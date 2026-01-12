# Heating PID Configuration Guide

This guide explains all configuration options for the Heating PID integration.

## Step 1: Heater Configuration

Connect the integration to your EMS-ESP boiler.

### Boiler Flow Setpoint
**Required** | Entity type: `number`

The entity that controls your boiler's target water temperature. This is typically a number entity from EMS-ESP that sets the flow temperature setpoint.

Example: `number.boiler_flow_setpoint`

### Flow Temperature
**Required** | Entity type: `sensor`

Measures the water temperature leaving the boiler (supply/flow). Used to monitor system performance and calculate efficiency.

Example: `sensor.boiler_flow_temperature`

### Return Temperature
**Required** | Entity type: `sensor`

Measures the water temperature returning to the boiler. The difference between flow and return (delta-T) indicates how much heat was transferred to the rooms.

Example: `sensor.boiler_return_temperature`

### Outdoor Temperature
**Required** | Entity type: `sensor`

The outside temperature sensor. Used for weather compensation - the system automatically boosts heating when it's colder outside.

Example: `sensor.outdoor_temperature` or a weather integration sensor

### Solar Power (optional)
**Optional** | Entity type: `sensor`

If you have solar panels, this sensor monitors their power output. When solar production exceeds the threshold, heating is automatically reduced to prioritize solar usage.

Example: `sensor.solar_power_production`

---

## Step 2: Temperature Limits

Configure the operating range for your heating system.

### Lowest Water Temperature
**Default: 25°C** | Range: 20-40°C

The minimum flow temperature when heating demand is low. For underfloor heating, this is typically 25-30°C. Too low and the floor won't feel warm; too high wastes energy.

**Recommended:**
- Underfloor heating: 25-30°C
- Radiators: 30-40°C

### Highest Water Temperature
**Default: 55°C** | Range: 35-80°C

The maximum flow temperature at full heating demand (cold day, room far below setpoint). For underfloor heating, stay below 45°C to protect flooring.

**Recommended:**
- Underfloor heating (tile): 40-45°C
- Underfloor heating (wood/laminate): 35-40°C
- Radiators: 55-70°C

### Minimum Demand to Start
**Default: 20%** | Range: 0-50%

The heating system won't turn on until the combined demand from all zones exceeds this percentage. This prevents short cycling and improves efficiency.

**Recommended:**
- Gas boilers: 15-25%
- Heat pumps: 10-20%

### Solar Power Limit
**Default: 2000W** | Range: 0-10000W

When your solar panels produce more than this amount, the heating system reduces its demand. Set to 0 to disable solar limiting.

### Solar Temperature Reduction
**Default: 5°C** | Range: 0-10°C

How much to reduce the flow temperature when solar production exceeds the limit. A higher value means more aggressive solar prioritization.

---

## Step 3: Zone Configuration

Add each room or heating area as a zone.

### Room Name
**Required**

A descriptive name for this heating zone. Used to identify the zone in Home Assistant.

Examples: `Living Room`, `Master Bedroom`, `Kitchen`

### Room Temperature
**Required** | Entity type: `sensor`

The temperature sensor measuring this room's current temperature. Can be any temperature sensor.

Examples:
- `sensor.living_room_temperature`
- `sensor.bedroom_aqara_temperature`
- TRV built-in sensor

### Zone Valve
**Required** | Entity type: `switch` or `climate`

The entity that controls heating flow to this zone. Can be:
- A **switch** controlling a zone valve (on/off)
- A **climate** entity like a TRV (thermostatic radiator valve)

Examples:
- `switch.living_room_valve`
- `climate.bedroom_trv`

### Draft/Window Sensor (optional)
**Optional** | Entity type: `binary_sensor` or `input_boolean`

When this sensor is "on" or "open", heating to this zone is reduced. Use for:
- Window/door contact sensors
- Manual "draft mode" toggle (input_boolean helper)
- Occupancy sensors

The setpoint is reduced by 5°C when active.

### Heating Schedule (optional)
**Optional** | Entity type: `schedule`

A Home Assistant schedule helper that defines when heating should be active and at what temperature. When no schedule is configured, the default setpoint is used.

Create schedules in Settings → Helpers → Create Helper → Schedule.

### Default Temperature
**Default: 20°C** | Range: 5-30°C

The target temperature when no schedule is active, or as the baseline setpoint.

---

## PID Tuning Parameters

The PID controller determines how aggressively the system responds to temperature differences. These parameters are per-zone, allowing different rooms to have different response characteristics.

### Understanding PID for Heating

- **Slow systems (underfloor)**: Need higher Kd to prevent overshooting
- **Fast systems (radiators)**: Can use higher Kp for quicker response
- **Large rooms**: May need higher Ki for steady-state accuracy

### Speed (Kp) - Proportional Gain
**Default: 30** | Range: 0-100 | Typical: 20-50

Controls how strongly the system responds to the temperature error (difference between current and target temperature).

- **Higher Kp**: Faster response, but may overshoot
- **Lower Kp**: Slower, more conservative response

**Starting points:**
- Underfloor heating: 30-40
- Radiators: 40-60
- Well-insulated rooms: 20-30
- Poorly-insulated rooms: 40-50

### Precision (Ki) - Integral Gain
**Default: 0.5** | Range: 0-5 | Typical: 0.01-0.5

Accumulates error over time to eliminate steady-state offset (when room stays slightly below target).

- **Higher Ki**: Eliminates offset faster, but can cause oscillation
- **Lower Ki**: More stable, but may never quite reach target

**Starting points:**
- Underfloor heating: 0.01-0.1
- Radiators: 0.1-0.5
- If room consistently undershoots: Increase Ki
- If temperature oscillates: Decrease Ki

### Stability (Kd) - Derivative Gain
**Default: 10** | Range: 0-200 | Typical: 50-150 for underfloor

Dampens rapid temperature changes to prevent overshooting. Essential for slow systems like underfloor heating.

- **Higher Kd**: More damping, less overshoot
- **Lower Kd**: Faster but may overshoot

**Starting points:**
- Underfloor heating: 80-150
- Radiators: 10-30
- Systems that overshoot: Increase Kd
- Systems that respond too slowly: Decrease Kd

### Weather Adjustment (Ke) - Outdoor Compensation
**Default: 0.02** | Range: 0-0.1 | Typical: 0.01-0.03

Boosts heating output when it's cold outside. The colder it gets, the more the system increases demand.

- **Higher Ke**: More aggressive cold weather compensation
- **Lower Ke**: Less weather influence

**Starting points:**
- Well-insulated house: 0.01-0.02
- Older/drafty house: 0.02-0.04
- If house cools down on cold days: Increase Ke

---

## Tuning Tips

### For Underfloor Heating (dry construction)

Underfloor heating has high thermal mass, meaning it responds slowly. Typical values:

```
Kp: 40      (moderate response)
Ki: 0.01    (very low to prevent oscillation)
Kd: 100     (high damping to prevent overshoot)
Ke: 0.02    (moderate weather compensation)
```

### For Radiators

Radiators respond faster, so you can be more aggressive:

```
Kp: 50      (faster response)
Ki: 0.3     (can tolerate more integral action)
Kd: 20      (less damping needed)
Ke: 0.02    (moderate weather compensation)
```

### Tuning Process

1. **Start conservative**: Use lower values and increase gradually
2. **Adjust Kp first**: Get reasonable response speed
3. **Add Ki if needed**: Only if room consistently undershoots
4. **Increase Kd**: If you see overshooting or oscillation
5. **Tune Ke seasonally**: Adjust based on how house performs in cold weather

---

## Troubleshooting

### Room never reaches target temperature
- Increase Kp (faster response)
- Increase Ki (accumulate more correction)
- Check if valve actually opens
- Verify temperature sensor is accurate

### Room overshoots target
- Increase Kd (more damping)
- Decrease Kp (less aggressive response)
- For underfloor: Check if flow temperature is too high

### Temperature oscillates up and down
- Decrease Ki (less integral action)
- Increase Kd (more damping)
- Check for sensor lag or placement issues

### Heating turns on/off frequently (short cycling)
- Increase "Minimum Demand to Start" percentage
- This is normal when demand is near the threshold

### System doesn't heat on cold days
- Increase Ke (more weather compensation)
- Check outdoor temperature sensor accuracy
- Verify maximum flow temperature is high enough
