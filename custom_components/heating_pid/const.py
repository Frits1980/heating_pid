"""Constants for the Heating PID integration."""

from typing import Final

from homeassistant.const import Platform

# Version - keep in sync with manifest.json
VERSION: Final = "0.5.0"

# Domain
DOMAIN: Final = "heating_pid"

# Platforms
PLATFORMS: Final = [Platform.CLIMATE, Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR]

# Configuration keys - Heater
CONF_HEATER_ENTITY: Final = "heater_entity"
CONF_FLOW_TEMP_ENTITY: Final = "flow_temp_entity"
CONF_RETURN_TEMP_ENTITY: Final = "return_temp_entity"
CONF_OUTDOOR_TEMP_ENTITY: Final = "outdoor_temp_entity"
CONF_SOLAR_POWER_ENTITY: Final = "solar_power_entity"

# Configuration keys - Global
CONF_MIN_EGRESS: Final = "min_egress"
CONF_MAX_EGRESS: Final = "max_egress"
CONF_MIN_IGNITION_LEVEL: Final = "min_ignition_level"
CONF_SOLAR_THRESHOLD: Final = "solar_threshold"
CONF_SOLAR_DROP: Final = "solar_drop"
CONF_OUTDOOR_REFERENCE_TEMP: Final = "outdoor_reference_temp"
CONF_VALVE_MIN_ON_TIME: Final = "valve_min_on_time"
CONF_VALVE_MIN_OFF_TIME: Final = "valve_min_off_time"
CONF_QUIET_MODE_MAX_FLOW: Final = "quiet_mode_max_flow"
CONF_QUIET_MODE_RAMP_MINUTES: Final = "quiet_mode_ramp_minutes"
CONF_PRESENCE_ENTITY: Final = "presence_entity"
CONF_AWAY_DELAY: Final = "away_delay"

# Configuration keys - Zones
CONF_ZONES: Final = "zones"
CONF_ZONE_NAME: Final = "zone_name"
CONF_ZONE_TEMP_ENTITY: Final = "zone_temp_entity"
CONF_ZONE_VALVE_ENTITY: Final = "zone_valve_entity"
CONF_ZONE_WINDOW_ENTITY: Final = "zone_window_entity"
CONF_ZONE_SCHEDULE_ENTITY: Final = "zone_schedule_entity"
CONF_ZONE_DEFAULT_SETPOINT: Final = "zone_default_setpoint"
CONF_ZONE_SOLAR_DROP: Final = "zone_solar_drop"
CONF_ZONE_AWAY_TEMP: Final = "zone_away_temp"

# Configuration keys - PID
CONF_KP: Final = "kp"
CONF_KI: Final = "ki"
CONF_KD: Final = "kd"
CONF_KE: Final = "ke"

# Default values - Global
DEFAULT_MIN_EGRESS: Final = 25  # Minimum flow temperature (°C)
DEFAULT_MAX_EGRESS: Final = 55  # Maximum flow temperature (°C)
DEFAULT_MIN_IGNITION_LEVEL: Final = 20  # Demand threshold (%)
DEFAULT_SOLAR_THRESHOLD: Final = 2000  # Solar power limit (W)
DEFAULT_SOLAR_DROP: Final = 5.0  # Temperature reduction for solar (°C)
DEFAULT_OUTDOOR_REFERENCE_TEMP: Final = 15.0  # Reference temp for outdoor compensation (°C)
DEFAULT_VALVE_MIN_ON_TIME: Final = 5  # Minimum valve on time (minutes)
DEFAULT_VALVE_MIN_OFF_TIME: Final = 5  # Minimum valve off time (minutes)
DEFAULT_QUIET_MODE_MAX_FLOW: Final = 0.0  # Disabled by default (°C, 0 = disabled)
DEFAULT_QUIET_MODE_RAMP_MINUTES: Final = 60  # Ramp-up time (minutes)
DEFAULT_AWAY_DELAY: Final = 30  # Minutes before activating away mode

# Default values - Zone
DEFAULT_WINDOW_DROP: Final = 5.0  # Setpoint reduction when window open (°C)
DEFAULT_SETPOINT: Final = 20.0  # Default target temperature (°C)
DEFAULT_AWAY_TEMP: Final = 15.0  # Default temperature when away (°C)

# Default values - PID gains
DEFAULT_KP: Final = 30.0  # Proportional gain
DEFAULT_KI: Final = 0.5  # Integral gain
DEFAULT_KD: Final = 10.0  # Derivative gain
DEFAULT_KE: Final = 0.02  # Outdoor compensation gain

# Timing constants
SYNC_LOOK_AHEAD: Final = 45  # Time window for synchronization (minutes)
MIN_EFFICIENT_DELTA_T: Final = 5.0  # Delta-T threshold for cooldown mode (°C)
PERSISTENCE_INTERVAL: Final = 60  # State save frequency (minutes)
INITIAL_WARMUP_GUESS: Final = 30.0  # Starting warmup factor (min/°C)
COORDINATOR_UPDATE_INTERVAL: Final = 30  # Data update interval (seconds)

# Valve maintenance
VALVE_MAINTENANCE_DAYS: Final = 7  # Days of inactivity before maintenance cycle
VALVE_MAINTENANCE_DURATION: Final = 30  # Seconds to cycle valve during maintenance
VALVE_MAINTENANCE_HOUR: Final = 14  # Hour of day to run maintenance (2 PM)

# Storage
STORAGE_KEY: Final = "heating_pid"
STORAGE_VERSION: Final = 1

# Attributes
ATTR_DEMAND: Final = "demand"
ATTR_WARMUP_FACTOR: Final = "warmup_factor"
ATTR_TIME_TO_TARGET: Final = "time_to_target"
ATTR_PID_OUTPUT: Final = "pid_output"
ATTR_OUTDOOR_COMPENSATION: Final = "outdoor_compensation"
