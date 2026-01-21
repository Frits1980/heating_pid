"""Zone logic module for EMS Zone Master.

Handles setpoint calculation, adaptive start, and manual setpoint expiration.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from homeassistant.util import dt as dt_util

from .const import INITIAL_WARMUP_GUESS, SYNC_LOOK_AHEAD

_LOGGER = logging.getLogger(__name__)


class ZoneLogic:
    """Static methods for zone setpoint and adaptive start logic.

    This class provides stateless utility methods for:
    - Calculating effective setpoint (away > manual > schedule > default)
    - Checking adaptive start preheating conditions
    - Checking manual setpoint expiration on schedule transition
    """

    @staticmethod
    def check_manual_setpoint_expiration(
        manual_setpoint: float | None,
        manual_setpoint_schedule_state: bool | None,
        schedule_reader,
        now: datetime,
    ) -> tuple[float | None, bool | None]:
        """Check if manual setpoint should expire due to schedule transition.

        Args:
            manual_setpoint: Current manual setpoint if set
            manual_setpoint_schedule_state: Schedule state when manual was set
            schedule_reader: Schedule reader instance
            now: Current time

        Returns:
            Tuple of (manual_setpoint, manual_setpoint_schedule_state)
            Returns (None, None) if manual setpoint expired
        """
        if manual_setpoint is None or schedule_reader is None:
            return manual_setpoint, manual_setpoint_schedule_state

        current_schedule_state = schedule_reader.is_schedule_active(now)
        if manual_setpoint_schedule_state is not None:
            if current_schedule_state != manual_setpoint_schedule_state:
                # Schedule transitioned - clear manual override
                _LOGGER.info(
                    "Manual setpoint expired (schedule transitioned)"
                )
                return None, None

        return manual_setpoint, manual_setpoint_schedule_state

    @staticmethod
    def calculate_effective_setpoint(
        default_setpoint: float,
        manual_setpoint: float | None,
        away_mode_active: bool,
        away_temp: float,
        schedule_reader,
        sync_forced: bool,
        now: datetime,
    ) -> tuple[float, bool, bool]:
        """Calculate effective setpoint with all modifiers.

        Priority hierarchy (highest to lowest):
        1. Away mode
        2. Manual setpoint
        3. Schedule setpoint (with adaptive start)
        4. Default setpoint

        Args:
            default_setpoint: Zone default temperature
            manual_setpoint: Manual override temperature
            away_mode_active: Whether away mode is active
            away_temp: Temperature when away
            schedule_reader: Schedule reader instance
            sync_forced: Whether zone is sync-forced to preheat
            now: Current time

        Returns:
            Tuple of (setpoint, adaptive_start_active, sync_forced)
        """
        adaptive_start_active = False

        # Priority 1: Away mode
        if away_mode_active:
            return away_temp, False, False

        # Priority 2: Manual setpoint
        if manual_setpoint is not None:
            return manual_setpoint, False, False

        # Priority 3: Schedule (with adaptive start)
        if schedule_reader is not None:
            # Get scheduled setpoint
            scheduled_setpoint = schedule_reader.get_current_setpoint(now)

            # Check for adaptive start or sync-forced preheat
            if not schedule_reader.is_schedule_active(now):
                # Currently in setback period, check if we need to preheat
                time_to_active = schedule_reader.get_time_to_next_active(now)
                target_temp = schedule_reader.get_next_block_setpoint(now)

                if time_to_active is not None and target_temp is not None:
                    # Will check adaptive start in PID update phase
                    # Here we just use the default for now
                    return default_setpoint, False, sync_forced
            else:
                # Schedule is active, use scheduled setpoint
                return scheduled_setpoint, False, False

        # Priority 4: Default setpoint
        return default_setpoint, False, False

    @staticmethod
    def check_adaptive_start(
        current_temp: float | None,
        warmup_factor: float,
        sync_forced: bool,
        schedule_reader,
        now: datetime,
    ) -> bool:
        """Check if adaptive start preheating should be active.

        Args:
            current_temp: Current zone temperature
            warmup_factor: Learned warmup time (minutes per degree)
            sync_forced: Whether zone is sync-forced
            schedule_reader: Schedule reader instance
            now: Current time

        Returns:
            True if adaptive start should be active (preheating)
        """
        if current_temp is None or schedule_reader is None:
            return False

        # Don't preheat if already in active period
        if schedule_reader.is_schedule_active(now):
            return False

        time_to_active = schedule_reader.get_time_to_next_active(now)
        target_temp = schedule_reader.get_next_block_setpoint(now)

        if time_to_active is None or target_temp is None:
            return False

        temp_delta = target_temp - current_temp

        if sync_forced:
            # Forced by synchronization - start heating now
            return True
        elif temp_delta > 0:
            # Calculate preheat time based on learned warmup factor
            preheat_minutes = temp_delta * warmup_factor
            preheat_time = timedelta(minutes=preheat_minutes)

            # Start preheating if within preheat window
            if time_to_active <= preheat_time:
                return True

        return False

    @staticmethod
    def get_preheat_target(
        schedule_reader,
        now: datetime,
    ) -> float | None:
        """Get the target temperature for preheating.

        Args:
            schedule_reader: Schedule reader instance
            now: Current time

        Returns:
            Target temperature for next active block, or None
        """
        if schedule_reader is None:
            return None
        return schedule_reader.get_next_block_setpoint(now)
