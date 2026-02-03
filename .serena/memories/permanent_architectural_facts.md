# Permanent Architectural Facts

## Core Technology
- **Language:** Python
- **Framework:** Home Assistant Custom Integration
- **Encoding:** UTF-8
- **Home Assistant:** Version 2024.1+

## Architecture Patterns
- **Control Pattern:** Modulating boiler flow temperature based on aggregated zone demand
- **Coordination:** DataUpdateCoordinator with 30s update interval
- **Persistence:** JSON storage in `.storage/heating_pid.json`
- **PID Control:** Anti-windup, derivative on process variable, multiplicative outdoor compensation

## Key Constants
- `MIN_EFFICIENT_DELTA_T = 5.0°C` - Delta-T threshold for cooldown mode
- `SYNC_LOOK_AHEAD = 45 min` - Time window for synchronization
- `MIN_IGNITION_LEVEL = 20%` - Demand threshold to activate burner
- `PERSISTENCE_INTERVAL = 60 min` - State save frequency
- `COORDINATOR_UPDATE_INTERVAL = 30s` - Data update interval

## Core Components
- `coordinator.py` - Central DataUpdateCoordinator
- `pid.py` - PID controller class
- `store.py` - Persistence layer
- `heater_controller.py` - Heater strategy and cooldown logic
- `config_flow.py` - Configuration flow UI

## Logging
- Uses standard Python logging via `_LOGGER` throughout all modules
