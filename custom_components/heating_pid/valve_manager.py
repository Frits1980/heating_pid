"""Valve manager for EMS Zone Master.

Handles valve control, anti-cycling protection, and maintenance cycling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import VALVE_MAINTENANCE_DAYS, VALVE_MAINTENANCE_DURATION, VALVE_MAINTENANCE_HOUR

_LOGGER = logging.getLogger(__name__)


class ValveManager:
    """Manages zone valve control with anti-cycling and maintenance.

    This class handles:
    - Opening/closing valves based on demand
    - Anti-cycling protection (min on/off times)
    - Periodic maintenance cycling for inactive valves
    - Support for both switch and climate entity types

    Attributes:
        hass: Home Assistant instance
        min_on_time: Minimum time valve must stay open (minutes)
        min_off_time: Minimum time valve must stay closed (minutes)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        min_on_time: int,
        min_off_time: int,
    ) -> None:
        """Initialize the valve manager.

        Args:
            hass: Home Assistant instance
            min_on_time: Minimum valve on time in minutes
            min_off_time: Minimum valve off time in minutes
        """
        self.hass = hass
        self._min_on_time = min_on_time
        self._min_off_time = min_off_time

    async def set_valve_state(
        self,
        entity_id: str,
        valve_opened_at: datetime | None,
        valve_closed_at: datetime | None,
        setpoint: float,
        should_open: bool,
        cooldown_active: bool,
    ) -> tuple[datetime | None, datetime | None, datetime]:
        """Control a valve with anti-cycling protection.

        Args:
            entity_id: Valve entity ID
            valve_opened_at: When valve was last opened
            valve_closed_at: When valve was last closed
            setpoint: Current zone setpoint (for climate entities)
            should_open: True to open valve, False to close
            cooldown_active: Whether cooldown mode is active

        Returns:
            Tuple of (new_valve_opened_at, new_valve_closed_at, last_activity)
        """
        # Don't open valves during cooldown
        if should_open and cooldown_active:
            should_open = False

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Valve entity not found: %s", entity_id)
            return valve_opened_at, valve_closed_at, dt_util.now()

        domain = entity_id.split(".")[0]
        now = dt_util.now()

        if domain == "switch":
            return await self._control_switch_valve(
                entity_id, valve_opened_at, valve_closed_at, should_open, now
            )
        elif domain == "climate":
            return await self._control_climate_valve(
                entity_id, valve_opened_at, valve_closed_at, should_open, setpoint, now
            )
        else:
            _LOGGER.warning(
                "Unsupported valve entity domain: %s for %s",
                domain,
                entity_id,
            )
            return valve_opened_at, valve_closed_at, now

    async def _control_switch_valve(
        self,
        entity_id: str,
        valve_opened_at: datetime | None,
        valve_closed_at: datetime | None,
        should_open: bool,
        now: datetime,
    ) -> tuple[datetime | None, datetime | None, datetime]:
        """Control a switch-type valve entity.

        Args:
            entity_id: Switch entity ID
            valve_opened_at: When valve was last opened
            valve_closed_at: When valve was last closed
            should_open: True to turn on (open), False to turn off (close)
            now: Current time

        Returns:
            Tuple of (new_valve_opened_at, new_valve_closed_at, last_activity)
        """
        current_state = self.hass.states.get(entity_id)
        if current_state is None:
            return valve_opened_at, valve_closed_at, now

        is_on = current_state.state == "on"

        if should_open and not is_on:
            # Check minimum off-time before opening
            if valve_closed_at and self._min_off_time > 0:
                time_since_close = (now - valve_closed_at).total_seconds() / 60
                if time_since_close < self._min_off_time:
                    _LOGGER.debug(
                        "Valve %s: skipping open, only %.1f min since close (min: %d)",
                        entity_id,
                        time_since_close,
                        self._min_off_time,
                    )
                    return valve_opened_at, valve_closed_at, now

            await self._safe_service_call(
                "switch", "turn_on", {"entity_id": entity_id}
            )
            _LOGGER.debug("Opened valve: %s", entity_id)
            return now, valve_closed_at, now

        elif not should_open and is_on:
            # Check minimum on-time before closing
            if valve_opened_at and self._min_on_time > 0:
                time_since_open = (now - valve_opened_at).total_seconds() / 60
                if time_since_open < self._min_on_time:
                    _LOGGER.debug(
                        "Valve %s: skipping close, only %.1f min since open (min: %d)",
                        entity_id,
                        time_since_open,
                        self._min_on_time,
                    )
                    return valve_opened_at, valve_closed_at, now

            await self._safe_service_call(
                "switch", "turn_off", {"entity_id": entity_id}
            )
            _LOGGER.debug("Closed valve: %s", entity_id)
            return valve_opened_at, now, now

        return valve_opened_at, valve_closed_at, now

    async def _control_climate_valve(
        self,
        entity_id: str,
        valve_opened_at: datetime | None,
        valve_closed_at: datetime | None,
        should_open: bool,
        setpoint: float,
        now: datetime,
    ) -> tuple[datetime | None, datetime | None, datetime]:
        """Control a climate-type valve entity (e.g., TRV).

        For climate entities, we set HVAC mode to heat/off and
        optionally set the target temperature.

        Args:
            entity_id: Climate entity ID
            valve_opened_at: When valve was last opened
            valve_closed_at: When valve was last closed
            should_open: True to enable heating, False to turn off
            setpoint: Target temperature to set
            now: Current time

        Returns:
            Tuple of (new_valve_opened_at, new_valve_closed_at, last_activity)
        """
        current_state = self.hass.states.get(entity_id)
        if current_state is None:
            return valve_opened_at, valve_closed_at, now

        current_mode = current_state.state
        new_opened_at = valve_opened_at
        new_closed_at = valve_closed_at

        if should_open:
            # Check minimum off-time before opening
            if current_mode != "heat":
                if valve_closed_at and self._min_off_time > 0:
                    time_since_close = (now - valve_closed_at).total_seconds() / 60
                    if time_since_close < self._min_off_time:
                        _LOGGER.debug(
                            "Climate %s: skipping heat, only %.1f min since off (min: %d)",
                            entity_id,
                            time_since_close,
                            self._min_off_time,
                        )
                        return valve_opened_at, valve_closed_at, now

                await self._safe_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "heat"},
                )
                _LOGGER.debug("Set climate to heat: %s", entity_id)
                new_opened_at = now

            # Also set temperature to zone setpoint
            await self._safe_service_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": setpoint},
            )

        elif current_mode not in ("off", "unavailable"):
            # Check minimum on-time before closing
            if valve_opened_at and self._min_on_time > 0:
                time_since_open = (now - valve_opened_at).total_seconds() / 60
                if time_since_open < self._min_on_time:
                    _LOGGER.debug(
                        "Climate %s: skipping off, only %.1f min since heat (min: %d)",
                        entity_id,
                        time_since_open,
                        self._min_on_time,
                    )
                    return valve_opened_at, valve_closed_at, now

            await self._safe_service_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": "off"},
            )
            _LOGGER.debug("Set climate to off: %s", entity_id)
            new_closed_at = now

        return new_opened_at, new_closed_at, now

    async def perform_maintenance(
        self,
        entity_id: str,
        duration: int,
    ) -> datetime:
        """Perform a maintenance cycle on a valve.

        Opens the valve briefly then closes it to prevent seizing.

        Args:
            entity_id: Valve entity ID
            duration: Duration in seconds to keep valve open

        Returns:
            Timestamp when maintenance was performed
        """
        domain = entity_id.split(".")[0]
        now = dt_util.now()

        _LOGGER.debug(
            "Performing valve maintenance cycle for %s (%d seconds)",
            entity_id,
            duration,
        )

        try:
            if domain == "switch":
                await self._safe_service_call(
                    "switch", "turn_on", {"entity_id": entity_id}
                )
                await asyncio.sleep(duration)
                await self._safe_service_call(
                    "switch", "turn_off", {"entity_id": entity_id}
                )
            elif domain == "climate":
                await self._safe_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "heat"},
                )
                await asyncio.sleep(duration)
                await self._safe_service_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "off"},
                )

            _LOGGER.info("Valve maintenance complete: %s", entity_id)
            return now

        except Exception as err:
            _LOGGER.error("Valve maintenance failed for %s: %s", entity_id, err)
            return now

    def check_maintenance_needed(
        self,
        last_valve_activity: datetime | None,
        maintenance_pending: bool,
        now: datetime,
    ) -> bool:
        """Check if a valve needs maintenance cycling.

        Args:
            last_valve_activity: When valve was last active
            maintenance_pending: Whether maintenance is already pending
            now: Current time

        Returns:
            True if maintenance should be scheduled
        """
        # Only run during designated hour
        if now.hour != VALVE_MAINTENANCE_HOUR:
            return False

        maintenance_threshold = timedelta(days=VALVE_MAINTENANCE_DAYS)

        # Skip if valve was recently active
        if last_valve_activity is not None:
            inactive_time = now - last_valve_activity
            if inactive_time < maintenance_threshold:
                return False

        # Check if maintenance is already pending
        if maintenance_pending:
            return False

        return True

    async def _safe_service_call(
        self, domain: str, service: str, data: dict[str, str | float]
    ) -> bool:
        """Call a service with error handling.

        Args:
            domain: Service domain (e.g., "switch", "climate", "number")
            service: Service name (e.g., "turn_on", "set_temperature")
            data: Service data parameters

        Returns:
            True if service call succeeded, False otherwise
        """
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
            return True
        except Exception as err:
            entity_id = data.get("entity_id", "unknown")
            _LOGGER.error(
                "Service call %s.%s failed for %s: %s", domain, service, entity_id, err
            )
            return False
