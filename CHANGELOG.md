# Changelog

All notable changes to the EMS Zone Master integration will be documented in this file.

## [Unreleased]

### Added
- **Away mode**: Automatic temperature reduction when nobody is home based on presence entity
- **Zone away temperature**: Per-zone configuration for away mode target temperature
- **Presence entity**: Global setting for tracking home/away state
- **Away delay**: Configurable delay before activating away mode (default 30 minutes)

### Changed
- Improved type safety with proper type annotations throughout codebase
- Added `types.py` for central type definitions
- Mypy configuration in `pyproject.toml` for strict type checking
- Made `dt` parameter explicit in PID controller for better time control
- Improved error handling in service calls with `_safe_service_call` helper
- Heater entities can now be configured via options flow

### Fixed
- Anti-windup logic now correctly includes D-term in potential output calculation
- Integral windup issue that caused demand to stick at 100%
- Integral values are now validated when restored from storage (max 300)

## [0.5.0] - 2025-01-15

### Added
- Quiet mode: Limits flow temperature during first heating block of the day
- Quiet mode ramp-up: Gradual temperature increase over configurable time
- Heater entities options step in configuration flow

### Fixed
- Manual setpoint now correctly persists across schedule transitions
- Schedule parser now handles `datetime.time` objects properly

## [0.4.0] - 2025-01-10

### Added
- Smart synchronization: Coordinates zone starts to improve efficiency
- Adaptive start preheating based on learned warmup factors
- Schedule state tracking for manual setpoint expiration

## [0.3.0] - 2025-01-05

### Added
- Live PID tuning via number entities (Kp, Ki, Kd, Ke per zone)
- Master status sensor with detailed system information
- Target flow temperature sensor
- Total demand sensor

## [0.2.0] - 2024-12-20

### Added
- Multi-zone temperature management
- PID-based demand calculation
- Schedule integration with Home Assistant schedule helpers
- Window detection and setpoint reduction
- Solar power limiting
- Efficiency cooldown mode
- Valve maintenance cycling
- Time-to-target estimation with warmup learning

## [0.1.0] - 2024-12-01

### Added
- Initial release
- Basic heater control via EMS-ESP
- Single zone support
- Flow temperature modulation
