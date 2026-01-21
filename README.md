# EMS Zone Master

A Home Assistant custom integration for modulating heating control via EMS-ESP. Provides multi-zone temperature management with PID-based demand calculation, adaptive start learning, and efficiency optimizations.

## Features

- **Multi-zone PID control**: Each zone has its own PID controller for precise temperature management
- **Modulating flow temperature**: Controls boiler output by setting flow temperature based on aggregate demand
- **Adaptive start**: Learns how long each zone takes to heat up and starts preheating automatically
- **Schedule integration**: Works with Home Assistant schedule helpers for time-based setpoints
- **Window detection**: Reduces setpoint when windows are open
- **Solar power limiting**: Reduces heating when solar generation is high
- **Efficiency cooldown**: Pauses heating when delta-T drops below threshold
- **Smart synchronization**: Coordinates zone starts to improve efficiency
- **Valve maintenance**: Periodically cycles inactive valves to prevent seizing
- **Live PID tuning**: Adjust Kp, Ki, Kd, Ke gains via number entities
- **Away mode**: Automatically reduces heating when nobody is home
- **Quiet mode**: Limits flow temperature during early morning heating blocks

## Requirements

- Home Assistant 2024.1.0 or newer
- EMS-ESP connected boiler with climate entity for flow temperature control

## Installation

### Manual Installation

1. Copy the `custom_components/heating_pid` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Settings > Devices & Services > Add Integration
4. Search for "EMS Zone Master"

## Configuration

The integration uses a 3-step configuration flow:

1. **Heater Setup**: Select your EMS-ESP climate entity and temperature sensors
2. **Global Settings**: Configure temperature limits, efficiency options, and away mode
3. **Zone Setup**: Add heating zones with temperature sensors, valves, and schedules

### Global Settings Options

| Setting | Description | Default |
|---------|-------------|---------|
| Min/Max Flow Temperature | Operating range for boiler flow | 25°C / 55°C |
| Minimum Ignition Level | Demand threshold to start burner | 20% |
| Solar Threshold | Reduce heating when solar exceeds this | 2000W |
| Solar Drop | Temperature reduction when solar limiting | 5°C |
| Outdoor Reference Temp | Reference for outdoor compensation | 15°C |
| Valve Min On/Off Time | Minimum valve switching times | 5 min |
| Quiet Mode Max Flow | Max flow temp during first heating block | 0 (disabled) |
| Quiet Mode Ramp-up | Gradual increase time | 60 min |
| Presence Entity | Tracker for home/away detection | - |
| Away Delay | Minutes before activating away mode | 30 |

### Zone Options

| Setting | Description |
|---------|-------------|
| Room Name | Display name for the zone |
| Room Temperature | Temperature sensor entity |
| Zone Valve | Valve or thermostat entity |
| Draft/Window Sensor | Optional window/door sensor |
| Heating Schedule | Optional schedule helper entity |
| Default Temperature | Target when no schedule is active |
| Away Temperature | Target when away mode is active |
| PID Gains (Kp, Ki, Kd, Ke) | Tuning parameters |
| Solar Drop | Zone-specific solar override |

## Entities

### Per Zone

- **Climate**: Temperature control with current/target temperature
- **Sensor**: Time to target estimate
- **Binary Sensor**: Heating active indicator, window state
- **Number**: PID gain tuning (Kp, Ki, Kd, Ke)

### Global

- **Sensor**: Master status, target flow temperature, total demand
- **Binary Sensor**: Cooldown active indicator

## License

MIT
