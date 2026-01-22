"""State debouncer for EMS Zone Master.

Manages debounced state change reactions for entities like window sensors,
presence sensors, and manual setpoints.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime  # Used for type hints in PendingChange
from typing import Awaitable, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


@dataclass
class PendingChange:
    """Represents a pending state change awaiting debounce confirmation.

    Attributes:
        new_state: The new state value
        detected_at: When the state change was first detected
        delay_seconds: How long to wait before confirming
        callback: Async function to call when change is confirmed
        cancel_timer: Function to cancel the debounce timer
    """

    new_state: str
    detected_at: datetime
    delay_seconds: float
    callback: Callable[[], Awaitable[None]]
    cancel_timer: Callable[[], None] | None = None


class StateDebouncer:
    """Manages debounced state change reactions.

    This class tracks entity state changes and applies debouncing
    before triggering callbacks. This prevents rapid state toggling
    from causing excessive updates.

    Example use cases:
    - Window sensors: Wait 30s before treating window as open/closed
    - Manual setpoints: Wait 5s before applying to avoid rapid changes
    - Presence: Wait 30 min before activating away mode
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the state debouncer.

        Args:
            hass: Home Assistant instance
        """
        self._hass = hass
        self._pending: dict[str, PendingChange] = {}
        self._unsub_listeners: list[Callable[[], None]] = []

    def track_entity(
        self,
        entity_id: str,
        delay_seconds: float,
        on_confirmed: Callable[[str], Awaitable[None]],
    ) -> None:
        """Start tracking an entity for debounced state changes.

        Args:
            entity_id: Entity to track
            delay_seconds: Seconds to wait before confirming change
            on_confirmed: Async callback when change is confirmed
        """
        @callback
        async def _state_listener(event: str | None = None) -> None:
            """Handle state change events."""
            state = self._hass.states.get(entity_id)
            if state is None:
                return

            new_state_value = state.state
            now = dt_util.now()

            # Check if there's a pending change
            if entity_id in self._pending:
                pending = self._pending[entity_id]

                # If state reverted to original, cancel pending change
                if new_state_value == pending.new_state:
                    # State changed again, ignore
                    pass
                elif new_state_value == self._get_previous_state(entity_id):
                    # State reverted, cancel pending
                    _LOGGER.debug(
                        "State reverted for %s to %s, canceling pending change",
                        entity_id,
                        new_state_value,
                    )
                    if pending.cancel_timer:
                        pending.cancel_timer()
                    del self._pending[entity_id]

                # Same as new state, reset timer
                if pending.new_state == new_state_value:
                    if pending.cancel_timer:
                        pending.cancel_timer()

                    # Schedule new timer
                    pending.cancel_timer = self._schedule_confirmation(
                        entity_id, pending, now
                    )
                return

            # Store previous state
            previous = getattr(self, f"_prev_state_{entity_id}", None)

            # Only trigger on actual changes
            if new_state_value != previous:
                _LOGGER.debug(
                    "State change detected for %s: %s -> %s (debounce %.0fs)",
                    entity_id,
                    previous,
                    new_state_value,
                    delay_seconds,
                )

                # Create pending change
                change = PendingChange(
                    new_state=new_state_value,
                    detected_at=now,
                    delay_seconds=delay_seconds,
                    callback=lambda: on_confirmed(new_state_value),
                )

                # Schedule confirmation
                change.cancel_timer = self._schedule_confirmation(
                    entity_id, change, now
                )
                self._pending[entity_id] = change

        # Track previous state
        setattr(self, f"_prev_state_{entity_id}", None)

        # Subscribe to state changes using proper HA event tracking
        self._unsub_listeners.append(
            async_track_state_change_event(
                self._hass, entity_id, _state_listener
            )
        )

        # Set initial state
        state = self._hass.states.get(entity_id)
        if state is not None:
            setattr(self, f"_prev_state_{entity_id}", state.state)

    def _get_previous_state(self, entity_id: str) -> str | None:
        """Get the previously stored state for an entity."""
        return getattr(self, f"_prev_state_{entity_id}", None)

    def _schedule_confirmation(
        self, entity_id: str, change: PendingChange, now: datetime
    ) -> Callable[[], None]:
        """Schedule a callback to confirm the state change.

        Args:
            entity_id: Entity being tracked
            change: Pending change info
            now: Current time

        Returns:
            Function to cancel the scheduled callback
        """

        async def _confirm_callback():
            try:
                # Verify state hasn't changed
                current = self._hass.states.get(entity_id)
                if current is None:
                    return

                if current.state == change.new_state:
                    _LOGGER.debug(
                        "State change confirmed for %s: %s",
                        entity_id,
                        change.new_state,
                    )
                    # Update previous state
                    setattr(self, f"_prev_state_{entity_id}", change.new_state)
                    # Call callback
                    await change.callback()
                    # Clear pending
                    del self._pending[entity_id]
                else:
                    _LOGGER.debug(
                        "State changed again for %s, re-scheduling",
                        entity_id,
                    )
                    # State changed again, reschedule
                    change_new = PendingChange(
                        new_state=current.state,
                        detected_at=dt_util.now(),
                        delay_seconds=change.delay_seconds,
                        callback=change.callback,
                    )
                    change_new.cancel_timer = self._schedule_confirmation(
                        entity_id, change_new, dt_util.now()
                    )
                    self._pending[entity_id] = change_new

            except Exception as err:
                _LOGGER.error("Error in state confirmation callback: %s", err)

        # Schedule the callback using HA's event loop
        timer_handle = self._hass.loop.call_later(
            change.delay_seconds, lambda: asyncio.create_task(_confirm_callback())
        )
        return timer_handle.cancel

    def cancel_pending(self, entity_id: str) -> None:
        """Cancel any pending state change for an entity.

        Args:
            entity_id: Entity to cancel pending change for
        """
        if entity_id in self._pending:
            pending = self._pending[entity_id]
            if pending.cancel_timer:
                pending.cancel_timer()
            del self._pending[entity_id]
            _LOGGER.debug("Canceled pending state change for %s", entity_id)

    def shutdown(self) -> None:
        """Cancel all pending changes and listeners."""
        # Cancel all pending timers
        for change in self._pending.values():
            if change.cancel_timer:
                change.cancel_timer()
        self._pending.clear()

        # Unsubscribe all listeners
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        _LOGGER.debug("State debouncer shutdown complete")
