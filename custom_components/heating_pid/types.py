"""Type definitions for Heating PID integration.

This module provides TypedDict classes for configuration and data structures
used throughout the integration, enabling better type safety and mypy compliance.
"""

from dataclasses import dataclass


class ZoneConfigDict(dict):
    """Configuration dict for a heating zone.

    Created from config flow options or initial setup.
    """

    zone_name: str
    zone_temp_entity: str
    zone_valve_entity: str
    zone_window_entity: str | None
    zone_schedule_entity: str | None
    zone_default_setpoint: float
    zone_away_temp: float
    zone_solar_drop: float | None
    kp: float
    ki: float
    kd: float
    ke: float


class HeaterConfigDict(dict):
    """Configuration dict for heater entities."""

    heater_entity: str
    flow_temp_entity: str
    return_temp_entity: str
    outdoor_temp_entity: str
    solar_power_entity: str | None


class GlobalConfigDict(dict):
    """Configuration dict for global settings."""

    min_egress: float
    max_egress: float
    min_ignition_level: float
    solar_threshold: float
    solar_drop: float
    outdoor_reference_temp: float
    valve_min_on_time: int
    valve_min_off_time: int
    quiet_mode_max_flow: float
    quiet_mode_ramp_minutes: int
    presence_entity: str | None
    away_delay: int


class ConfigEntryData(dict):
    """Data stored in config_entry.data."""

    heater_entity: str
    flow_temp_entity: str
    return_temp_entity: str
    outdoor_temp_entity: str
    solar_power_entity: str | None
    min_egress: float
    max_egress: float
    min_ignition_level: float
    solar_threshold: float
    solar_drop: float
    outdoor_reference_temp: float
    valve_min_on_time: int
    valve_min_off_time: int
    quiet_mode_max_flow: float
    quiet_mode_ramp_minutes: int
    presence_entity: str | None
    away_delay: int
    zones: list[ZoneConfigDict]


class CoordinatorStateDict(dict):
    """State exposed by coordinator to entities."""

    flow_temp: float | None
    return_temp: float | None
    outdoor_temp: float | None
    solar_power: float | None
    target_flow_temp: float
    max_demand: float
    cooldown_active: bool
    away_mode_active: bool
    quiet_mode_active: bool
    quiet_mode_ratio: float


@dataclass
class ZoneData:
    """Runtime data for a heating zone."""

    name: str
    current_temp: float | None
    setpoint: float
    demand: float
    window_open: bool
    valve_open: bool
    manual_setpoint: float | None
    away_temp: float
    solar_drop: float | None
    pid_output: float
    outdoor_compensation: float
    time_to_target: float | None
    warmup_factor: float
    adaptive_start_active: bool
    sync_forced: bool
    last_valve_change: float | None  # timestamp
