# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

EMS Zone Master is a Home Assistant custom integration for modulating heating control via EMS-ESP. It provides multi-zone temperature management with PID-based demand calculation, adaptive start learning, and efficiency optimizations.

## Architecture

**Control Method:** Modulates boiler flow temperature based on aggregated zone demand rather than simple on/off control.

**Core Components:**

- `coordinator.py` - Central `DataUpdateCoordinator` (30s update interval) managing heater and zone states
- `pid.py` - PID controller with anti-windup, derivative on process variable, multiplicative outdoor compensation
- `store.py` - JSON persistence in `.storage/heating_pid.json` for learned warmup factors and PID integrals
- `schedule.py` - Reader for Home Assistant schedule helper entities
- `climate.py` - Zone climate entities
- `sensor.py` - Time-to-target and master status sensors
- `number.py` - Live PID tuning entities (Kp, Ki, Kd, Ke per zone)

**Priority Hierarchy (highest to lowest):**

1. Window open → setpoint reduced by configured delta
2. Manual setpoint → persists until next schedule event
3. Schedule setpoint → baseline operation
4. Synchronization forcing → treated as schedule-level

**Demand Curve:**

```
target_egress = min_egress + (max_demand / 100) × (max_egress - min_egress)
```

## Directory Structure

```
custom_components/heating_pid/
├── __init__.py          # async_setup_entry, coordinator init
├── manifest.json        # Integration metadata, HA 2024.1+
├── const.py             # Domain, config keys, defaults
├── config_flow.py       # 3-step config: heater → global → zones
├── coordinator.py       # DataUpdateCoordinator
├── store.py             # Persistence layer
├── pid.py               # PID controller class
├── schedule.py          # Schedule helper reader
├── climate.py           # EmsZoneClimate entities
├── sensor.py            # Time-to-target, master status
├── number.py            # PID tuning number entities
├── binary_sensor.py     # Cooldown indicator
├── strings.json
└── translations/en.json
```

## Development Commands

```bash
# Restart Home Assistant to reload integration changes
ha core restart

# Check logs for integration errors
ha core logs | grep heating_pid

# Validate configuration
ha core check

# Access Home Assistant container (if using Docker)
docker exec -it homeassistant bash
```

**Testing:** Verify each phase works in Home Assistant via Settings → Devices & Services before proceeding to next phase.

## Key Constants (const.py)

| Constant                | Default   | Purpose                                   |
| ----------------------- | --------- | ----------------------------------------- |
| `SYNC_LOOK_AHEAD`       | 45 min    | Time window for synchronization           |
| `MIN_IGNITION_LEVEL`    | 20%       | Demand threshold to activate burner       |
| `SOLAR_THRESHOLD`       | 2000W     | Solar power limit activation              |
| `SOLAR_DROP`            | 5°C       | Temperature reduction when solar limiting |
| `WINDOW_DROP`           | 5°C       | Setpoint reduction when window open       |
| `MIN_EFFICIENT_DELTA_T` | 5°C       | Delta-T threshold for cooldown mode       |
| `PERSISTENCE_INTERVAL`  | 60 min    | State save frequency                      |
| `INITIAL_WARMUP_GUESS`  | 30 min/°C | Starting warmup factor                    |

## PID Defaults

| Gain | Value |
| ---- | ----- |
| Kp   | 30    |
| Ki   | 0.5   |
| Kd   | 10    |
| Ke   | 0.02  |

## Implementation Phases

The project follows a 7-phase implementation plan documented in `chat.md`:

1. Integration scaffold and heater configuration
2. Global settings and zone configuration flow
3. Data coordinator and persistence store
4. Climate entity and basic PID control
5. Heater strategy and valve control
6. Schedule integration, adaptive start, and window logic
7. Smart synchronization and valve maintenance

Each phase produces a testable increment. Verify functionality before advancing.
