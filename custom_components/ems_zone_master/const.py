"""Constants for the EMS Zone Master integration."""

from typing import Final

# Domain
DOMAIN: Final = "ems_zone_master"

# Platforms
PLATFORMS: Final = ["climate", "sensor", "number", "binary_sensor"]

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

# Configuration keys - Zones
CONF_ZONES: Final = "zones"
CONF_ZONE_NAME: Final = "zone_name"
CONF_ZONE_TEMP_ENTITY: Final = "zone_temp_entity"
CONF_ZONE_VALVE_ENTITY: Final = "zone_valve_entity"
CONF_ZONE_WINDOW_ENTITY: Final = "zone_window_entity"
CONF_ZONE_SCHEDULE_ENTITY: Final = "zone_schedule_entity"
CONF_ZONE_DEFAULT_SETPOINT: Final = "zone_default_setpoint"

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

# Default values - Zone
DEFAULT_WINDOW_DROP: Final = 5.0  # Setpoint reduction when window open (°C)
DEFAULT_SETPOINT: Final = 20.0  # Default target temperature (°C)

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
STORAGE_KEY: Final = "ems_zone_master"
STORAGE_VERSION: Final = 1

# Services
SERVICE_SET_ZONE_SETPOINT: Final = "set_zone_setpoint"
SERVICE_RESET_WARMUP_FACTOR: Final = "reset_warmup_factor"

# Attributes
ATTR_DEMAND: Final = "demand"
ATTR_WARMUP_FACTOR: Final = "warmup_factor"
ATTR_TIME_TO_TARGET: Final = "time_to_target"
ATTR_PID_OUTPUT: Final = "pid_output"
ATTR_OUTDOOR_COMPENSATION: Final = "outdoor_compensation"
