"""Schedule reader for Home Assistant schedule helper entities.

Reads schedule helper entities to determine target setpoints throughout
the day. Uses the schedule helper's temp attribute which HA maintains
based on the currently active time block.

The integration uses schedule entities to:
1. Determine when to start heating (with adaptive start)
2. Set target temperatures for different times of day
3. Trigger setpoint changes at scheduled times

Home Assistant schedule helpers expose:
- state: "on" when a time block is active, "off" otherwise
- attributes.temp: Temperature from the currently active block's data field
- attributes.next_event: Datetime of the next schedule transition

Each time block in the schedule UI can have a "temp" value in its data field.
When no block is active, the default_setpoint is used.
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


def _parse_temperature(value: Any) -> float | None:
    """Parse a temperature value, handling European comma decimals.

    Args:
        value: Temperature value (int, float, or string)

    Returns:
        Parsed float value, or None if parsing fails
    """
    if value is None:
        return None

    # Already a number
    if isinstance(value, (int, float)):
        return float(value)

    # String - handle European comma decimal separator
    if isinstance(value, str):
        try:
            # Replace comma with dot for European format (e.g., "19,5" -> "19.5")
            normalized = value.replace(",", ".")
            return float(normalized)
        except ValueError:
            _LOGGER.warning("Failed to parse temperature value: %s", value)
            return None

    _LOGGER.warning("Unexpected temperature type: %s (%s)", value, type(value).__name__)
    return None


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

        Home Assistant's schedule helper exposes the current temperature
        directly via the 'temp' attribute when a schedule block is active.

        Args:
            now: Current datetime, or None to use current time (unused, kept for API compatibility)

        Returns:
            Target temperature based on schedule (°C)
        """
        state = self.hass.states.get(self.entity_id)
        if state is None:
            _LOGGER.debug("Schedule entity not found: %s", self.entity_id)
            return self.default_setpoint

        # Check if schedule is currently active (in a time block)
        if state.state != "on":
            return self.default_setpoint

        # Read temperature from the 'temp' attribute (HA provides this directly)
        temp_value = state.attributes.get("temp")
        if temp_value is not None:
            parsed = _parse_temperature(temp_value)
            if parsed is not None:
                return parsed
            _LOGGER.warning(
                "Schedule %s has invalid temp value: %s",
                self.entity_id,
                temp_value,
            )

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

        Uses HA's next_event attribute when schedule is currently off.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Time until next active period starts, or None if no schedule
        """
        if now is None:
            now = dt_util.now()

        state = self.hass.states.get(self.entity_id)
        if state is None:
            return None

        # If schedule is already active, return 0
        if state.state == "on":
            return timedelta(0)

        # Use HA's next_event attribute for the next transition
        next_event = state.attributes.get("next_event")
        if next_event is None:
            return None

        # next_event is already a datetime object from HA
        if isinstance(next_event, datetime):
            if next_event > now:
                return next_event - now
            return timedelta(0)

        return None

    def get_time_to_next_event(self, now: datetime | None = None) -> timedelta | None:
        """Get time until the next scheduled event (start or end).

        Uses HA's next_event attribute directly.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Time until next event, or None if no schedule
        """
        if now is None:
            now = dt_util.now()

        state = self.hass.states.get(self.entity_id)
        if state is None:
            return None

        # Use HA's next_event attribute
        next_event = state.attributes.get("next_event")
        if next_event is None:
            return None

        # next_event is already a datetime object from HA
        if isinstance(next_event, datetime):
            if next_event > now:
                return next_event - now
            return timedelta(0)

        return None

    def _get_schedule_state(self) -> dict[str, Any] | None:
        """Get the current state of the schedule entity.

        Note: This method is kept for backwards compatibility with legacy code
        that parses weekday data. The main methods now use HA's direct attributes
        (state, temp, next_event) instead.

        Returns:
            Schedule state attributes, or None if entity not found or invalid
        """
        try:
            state = self.hass.states.get(self.entity_id)
            if state is None:
                _LOGGER.debug("Schedule entity not found: %s", self.entity_id)
                return None

            # Schedule entities store their config in attributes
            return dict(state.attributes)
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

    def _parse_time(self, time_value: str | time) -> time | None:
        """Parse a time value (string or time object) into a time object.

        Args:
            time_value: Time string (HH:MM:SS or HH:MM) or time object

        Returns:
            time object or None if invalid
        """
        # Already a time object - return as-is
        if isinstance(time_value, time):
            return time_value

        # Handle string parsing
        if not isinstance(time_value, str):
            _LOGGER.warning("Invalid time type: %s (%s)", time_value, type(time_value).__name__)
            return None

        try:
            if len(time_value) == 8:  # HH:MM:SS
                parts = time_value.split(":")
                return time(int(parts[0]), int(parts[1]), int(parts[2]))
            elif len(time_value) == 5:  # HH:MM
                parts = time_value.split(":")
                return time(int(parts[0]), int(parts[1]))
            else:
                _LOGGER.warning("Invalid time format: %s", time_value)
                return None
        except (ValueError, IndexError) as err:
            _LOGGER.warning("Failed to parse time '%s': %s", time_value, err)
            return None

    def is_schedule_active(self, now: datetime | None = None) -> bool:
        """Check if the schedule is currently in an active period.

        Home Assistant's schedule helper state is "on" when in a time block.

        Args:
            now: Current datetime, or None to use current time (unused, kept for API compatibility)

        Returns:
            True if currently in a scheduled block (not in default/off period)
        """
        state = self.hass.states.get(self.entity_id)
        if state is None:
            return False

        return state.state == "on"

    async def get_next_block_setpoint_async(self, now: datetime | None = None) -> float | None:
        """Get the setpoint of the next scheduled block (async version).

        Fetches full schedule data via schedule.get_schedule service to determine
        the next block's temperature for adaptive start preheating.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Temperature of next active block, or None if unavailable
        """
        if now is None:
            now = dt_util.now()

        # Try to get full schedule data
        schedule_data = await self._fetch_full_schedule()
        if schedule_data is None:
            return None

        # Find the next block after current time
        return self._find_next_block_temp(now, schedule_data)

    def get_next_block_setpoint(self, now: datetime | None = None) -> float | None:
        """Get the setpoint of the next scheduled block (sync fallback).

        Note: This sync version can only return the current block's temp from
        entity attributes. For full next-block detection, use get_next_block_setpoint_async.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Temperature of current active block, or None if schedule is off
        """
        state = self.hass.states.get(self.entity_id)
        if state is None:
            return None

        # If schedule is active, return current temp
        if state.state == "on":
            temp_value = state.attributes.get("temp")
            if temp_value is not None:
                return _parse_temperature(temp_value)

        return None

    async def _fetch_full_schedule(self) -> dict[str, Any] | None:
        """Fetch full schedule data via schedule.get_schedule service.

        Returns:
            Full schedule with weekday blocks, or None if unavailable
        """
        try:
            response = await self.hass.services.async_call(
                "schedule",
                "get_schedule",
                {"entity_id": self.entity_id},
                blocking=True,
                return_response=True,
            )
            if response and self.entity_id in response:
                return response[self.entity_id]
        except Exception as err:
            _LOGGER.debug("Failed to fetch schedule data for %s: %s", self.entity_id, err)
        return None

    def _find_next_block_temp(
        self, now: datetime, schedule_data: dict[str, Any]
    ) -> float | None:
        """Find the temperature of the next schedule block.

        Args:
            now: Current datetime
            schedule_data: Full schedule data from get_schedule service

        Returns:
            Temperature of next block, or None if not found
        """
        current_time = now.time()

        # Check today first, then tomorrow
        for day_offset in range(2):
            check_date = now + timedelta(days=day_offset)
            day_name = WEEKDAY_NAMES[check_date.weekday()]
            day_blocks = schedule_data.get(day_name, [])

            if not day_blocks:
                continue

            # Sort blocks by start time
            sorted_blocks = sorted(
                day_blocks,
                key=lambda b: self._parse_time(b.get("from", "99:99:99")) or time(23, 59, 59)
            )

            for block in sorted_blocks:
                from_time = self._parse_time(block.get("from", "00:00:00"))
                if from_time is None:
                    continue

                # For today, only consider blocks that start after current time
                # For tomorrow, consider all blocks
                if day_offset == 0 and from_time <= current_time:
                    continue

                # Found the next block - get its temperature
                data = block.get("data", {})
                if isinstance(data, dict) and self.DATA_TEMP_KEY in data:
                    return _parse_temperature(data[self.DATA_TEMP_KEY])
                return self.default_setpoint

        return None

    async def is_first_block_of_day_async(self, now: datetime | None = None) -> bool:
        """Check if currently in the first schedule block of the day.

        Used for quiet mode detection.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            True if in the first block of the day
        """
        if now is None:
            now = dt_util.now()

        # Must be in an active schedule block
        state = self.hass.states.get(self.entity_id)
        if state is None or state.state != "on":
            return False

        schedule_data = await self._fetch_full_schedule()
        if schedule_data is None:
            return False

        return self._is_in_first_block(now, schedule_data)

    def _is_in_first_block(self, now: datetime, schedule_data: dict[str, Any]) -> bool:
        """Check if the current time is in the first block of the day.

        Args:
            now: Current datetime
            schedule_data: Full schedule data

        Returns:
            True if in first block of the day
        """
        day_name = WEEKDAY_NAMES[now.weekday()]
        day_blocks = schedule_data.get(day_name, [])

        if not day_blocks:
            return False

        # Sort blocks by start time to find the first one
        sorted_blocks = sorted(
            day_blocks,
            key=lambda b: self._parse_time(b.get("from", "99:99:99")) or time(23, 59, 59)
        )

        first_block = sorted_blocks[0]
        from_time = self._parse_time(first_block.get("from", "00:00:00"))
        to_time = self._parse_time(first_block.get("to", "00:00:00"))

        if from_time is None or to_time is None:
            return False

        current_time = now.time()

        # Check if we're in this first block
        if from_time <= current_time < to_time:
            return True

        # Handle overnight blocks
        if from_time > to_time:
            if current_time >= from_time or current_time < to_time:
                return True

        return False

    async def get_first_block_start_time_async(self, now: datetime | None = None) -> datetime | None:
        """Get the start time of today's first schedule block.

        Used for quiet mode ramp calculation.

        Args:
            now: Current datetime, or None to use current time

        Returns:
            Datetime when today's first block started, or None if not in first block
        """
        if now is None:
            now = dt_util.now()

        schedule_data = await self._fetch_full_schedule()
        if schedule_data is None:
            return None

        day_name = WEEKDAY_NAMES[now.weekday()]
        day_blocks = schedule_data.get(day_name, [])

        if not day_blocks:
            return None

        # Sort blocks by start time
        sorted_blocks = sorted(
            day_blocks,
            key=lambda b: self._parse_time(b.get("from", "99:99:99")) or time(23, 59, 59)
        )

        first_block = sorted_blocks[0]
        from_time = self._parse_time(first_block.get("from", "00:00:00"))

        if from_time is None:
            return None

        # Combine with today's date
        return datetime.combine(now.date(), from_time, tzinfo=now.tzinfo)
