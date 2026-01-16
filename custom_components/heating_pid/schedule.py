"""Schedule reader for Home Assistant schedule helper entities.

Reads schedule helper entities to determine target setpoints throughout
the day. Uses the schedule helper's data field to specify temperature
setpoints for each time block.

The integration uses schedule entities to:
1. Determine when to start heating (with adaptive start)
2. Set target temperatures for different times of day
3. Trigger setpoint changes at scheduled times

Schedule helpers store time blocks per day of week in the format:
{
    "monday": [{"from": "07:00:00", "to": "09:00:00", "data": {"temp": 21}}, ...],
    "tuesday": [...],
    ...
}

Each time block can specify a "temp" key in its data field. If not specified,
the default_setpoint is used during that block.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Day name mapping (Python weekday() returns 0=Monday)
WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class ScheduleEvent(NamedTuple):
    """Represents a scheduled event with time and setpoint.

    Attributes:
        time: Time of day for this event
        setpoint: Target temperature (°C)
        is_active: Whether heating should be active (True=start, False=end)
    """

    time: time
    setpoint: float
    is_active: bool


class ScheduleReader:
    """Reader for Home Assistant schedule helper entities.

    This class reads schedule helper entities and interprets them
    for heating control. It provides methods to:
    - Get the current scheduled setpoint
    - Get upcoming schedule events
    - Calculate time until next event

    Schedule helpers store time blocks as a list of time ranges per day.
    Each block can have a "data" field with a "temp" key specifying the
    setpoint for that period. Gaps between blocks use the default_setpoint.

    Example schedule block with data:
        {"from": "07:00:00", "to": "09:00:00", "data": {"temp": 21}}

    Attributes:
        hass: Home Assistant instance
        entity_id: Schedule helper entity ID
        default_setpoint: Setpoint when no schedule block is active
    """

    # Key used in schedule data for temperature
    DATA_TEMP_KEY = "temp"

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        default_setpoint: float = 18.0,
    ) -> None:
        """Initialize the schedule reader.

        Args:
            hass: Home Assistant instance
            entity_id: Entity ID of the schedule helper
            default_setpoint: Temperature when no schedule block is active (°C)
        """
        self.hass = hass
        self.entity_id = entity_id
        self.default_setpoint = default_setpoint

    def get_current_setpoint(self, now: datetime | None = None) -> float:
        """Get the setpoint for the current time.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Target temperature based on schedule (°C)
        """
        if now is None:
            now = dt_util.now()

        state = self._get_schedule_state()
        if state is None:
            return self.default_setpoint

        # Check if current time falls within an active block and get its temp
        block_temp = self._get_block_temperature(now, state)
        if block_temp is not None:
            return block_temp
        return self.default_setpoint

    def _get_block_temperature(
        self, now: datetime, schedule_state: dict[str, Any]
    ) -> float | None:
        """Get the temperature from the active schedule block's data field.

        Args:
            now: Datetime to check
            schedule_state: Schedule entity attributes

        Returns:
            Temperature from block's data["temp"], or None if not in a block
        """
        day_name = WEEKDAY_NAMES[now.weekday()]
        day_schedule = schedule_state.get(day_name, [])

        if not day_schedule:
            return None

        check_time = now.time()

        for block in day_schedule:
            # Validate block structure
            if not isinstance(block, dict):
                _LOGGER.warning(
                    "Invalid schedule block type for %s: expected dict, got %s",
                    self.entity_id,
                    type(block).__name__,
                )
                continue

            from_time = self._parse_time(block.get("from", "00:00:00"))
            to_time = self._parse_time(block.get("to", "00:00:00"))

            if from_time is None or to_time is None:
                continue

            in_block = False

            # Handle same-day blocks
            if from_time <= check_time < to_time:
                in_block = True
            # Handle overnight blocks (e.g., 22:00 to 06:00)
            elif from_time > to_time:
                if check_time >= from_time or check_time < to_time:
                    in_block = True

            if in_block:
                # Get temperature from block's data field
                data = block.get("data", {})
                if isinstance(data, dict) and self.DATA_TEMP_KEY in data:
                    try:
                        return float(data[self.DATA_TEMP_KEY])
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            "Invalid temp value in schedule data: %s",
                            data.get(self.DATA_TEMP_KEY),
                        )
                # Block is active but no temp specified, use default
                return self.default_setpoint

        return None

    def get_next_event(self, now: datetime | None = None) -> ScheduleEvent | None:
        """Get the next scheduled event after the given time.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Next schedule event, or None if no schedule configured
        """
        if now is None:
            now = dt_util.now()

        state = self._get_schedule_state()
        if state is None:
            return None

        events = self._parse_schedule_events(now, state)
        if not events:
            return None

        current_time = now.time()

        # Find the next event after current time
        for event in events:
            if event.time > current_time:
                return event

        # If no event found today, check tomorrow
        tomorrow = now + timedelta(days=1)
        tomorrow_events = self._parse_schedule_events(tomorrow, state)
        return tomorrow_events[0] if tomorrow_events else None

    def get_time_to_next_active(self, now: datetime | None = None) -> timedelta | None:
        """Get time until the next schedule activation (start of heating period).

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Time until next active period starts, or None if no schedule
        """
        if now is None:
            now = dt_util.now()

        # Cache schedule state once before looping
        state = self._get_schedule_state()
        if state is None:
            return None

        # Search up to 7 days ahead
        for day_offset in range(7):
            check_date = now + timedelta(days=day_offset)
            events = self._parse_schedule_events(check_date, state)
            for event in events:
                if event.is_active:  # This is a "start heating" event
                    event_datetime = datetime.combine(check_date.date(), event.time, tzinfo=dt_util.DEFAULT_TIME_ZONE)
                    if event_datetime > now:
                        return event_datetime - now

        return None

    def get_time_to_next_event(self, now: datetime | None = None) -> timedelta | None:
        """Get time until the next scheduled event (start or end).

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Time until next event, or None if no schedule
        """
        if now is None:
            now = dt_util.now()

        next_event = self.get_next_event(now)
        if next_event is None:
            return None

        # Calculate time to event
        event_datetime = datetime.combine(now.date(), next_event.time, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        if event_datetime <= now:
            # Event is tomorrow
            event_datetime += timedelta(days=1)

        return event_datetime - now

    def _get_schedule_state(self) -> dict[str, Any] | None:
        """Get the current state of the schedule entity.

        Returns:
            Schedule state attributes, or None if entity not found or invalid
        """
        try:
            state = self.hass.states.get(self.entity_id)
            if state is None:
                _LOGGER.debug("Schedule entity not found: %s", self.entity_id)
                return None

            # Schedule entities store their config in attributes
            attributes = dict(state.attributes)

            # Validate that schedule has expected structure (at least one weekday key)
            valid_days = [d for d in WEEKDAY_NAMES if d in attributes]
            if not valid_days:
                _LOGGER.warning(
                    "Schedule entity %s has no weekday data configured",
                    self.entity_id,
                )

            return attributes
        except Exception as err:
            _LOGGER.error(
                "Error reading schedule entity %s: %s",
                self.entity_id,
                err,
            )
            return None

    def _is_time_in_schedule(self, now: datetime, schedule_state: dict[str, Any]) -> bool:
        """Check if a datetime falls within active schedule blocks.

        Args:
            now: Datetime to check
            schedule_state: Schedule entity attributes

        Returns:
            True if time is in an active block
        """
        return self._get_block_temperature(now, schedule_state) is not None

    def _parse_schedule_events(
        self, date: datetime, schedule_state: dict[str, Any]
    ) -> list[ScheduleEvent]:
        """Parse schedule into a list of events for a specific date.

        Each time block generates two events: start (is_active=True) and
        end (is_active=False).

        Args:
            date: Date to parse schedule for
            schedule_state: Schedule entity attributes

        Returns:
            List of schedule events sorted by time
        """
        day_name = WEEKDAY_NAMES[date.weekday()]
        day_schedule = schedule_state.get(day_name, [])

        events: list[ScheduleEvent] = []

        for block in day_schedule:
            # Validate block structure
            if not isinstance(block, dict):
                _LOGGER.warning(
                    "Invalid schedule block type for %s on %s: expected dict, got %s",
                    self.entity_id,
                    day_name,
                    type(block).__name__,
                )
                continue

            from_time = self._parse_time(block.get("from", "00:00:00"))
            to_time = self._parse_time(block.get("to", "00:00:00"))

            if from_time is None or to_time is None:
                _LOGGER.debug(
                    "Skipping schedule block with invalid time in %s on %s",
                    self.entity_id,
                    day_name,
                )
                continue

            # Get temperature from block's data field
            data = block.get("data", {})
            block_temp = self.default_setpoint
            if isinstance(data, dict) and self.DATA_TEMP_KEY in data:
                try:
                    block_temp = float(data[self.DATA_TEMP_KEY])
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Invalid temp value in schedule block data for %s: %s",
                        self.entity_id,
                        data.get(self.DATA_TEMP_KEY),
                    )

            # Start of active period
            events.append(ScheduleEvent(
                time=from_time,
                setpoint=block_temp,
                is_active=True,
            ))

            # End of active period (only if not overnight)
            if to_time > from_time:
                events.append(ScheduleEvent(
                    time=to_time,
                    setpoint=self.default_setpoint,
                    is_active=False,
                ))

        # Sort by time
        events.sort(key=lambda e: e.time)
        return events

    def _parse_time(self, time_str: str) -> time | None:
        """Parse a time string in HH:MM:SS or HH:MM format.

        Args:
            time_str: Time string to parse

        Returns:
            time object or None if invalid
        """
        try:
            if len(time_str) == 8:  # HH:MM:SS
                parts = time_str.split(":")
                return time(int(parts[0]), int(parts[1]), int(parts[2]))
            elif len(time_str) == 5:  # HH:MM
                parts = time_str.split(":")
                return time(int(parts[0]), int(parts[1]))
            else:
                _LOGGER.warning("Invalid time format: %s", time_str)
                return None
        except (ValueError, IndexError) as err:
            _LOGGER.warning("Failed to parse time '%s': %s", time_str, err)
            return None

    def is_schedule_active(self, now: datetime | None = None) -> bool:
        """Check if the schedule is currently in an active period.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            True if currently in a scheduled block (not in default/off period)
        """
        if now is None:
            now = dt_util.now()

        state = self._get_schedule_state()
        if state is None:
            return False

        return self._get_block_temperature(now, state) is not None

    def get_next_block_setpoint(self, now: datetime | None = None) -> float | None:
        """Get the setpoint of the next scheduled block.

        Used for adaptive start to know what temperature to preheat to.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Temperature of next active block, or None if no upcoming block
        """
        next_event = self.get_next_event(now)
        if next_event is not None and next_event.is_active:
            return next_event.setpoint
        return None
