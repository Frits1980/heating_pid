"""Data coordinator for EMS Zone Master.

The coordinator is the central hub that:
- Polls all zone sensors at a regular interval (30s)
- Aggregates demand from all zones
- Calculates target flow temperature
- Controls the heater entity
- Manages zone states and PID controllers
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AWAY_DELAY,
    CONF_FLOW_TEMP_ENTITY,
    CONF_HEATER_ENTITY,
    CONF_KD,
    CONF_KE,
    CONF_KI,
    CONF_KP,
    CONF_MAX_EGRESS,
    CONF_MIN_EGRESS,
    CONF_MIN_IGNITION_LEVEL,
    CONF_OUTDOOR_REFERENCE_TEMP,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_QUIET_MODE_MAX_FLOW,
    CONF_QUIET_MODE_RAMP_MINUTES,
    CONF_RETURN_TEMP_ENTITY,
    CONF_SOLAR_DROP,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_THRESHOLD,
    CONF_VALVE_MIN_OFF_TIME,
    CONF_VALVE_MIN_ON_TIME,
    CONF_ZONE_AWAY_TEMP,
    CONF_ZONE_DEFAULT_SETPOINT,
    CONF_ZONE_NAME,
    CONF_ZONE_SCHEDULE_ENTITY,
    CONF_ZONE_SOLAR_DROP,
    CONF_ZONE_TEMP_ENTITY,
    CONF_ZONE_VALVE_ENTITY,
    CONF_ZONE_WINDOW_ENTITY,
    CONF_ZONES,
    COORDINATOR_UPDATE_INTERVAL,
    DEFAULT_AWAY_DELAY,
    DEFAULT_AWAY_TEMP,
    DEFAULT_OUTDOOR_REFERENCE_TEMP,
    DEFAULT_QUIET_MODE_MAX_FLOW,
    DEFAULT_QUIET_MODE_RAMP_MINUTES,
    DEFAULT_VALVE_MIN_OFF_TIME,
    DEFAULT_VALVE_MIN_ON_TIME,
    DEFAULT_WINDOW_DROP,
    DOMAIN,
    INITIAL_WARMUP_GUESS,
    MIN_EFFICIENT_DELTA_T,
    PERSISTENCE_INTERVAL,
    SYNC_LOOK_AHEAD,
    VALVE_MAINTENANCE_DAYS,
    VALVE_MAINTENANCE_DURATION,
    VALVE_MAINTENANCE_HOUR,
    VERSION,
)
from .heater_controller import HeaterController
from .pid import PIDController
from .state_debouncer import StateDebouncer
from .store import EmsZoneMasterStore
from .valve_manager import ValveManager
from .zone_logic import ZoneLogic
from .schedule import ScheduleReader

_LOGGER = logging.getLogger(__name__)


class ZoneState:
    """Holds runtime state for a single heating zone.

    Attributes:
        name: Zone identifier
        temp_entity_id: Entity ID of temperature sensor
        valve_entity_id: Entity ID of valve control (switch or climate)
        window_entity_id: Optional entity ID of window sensor
        schedule_entity_id: Optional entity ID of schedule helper
        setpoint: Current target temperature
        default_setpoint: Configured default temperature
        away_temp: Temperature when away mode is active
        current_temp: Last read temperature from sensor
        demand: Current calculated demand (0-100%)
        pid: PID controller instance for this zone
        manual_setpoint: Manually set temperature (overrides schedule)
        window_open: Whether window is detected as open
        warmup_factor: Learned minutes per degree for adaptive start
        schedule_reader: Schedule reader instance (if schedule configured)
        adaptive_start_active: Whether adaptive start preheat is active
        warmup_started_at: When current warmup cycle started (for learning)
        warmup_start_temp: Temperature when warmup started (for learning)
        warmup_target_temp: Target temperature for warmup (for learning)
    """

    def __init__(
        self,
        name: str,
        temp_entity_id: str,
        valve_entity_id: str,
        default_setpoint: float,
        pid: PIDController,
        window_entity_id: str | None = None,
        schedule_entity_id: str | None = None,
    ) -> None:
        """Initialize zone state."""
        self.name = name
        self.temp_entity_id = temp_entity_id
        self.valve_entity_id = valve_entity_id
        self.window_entity_id = window_entity_id
        self.schedule_entity_id = schedule_entity_id
        self.default_setpoint = default_setpoint
        self.setpoint = default_setpoint
        self.away_temp: float = DEFAULT_AWAY_TEMP
        self.current_temp: float | None = None
        self.demand: float = 0.0
        self.pid = pid
        self.manual_setpoint: float | None = None
        self.manual_setpoint_schedule_state: bool | None = None  # Schedule state when manual was set
        self.window_open: bool = False
        self.disabled: bool = False
        self.disabled_reason: str | None = None
        self.warmup_factor: float = INITIAL_WARMUP_GUESS
        self.solar_drop: float | None = None  # Zone-specific solar drop (None = use global)

        # Schedule and adaptive start
        self.schedule_reader: ScheduleReader | None = None  # Set by coordinator if schedule configured
        self.adaptive_start_active: bool = False
        self.sync_forced: bool = False  # Forced to start early due to synchronization

        # Warmup learning state
        self.warmup_started_at: datetime | None = None
        self.warmup_start_temp: float | None = None
        self.warmup_target_temp: float | None = None

        # Valve maintenance
        self.last_valve_activity: datetime | None = None
        self.valve_maintenance_pending: bool = False

        # Valve anti-cycling protection
        self.valve_opened_at: datetime | None = None
        self.valve_closed_at: datetime | None = None


class EmsZoneMasterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for EMS Zone Master integration.

    This coordinator:
    1. Reads temperature sensors for all zones every 30 seconds
    2. Updates PID controllers with current temperatures
    3. Calculates aggregated demand from all zones
    4. Determines target flow temperature based on demand curve
    5. Controls the heater entity (EMS-ESP flow temp setpoint)
    6. Manages valve states based on zone demand
    7. Handles efficiency features (cooldown, solar limiting)

    The demand curve formula:
        target_egress = min_egress + (max_demand / 100) × (max_egress - min_egress)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: EmsZoneMasterStore,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            entry: Config entry with integration settings
            store: Persistence store for learned data
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=COORDINATOR_UPDATE_INTERVAL),
        )
        self.entry = entry
        self.store = store
        self.zones: dict[str, ZoneState] = {}
        self._heater_entity_id: str = entry.data[CONF_HEATER_ENTITY]
        self._flow_temp_entity_id: str = entry.data[CONF_FLOW_TEMP_ENTITY]
        self._return_temp_entity_id: str = entry.data[CONF_RETURN_TEMP_ENTITY]
        self._outdoor_temp_entity_id: str = entry.data[CONF_OUTDOOR_TEMP_ENTITY]
        self._solar_power_entity_id: str | None = entry.data.get(CONF_SOLAR_POWER_ENTITY)
        self._min_egress: float = entry.data[CONF_MIN_EGRESS]
        self._max_egress: float = entry.data[CONF_MAX_EGRESS]
        self._min_ignition_level: float = entry.data[CONF_MIN_IGNITION_LEVEL]
        self._solar_threshold: float = entry.data[CONF_SOLAR_THRESHOLD]
        self._solar_drop: float = entry.data.get(CONF_SOLAR_DROP, 0.0)
        self._outdoor_reference_temp: float = entry.data.get(
            CONF_OUTDOOR_REFERENCE_TEMP, DEFAULT_OUTDOOR_REFERENCE_TEMP
        )
        self._valve_min_on_time: int = entry.data.get(
            CONF_VALVE_MIN_ON_TIME, DEFAULT_VALVE_MIN_ON_TIME
        )
        self._valve_min_off_time: int = entry.data.get(
            CONF_VALVE_MIN_OFF_TIME, DEFAULT_VALVE_MIN_OFF_TIME
        )
        self._quiet_mode_max_flow: float = entry.data.get(
            CONF_QUIET_MODE_MAX_FLOW, DEFAULT_QUIET_MODE_MAX_FLOW
        )
        self._quiet_mode_ramp_minutes: int = entry.data.get(
            CONF_QUIET_MODE_RAMP_MINUTES, DEFAULT_QUIET_MODE_RAMP_MINUTES
        )

        # Runtime state
        self._current_flow_temp: float | None = None
        self._current_return_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._solar_power: float | None = None
        self._target_flow_temp: float = self._min_egress
        self._max_demand: float = 0.0
        self._cooldown_active: bool = False
        self._heater_was_active: bool = False  # Track if heater was actively commanded
        self._unsub_persistence: CALLBACK_TYPE | None = None
        self._last_update: datetime | None = None  # Track time for PID dt calculation

        # Away mode state
        self._presence_entity_id: str | None = entry.data.get(CONF_PRESENCE_ENTITY)
        self._away_delay: int = entry.data.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY)
        self._away_mode_active: bool = False
        self._presence_lost_at: datetime | None = None  # When presence went "off"

        # Quiet mode state
        self._quiet_mode_active: bool = False
        self._first_block_start_time: datetime | None = None
        self._last_quiet_mode_check_date: datetime | None = None

        # Initialize controller and manager modules
        self._heater_controller = HeaterController(
            hass,
            self._heater_entity_id,
            self._min_egress,
            self._max_egress,
            self._min_ignition_level,
            self._quiet_mode_max_flow,
            self._quiet_mode_ramp_minutes,
        )
        self._valve_manager = ValveManager(
            hass,
            self._valve_min_on_time,
            self._valve_min_off_time,
        )

        # Initialize state debouncer for event-driven updates
        self._state_debouncer = StateDebouncer(hass)

        # Initialize zones from config
        self._init_zones()

        # Set up event-driven tracking for window sensors
        self._setup_window_tracking()

        # Set up periodic persistence
        self._unsub_persistence = async_track_time_interval(
            hass,
            self._async_persist_state,
            timedelta(minutes=PERSISTENCE_INTERVAL),
        )

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator and clean up resources."""
        # Shutdown state debouncer (cancels event listeners)
        self._state_debouncer.shutdown()

        # Cancel persistence timer
        if self._unsub_persistence:
            self._unsub_persistence()
            self._unsub_persistence = None

        # Final state save
        await self._do_persist_state()
        _LOGGER.debug("Coordinator shutdown complete")

    @callback
    def _async_persist_state(self, _now: datetime) -> None:
        """Persist current state to storage (scheduled callback).

        Saves PID integrals and warmup factors for all zones.
        """
        self.hass.async_create_task(self._do_persist_state())

    async def _do_persist_state(self) -> None:
        """Actually persist state to storage."""
        for name, zone in self.zones.items():
            self.store.set_pid_integral(name, zone.pid.integral)
            self.store.set_warmup_factor(name, zone.warmup_factor)
            self.store.set_manual_setpoint(name, zone.manual_setpoint)

        await self.store.async_save()
        _LOGGER.debug("Persisted state for %d zones", len(self.zones))

    def _init_zones(self) -> None:
        """Initialize zone states from configuration.

        Creates ZoneState objects for each configured zone,
        restoring learned warmup factors from the store.
        """
        for zone_config in self.entry.data.get(CONF_ZONES, []):
            name = zone_config[CONF_ZONE_NAME]

            # Create PID controller with zone-specific gains
            pid = PIDController(
                kp=zone_config[CONF_KP],
                ki=zone_config[CONF_KI],
                kd=zone_config[CONF_KD],
                ke=zone_config[CONF_KE],
                outdoor_reference_temp=self._outdoor_reference_temp,
            )

            # Restore integral from store if available, with validation
            # Prevents persisting unreasonable values that cause 100% demand lockup
            stored_integral = self.store.get_pid_integral(name)
            if stored_integral is not None:
                # Validate: max reasonable integral produces ~150% output before clamping
                # This allows for outdoor compensation but prevents runaway windup
                max_reasonable_integral = 300.0  # 150% output / Ki(0.5)
                if abs(stored_integral) <= max_reasonable_integral:
                    pid.integral = stored_integral
                else:
                    _LOGGER.warning(
                        "Zone %s: ignoring stored integral %.1f (exceeds max %.1f), resetting",
                        name,
                        stored_integral,
                        max_reasonable_integral,
                    )
                    pid.integral = 0.0

            # Restore tuned PID gains from store if available
            stored_gains = self.store.get_pid_gains(name)
            if stored_gains is not None:
                pid.kp = stored_gains["kp"]
                pid.ki = stored_gains["ki"]
                pid.kd = stored_gains["kd"]
                pid.ke = stored_gains["ke"]
                _LOGGER.info(
                    "Zone %s: restored PID gains Kp=%.1f, Ki=%.2f, Kd=%.1f, Ke=%.3f",
                    name,
                    pid.kp,
                    pid.ki,
                    pid.kd,
                    pid.ke,
                )

            zone = ZoneState(
                name=name,
                temp_entity_id=zone_config[CONF_ZONE_TEMP_ENTITY],
                valve_entity_id=zone_config[CONF_ZONE_VALVE_ENTITY],
                default_setpoint=zone_config[CONF_ZONE_DEFAULT_SETPOINT],
                pid=pid,
                window_entity_id=zone_config.get(CONF_ZONE_WINDOW_ENTITY),
                schedule_entity_id=zone_config.get(CONF_ZONE_SCHEDULE_ENTITY),
            )

            # Restore warmup factor from store
            stored_warmup = self.store.get_warmup_factor(name)
            if stored_warmup is not None:
                zone.warmup_factor = stored_warmup

            # Restore manual setpoint from store
            stored_manual = self.store.get_manual_setpoint(name)
            if stored_manual is not None:
                zone.manual_setpoint = stored_manual
                zone.setpoint = stored_manual
                _LOGGER.debug(
                    "Restored manual setpoint for zone %s: %.1f°C",
                    name,
                    stored_manual,
                )

            # Load zone-specific solar drop if configured
            zone.solar_drop = zone_config.get(CONF_ZONE_SOLAR_DROP)

            # Load away temperature if configured
            zone.away_temp = zone_config.get(CONF_ZONE_AWAY_TEMP, DEFAULT_AWAY_TEMP)

            # Create schedule reader if schedule entity is configured
            schedule_entity = zone_config.get(CONF_ZONE_SCHEDULE_ENTITY)
            if schedule_entity:
                zone.schedule_reader = ScheduleReader(
                    hass=self.hass,
                    entity_id=schedule_entity,
                    default_setpoint=zone.default_setpoint,
                )
                _LOGGER.debug(
                    "Created schedule reader for zone %s: %s",
                    name,
                    schedule_entity,
                )

            self.zones[name] = zone

    def _setup_window_tracking(self) -> None:
        """Set up event-driven tracking for window sensors.

        Window sensors are tracked with a 30-second debounce to prevent
        rapid state toggling from causing excessive updates.
        """
        for zone in self.zones.values():
            if zone.window_entity_id:
                self._state_debouncer.track_entity(
                    zone.window_entity_id,
                    delay_seconds=30.0,
                    on_confirmed=lambda state, z=zone: self._on_window_change(z, state),
                )

    async def _on_window_change(self, zone: ZoneState, state: str) -> None:
        """Handle debounced window state change.

        Args:
            zone: Zone whose window changed
            state: New window state ("on" = open, other = closed)
        """
        is_open = state == "on"
        if zone.window_open != is_open:
            zone.window_open = is_open
            _LOGGER.info(
                "Zone %s: window state changed to %s",
                zone.name,
                "open" if is_open else "closed",
            )
            # Trigger a partial update for this zone
            await self._update_single_zone(zone)

    async def _update_single_zone(self, zone: ZoneState) -> None:
        """Perform a partial update for a single zone.

        This is called when an event-driven state change occurs (e.g., window opens).
        It updates only the affected zone without running the full update cycle.

        Args:
            zone: Zone to update
        """
        # Skip if zone is disabled
        if zone.disabled:
            return

        # Skip if no temperature reading
        if zone.current_temp is None:
            return

        # Update demand for this zone using current time
        now = dt_util.now()
        dt = (
            (now - self._last_update).total_seconds()
            if self._last_update is not None
            else COORDINATOR_UPDATE_INTERVAL
        )

        # Apply window drop if needed
        effective_setpoint = zone.setpoint
        if zone.window_open:
            effective_setpoint -= DEFAULT_WINDOW_DROP

        # Update PID
        output = zone.pid.update(
            process_variable=zone.current_temp,
            setpoint=effective_setpoint,
            outdoor_temp=self._outdoor_temp,
            dt=dt,
        )
        zone.demand = max(0.0, min(100.0, output))

        _LOGGER.debug(
            "Zone %s: event-driven update, demand=%.1f%%, setpoint=%.1f°C",
            zone.name,
            zone.demand,
            zone.setpoint,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from sensors and update control outputs.

        This is called every 30 seconds by the coordinator framework.

        Returns:
            Dictionary containing current state for all entities

        Raises:
            UpdateFailed: If critical sensors cannot be read
        """
        try:
            # Track time for PID dt calculation
            now = dt_util.now()
            dt = (now - self._last_update).total_seconds() if self._last_update else 30.0
            self._last_update = now

            # Phase 3: Read all sensor states
            await self._read_sensor_states()

            # Phase 7: Apply smart synchronization
            self._apply_synchronization()

            # Phase 3.5: Update away mode state
            self._update_away_mode(now)

            # Phase 4: Update PID controllers and calculate demand
            self._update_zone_demands(dt)

            # Phase 4.5: Update quiet mode state
            await self._update_quiet_mode_state(now)

            # Phase 5: Calculate target flow temperature and control heater
            await self._update_heater_control()

            # Phase 7: Check and run valve maintenance
            await self._check_valve_maintenance()

            # Build state dictionary for entities
            return self._build_state_dict()

        except Exception as err:
            _LOGGER.error("Error updating EMS Zone Master: %s", err)
            raise UpdateFailed(f"Update failed: {err}") from err

    async def _read_sensor_states(self) -> None:
        """Read current values from all configured sensors.

        Updates internal state with:
        - Flow and return temperatures
        - Outdoor temperature
        - Solar power (if configured)
        - Zone temperatures
        - Window states
        """
        # Read heater sensors
        self._current_flow_temp = self._get_sensor_value(self._flow_temp_entity_id)
        self._current_return_temp = self._get_sensor_value(self._return_temp_entity_id)
        self._outdoor_temp = self._get_sensor_value(self._outdoor_temp_entity_id)

        if self._solar_power_entity_id:
            self._solar_power = self._get_sensor_value(self._solar_power_entity_id)

        # Read zone sensors
        for zone in self.zones.values():
            zone.current_temp = self._get_sensor_value(zone.temp_entity_id)

            # Read window state if configured
            if zone.window_entity_id:
                zone.window_open = self._get_binary_sensor_state(zone.window_entity_id)

        _LOGGER.debug(
            "Sensor states: flow=%.1f, return=%.1f, outdoor=%.1f, solar=%s",
            self._current_flow_temp or 0,
            self._current_return_temp or 0,
            self._outdoor_temp or 0,
            self._solar_power,
        )

    def _get_sensor_value(self, entity_id: str) -> float | None:
        """Get numeric value from a sensor entity.

        Args:
            entity_id: Entity ID to read

        Returns:
            Float value or None if unavailable/invalid
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Entity not found: %s", entity_id)
            return None

        if state.state in ("unknown", "unavailable"):
            _LOGGER.debug("Entity unavailable: %s", entity_id)
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid numeric state for %s: %s", entity_id, state.state)
            return None

    def _get_binary_sensor_state(self, entity_id: str) -> bool:
        """Get boolean state from a binary sensor entity.

        Args:
            entity_id: Entity ID to read

        Returns:
            True if "on", False otherwise
        """
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Binary sensor not found: %s", entity_id)
            return False

        return state.state == "on"

    def _apply_synchronization(self) -> None:
        """Apply smart synchronization to coordinate zone heating starts.

        When multiple zones have scheduled heating starts within the
        SYNC_LOOK_AHEAD window (45 min), this method forces earlier zones
        to start when the first one needs to start. This improves efficiency
        by having all zones heat together.

        The synchronization works as follows:
        1. Find all zones with upcoming scheduled starts
        2. Calculate when each zone needs to start (considering adaptive start)
        3. If multiple starts fall within the window, use the earliest
        4. Set sync_forced flag on zones that are started early
        """
        now = dt_util.now()
        sync_window = timedelta(minutes=SYNC_LOOK_AHEAD)

        # Collect zones with upcoming starts and their required start times
        zone_starts: list[tuple[ZoneState, datetime]] = []

        for zone in self.zones.values():
            zone.sync_forced = False  # Reset sync flag

            if zone.schedule_reader is None or zone.current_temp is None:
                continue

            # Skip if already in active period or manual mode
            if zone.schedule_reader.is_schedule_active(now) or zone.manual_setpoint is not None:
                continue

            # Get time to next scheduled active period
            time_to_active = zone.schedule_reader.get_time_to_next_active(now)
            if time_to_active is None:
                continue

            # Calculate when this zone needs to start heating (with adaptive start)
            target_temp = zone.schedule_reader.get_next_block_setpoint(now)
            if target_temp is None:
                continue

            temp_delta = target_temp - zone.current_temp

            if temp_delta <= 0:
                continue  # Already at target

            preheat_minutes = temp_delta * zone.warmup_factor
            preheat_time = timedelta(minutes=preheat_minutes)

            # Calculate absolute start time
            scheduled_active_time = now + time_to_active
            required_start_time = scheduled_active_time - preheat_time

            # Only consider zones that need to start within sync window
            time_until_start = required_start_time - now
            if timedelta(0) <= time_until_start <= sync_window:
                zone_starts.append((zone, required_start_time))

        # If multiple zones have upcoming starts, synchronize them
        if len(zone_starts) > 1:
            # Sort by required start time
            zone_starts.sort(key=lambda x: x[1])

            # Get the earliest required start time
            earliest_start = zone_starts[0][1]

            # Check if all starts are within sync window of each other
            latest_start = zone_starts[-1][1]
            if latest_start - earliest_start <= sync_window:
                # Force all zones to start at the earliest time
                for zone, start_time in zone_starts:
                    if start_time > earliest_start:
                        zone.sync_forced = True
                        _LOGGER.info(
                            "Zone %s: synchronized start (%.0f min early)",
                            zone.name,
                            (start_time - earliest_start).total_seconds() / 60,
                        )

    def _update_away_mode(self, now: datetime) -> None:
        """Update away mode state based on presence entity.

        Args:
            now: Current datetime

        Away mode activates when:
        1. Presence entity is configured
        2. Presence is "away" for the configured delay
        3. Presence returns immediately (instant exit from away mode)
        """
        if not self._presence_entity_id:
            self._away_mode_active = False
            return

        state = self.hass.states.get(self._presence_entity_id)
        if state is None:
            return

        # Check if "home" (on/home) or "away" (off/not_home/not_home)
        is_home = state.state in ("on", "home")

        if is_home:
            # Instant return - clear away mode immediately
            if self._away_mode_active:
                _LOGGER.info("Presence detected - exiting away mode")
            self._away_mode_active = False
            self._presence_lost_at = None
        else:
            # Away - check delay
            if self._presence_lost_at is None:
                self._presence_lost_at = now

            minutes_away = (now - self._presence_lost_at).total_seconds() / 60

            if minutes_away >= self._away_delay and not self._away_mode_active:
                _LOGGER.info("Away for %.0f min - entering away mode", minutes_away)
                self._away_mode_active = True

    async def _check_valve_maintenance(self) -> None:
        """Check and perform valve maintenance cycling.

        Valves that haven't been used for VALVE_MAINTENANCE_DAYS are
        cycled briefly to prevent seizing. This runs at a specific
        hour of the day to minimize disruption.
        """
        now = dt_util.now()

        for zone in self.zones.values():
            # Check if maintenance is needed using ValveManager
            if self._valve_manager.check_maintenance_needed(
                zone.last_valve_activity,
                zone.valve_maintenance_pending,
                now,
            ):
                # Schedule maintenance for this zone
                zone.valve_maintenance_pending = True
                _LOGGER.info(
                    "Zone %s: scheduling valve maintenance (inactive for %d days)",
                    zone.name,
                    (now - zone.last_valve_activity).days if zone.last_valve_activity else VALVE_MAINTENANCE_DAYS,
                )

                # Run maintenance in background task to avoid blocking update cycle
                self.hass.async_create_background_task(
                    self._perform_valve_maintenance(zone),
                    f"valve_maintenance_{zone.name}",
                )

    async def _perform_valve_maintenance(self, zone: ZoneState) -> None:
        """Perform a maintenance cycle on a zone valve.

        Opens the valve briefly then closes it to prevent seizing.

        Args:
            zone: Zone to maintain
        """
        _LOGGER.debug(
            "Zone %s: performing valve maintenance cycle (%d seconds)",
            zone.name,
            VALVE_MAINTENANCE_DURATION,
        )

        try:
            # Use ValveManager to perform maintenance
            zone.last_valve_activity = await self._valve_manager.perform_maintenance(
                zone.valve_entity_id,
                VALVE_MAINTENANCE_DURATION,
            )
            _LOGGER.info("Zone %s: valve maintenance complete", zone.name)

        except Exception as err:
            _LOGGER.error(
                "Zone %s: valve maintenance failed: %s",
                zone.name,
                err,
            )
        finally:
            # Reset pending flag when task completes (success or failure)
            zone.valve_maintenance_pending = False

    def _update_zone_demands(self, dt: float) -> None:
        """Update PID controllers and calculate demand for each zone.

        Args:
            dt: Time delta in seconds since last update

        For each zone:
        1. Determine effective setpoint (away > manual > schedule > default)
        2. Check adaptive start (preheat before schedule)
        3. Apply window drop if window is open
        4. Update PID with current temperature
        5. Track warmup for learning
        """
        now = dt_util.now()

        for zone in self.zones.values():
            # Skip disabled zones
            if zone.disabled:
                zone.demand = 0.0
                continue

            # Skip if no temperature reading
            if zone.current_temp is None:
                _LOGGER.debug("Skipping zone %s: no temperature reading", zone.name)
                zone.demand = 0.0
                continue

            # Check if manual setpoint should expire (schedule transitioned)
            if zone.manual_setpoint is not None and zone.schedule_reader is not None:
                current_schedule_state = zone.schedule_reader.is_schedule_active(now)
                if zone.manual_setpoint_schedule_state is not None:
                    if current_schedule_state != zone.manual_setpoint_schedule_state:
                        # Schedule transitioned - clear manual override
                        _LOGGER.info(
                            "Zone %s: clearing manual setpoint (schedule transitioned)",
                            zone.name,
                        )
                        zone.manual_setpoint = None
                        zone.manual_setpoint_schedule_state = None

            # Determine effective setpoint (priority: away > manual > schedule > default)
            if self._away_mode_active:
                zone.setpoint = zone.away_temp
                zone.adaptive_start_active = False
                _LOGGER.debug(
                    "Zone %s: away mode, using away temp %.1f°C",
                    zone.name,
                    zone.away_temp,
                )
            elif zone.manual_setpoint is not None:
                zone.setpoint = zone.manual_setpoint
                zone.adaptive_start_active = False
            elif zone.schedule_reader is not None:
                # Get scheduled setpoint
                scheduled_setpoint = zone.schedule_reader.get_current_setpoint(now)

                # Check for adaptive start or sync-forced preheat
                if not zone.schedule_reader.is_schedule_active(now):
                    # Currently in setback period, check if we need to preheat
                    time_to_active = zone.schedule_reader.get_time_to_next_active(now)
                    # Get the target temp from the next schedule block
                    target_temp = zone.schedule_reader.get_next_block_setpoint(now)

                    if time_to_active is not None and target_temp is not None:
                        temp_delta = target_temp - zone.current_temp

                        if zone.sync_forced:
                            # Forced by synchronization - start heating now
                            zone.adaptive_start_active = True
                            zone.setpoint = target_temp
                            _LOGGER.debug(
                                "Zone %s: sync-forced preheat to %.1f°C",
                                zone.name,
                                target_temp,
                            )
                        elif temp_delta > 0:
                            preheat_minutes = temp_delta * zone.warmup_factor
                            preheat_time = timedelta(minutes=preheat_minutes)

                            # Start preheating if within preheat window
                            if time_to_active <= preheat_time:
                                zone.adaptive_start_active = True
                                zone.setpoint = target_temp
                                _LOGGER.debug(
                                    "Zone %s: adaptive start activated, "
                                    "preheating %.1f°C in %.0f min",
                                    zone.name,
                                    temp_delta,
                                    time_to_active.total_seconds() / 60,
                                )
                            else:
                                zone.adaptive_start_active = False
                                zone.setpoint = scheduled_setpoint
                        else:
                            zone.adaptive_start_active = False
                            zone.setpoint = scheduled_setpoint
                    else:
                        zone.adaptive_start_active = False
                        zone.setpoint = scheduled_setpoint
                else:
                    zone.adaptive_start_active = False
                    zone.setpoint = scheduled_setpoint
            else:
                zone.setpoint = zone.default_setpoint
                zone.adaptive_start_active = False

            # Apply window drop if window is open
            effective_setpoint = zone.setpoint
            if zone.window_open:
                effective_setpoint -= DEFAULT_WINDOW_DROP
                _LOGGER.debug(
                    "Zone %s: window open, reducing setpoint by %.1f°C",
                    zone.name,
                    DEFAULT_WINDOW_DROP,
                )

            # Apply solar limiting if solar power exceeds threshold
            if (
                self._solar_power is not None
                and self._solar_power > self._solar_threshold
            ):
                # Use zone-specific solar drop if set, otherwise use global
                solar_drop = (
                    zone.solar_drop if zone.solar_drop is not None else self._solar_drop
                )
                effective_setpoint -= solar_drop
                _LOGGER.debug(
                    "Zone %s: solar limiting (%.0fW), reducing setpoint by %.1f°C",
                    zone.name,
                    self._solar_power,
                    solar_drop,
                )

            # Update PID controller
            zone.demand = zone.pid.update(
                setpoint=effective_setpoint,
                process_variable=zone.current_temp,
                outdoor_temp=self._outdoor_temp,
                dt=dt,
            )

            # Track warmup for learning
            self._track_warmup_learning(zone, effective_setpoint, now)

            _LOGGER.debug(
                "Zone %s: temp=%.1f, setpoint=%.1f, demand=%.1f%%, adaptive=%s",
                zone.name,
                zone.current_temp,
                effective_setpoint,
                zone.demand,
                zone.adaptive_start_active,
            )

    def _track_warmup_learning(
        self, zone: ZoneState, target_setpoint: float, now: datetime
    ) -> None:
        """Track warmup cycles to learn warmup factor.

        Monitors heating cycles to measure actual time-per-degree
        and updates the warmup factor using exponential smoothing.

        Args:
            zone: Zone state to track
            target_setpoint: Current target temperature
            now: Current time
        """
        if zone.current_temp is None:
            return

        temp_delta = target_setpoint - zone.current_temp
        at_target = temp_delta <= 0.2  # Within 0.2°C of target

        if zone.warmup_started_at is None:
            # Not currently tracking a warmup
            if temp_delta > 0.5 and zone.demand > 10:
                # Start tracking: heating needed and demand is significant
                zone.warmup_started_at = now
                zone.warmup_start_temp = zone.current_temp
                zone.warmup_target_temp = target_setpoint
                _LOGGER.debug(
                    "Zone %s: started warmup tracking at %.1f°C, target %.1f°C",
                    zone.name,
                    zone.current_temp,
                    target_setpoint,
                )
        else:
            # Currently tracking warmup
            if at_target and zone.warmup_start_temp is not None:
                # Reached target - calculate and update warmup factor
                elapsed = (now - zone.warmup_started_at).total_seconds() / 60
                temp_rise = zone.current_temp - zone.warmup_start_temp

                if temp_rise > 0.5:  # Meaningful temperature rise
                    measured_factor = elapsed / temp_rise

                    # Exponential smoothing (alpha = 0.3)
                    alpha = 0.3
                    old_factor = zone.warmup_factor
                    zone.warmup_factor = (
                        alpha * measured_factor + (1 - alpha) * zone.warmup_factor
                    )

                    _LOGGER.info(
                        "Zone %s: warmup complete in %.0f min for %.1f°C rise, "
                        "factor: %.1f -> %.1f min/°C",
                        zone.name,
                        elapsed,
                        temp_rise,
                        old_factor,
                        zone.warmup_factor,
                    )

                # Reset tracking
                zone.warmup_started_at = None
                zone.warmup_start_temp = None
                zone.warmup_target_temp = None

            elif zone.demand < 5:
                # Demand dropped significantly - cancel tracking
                _LOGGER.debug(
                    "Zone %s: cancelled warmup tracking (demand dropped)",
                    zone.name,
                )
                zone.warmup_started_at = None
                zone.warmup_start_temp = None
                zone.warmup_target_temp = None

    async def _update_heater_control(self) -> None:
        """Calculate and apply heater control output.

        1. Find maximum demand across all zones
        2. Check cooldown efficiency
        3. Calculate target flow temperature from demand curve
        4. Apply to heater entity (or set to 0 if below ignition level)

        Note: Solar limiting is handled at zone level in _update_zone_demands.
        """
        # Find maximum demand across all zones
        if self.zones:
            self._max_demand = max(zone.demand for zone in self.zones.values())
        else:
            self._max_demand = 0.0

        # Calculate target flow temperature using HeaterController
        now = dt_util.now()
        target_temp, cooldown_active = self._heater_controller.calculate_target_flow_temp(
            self._max_demand,
            self._current_flow_temp,
            self._current_return_temp,
            self._quiet_mode_active,
            self._first_block_start_time,
            now,
        )

        self._target_flow_temp = target_temp
        self._cooldown_active = cooldown_active

        # Apply to heater entity
        await self._heater_controller.set_flow_temperature(self._target_flow_temp)

        # Sync heater state from controller
        self._heater_was_active = self._heater_controller.heater_was_active

        # Control zone valves based on demand
        await self._update_valve_states()

    async def _update_valve_states(self) -> None:
        """Control zone valves based on their demand.

        Opens valves for zones with demand > 0, closes others.
        Handles both switch and climate entity types.
        """
        for zone in self.zones.values():
            should_open = zone.demand > 0 and not self._cooldown_active

            # Use ValveManager to control the valve
            zone.valve_opened_at, zone.valve_closed_at, zone.last_valve_activity = (
                await self._valve_manager.set_valve_state(
                    zone.valve_entity_id,
                    zone.valve_opened_at,
                    zone.valve_closed_at,
                    zone.setpoint,
                    should_open,
                    self._cooldown_active,
                )
            )

    def _build_state_dict(self) -> dict[str, Any]:
        """Build state dictionary for coordinator data.

        Returns:
            Dictionary with current state for all entities
        """
        return {
            "flow_temp": self._current_flow_temp,
            "return_temp": self._current_return_temp,
            "outdoor_temp": self._outdoor_temp,
            "target_flow_temp": self._target_flow_temp,
            "max_demand": self._max_demand,
            "cooldown_active": self._cooldown_active,
            "zones": {
                name: {
                    "setpoint": zone.setpoint,
                    "current_temp": zone.current_temp,
                    "demand": zone.demand,
                    "window_open": zone.window_open,
                }
                for name, zone in self.zones.items()
            },
        }

    @property
    def max_demand(self) -> float:
        """Return the current maximum demand across all zones."""
        return self._max_demand

    @property
    def target_flow_temp(self) -> float:
        """Return the current target flow temperature."""
        return self._target_flow_temp

    @property
    def cooldown_active(self) -> bool:
        """Return whether cooldown mode is active."""
        return self._cooldown_active

    @property
    def solar_limited(self) -> bool:
        """Return whether solar limiting is currently active."""
        return (
            self._solar_power is not None
            and self._solar_power > self._solar_threshold
            and self._max_demand > 0
        )

    @property
    def quiet_mode_active(self) -> bool:
        """Return whether quiet mode is currently active."""
        return self._quiet_mode_active

    @property
    def away_mode_active(self) -> bool:
        """Return whether away mode is currently active."""
        return self._away_mode_active

    async def _update_quiet_mode_state(self, now: datetime) -> None:
        """Update quiet mode state based on current schedule blocks.

        Quiet mode activates during the first schedule block of the day
        and ramps up flow temperature over the configured time period.
        """
        # Skip if quiet mode is disabled
        if self._quiet_mode_max_flow <= 0:
            self._quiet_mode_active = False
            self._first_block_start_time = None
            return

        # Reset quiet mode at midnight (new day)
        if (
            self._last_quiet_mode_check_date is not None
            and now.date() > self._last_quiet_mode_check_date.date()
        ):
            self._quiet_mode_active = False
            self._first_block_start_time = None

        self._last_quiet_mode_check_date = now

        # Check each zone's schedule for first block status
        any_zone_in_first_block = False
        for zone in self.zones.values():
            if zone.schedule_reader is not None:
                is_first_block = await zone.schedule_reader.is_first_block_of_day_async(now)
                if is_first_block:
                    any_zone_in_first_block = True
                    # Get the start time if we don't have it
                    if self._first_block_start_time is None:
                        self._first_block_start_time = (
                            await zone.schedule_reader.get_first_block_start_time_async(now)
                        )
                    break

        if any_zone_in_first_block:
            # Check if ramp period has completed
            if self._first_block_start_time is not None:
                minutes_since_start = (now - self._first_block_start_time).total_seconds() / 60
                if minutes_since_start < self._quiet_mode_ramp_minutes:
                    self._quiet_mode_active = True
                else:
                    # Ramp completed
                    self._quiet_mode_active = False
            else:
                self._quiet_mode_active = True
        else:
            # Not in first block (second block started or no schedule active)
            self._quiet_mode_active = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the main EMS Zone Master device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="EMS Zone Master",
            manufacturer="EMS-ESP",
            model="Zone Master Controller",
            sw_version=VERSION,
        )

    def get_zone_device_info(self, zone_name: str) -> DeviceInfo:
        """Return device info for a specific zone.

        Args:
            zone_name: Name of the zone

        Returns:
            DeviceInfo for the zone, linked to main device
        """
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{zone_name}")},
            name=f"Zone: {zone_name}",
            manufacturer="EMS-ESP",
            model="Heating Zone",
            via_device=(DOMAIN, self.entry.entry_id),
        )
