Excellent. All architectural decisions are now confirmed. Let me compile the complete coding plan.

---

## Final Architecture Summary

Before presenting the coding plan, here is the consolidated technical specification based on all our discussions.

**Core Integration: EMS Zone Master**

| Aspect             | Decision                                                                                 |
| ------------------ | ---------------------------------------------------------------------------------------- |
| Control Method     | Modulating flow temperature via EMS-ESP                                                  |
| Zone Input         | One temperature sensor, one window binary sensor per zone                                |
| Valve Control      | Switch entities with configurable opening delay                                          |
| Schedule Backend   | Native Home Assistant schedule helpers                                                   |
| PID Configuration  | Anti-windup enabled, derivative on process variable, multiplicative outdoor compensation |
| Learning Algorithm | Exponential weighted moving average with bounds (±10% per learning event)                |
| Persistence        | Configurable interval with shutdown save                                                 |
| Minimum Runtime    | Implemented in integration (user configures value)                                       |
| Delta-T Cooldown   | Dynamic exit (recovers when Delta-T exceeds threshold)                                   |

**Priority Hierarchy (highest to lowest):**

1. Window open → setpoint reduced by configured delta
2. Manual setpoint → persists until next schedule event
3. Schedule setpoint → baseline operation
4. Synchronization forcing → treated as schedule-level

**Entities Created Per Zone:**

- `climate.{zone_name}` — main thermostat interface
- `sensor.{zone_name}_time_to_target` — estimated minutes remaining
- `number.{zone_name}_kp` / `ki` / `kd` / `ke` — live PID tuning

**Global Entities Created:**

- `sensor.ems_master_status` — current strategy and state
- `number.ems_heater_min_egress` / `max_egress` — temperature curve bounds
- `binary_sensor.ems_heater_cooldown_active` — Delta-T cooldown indicator

---

## Coding Plan: Phased Approach

The plan is divided into seven phases. Each phase produces a testable, functional increment. You should verify each phase works correctly in your Home Assistant environment before proceeding to the next.

---

### Phase 1: Integration Scaffold and Heater Configuration

**Objective:** Establish the basic integration structure and configure the heater connection.

**Step 1.1 — Create folder structure**

Create the following directory structure under `custom_components/`:

```
heating_pid/
├── __init__.py
├── manifest.json
├── const.py
├── config_flow.py
├── strings.json
└── translations/
    └── en.json
```

**Step 1.2 — Implement manifest.json**

Define the integration metadata including dependencies on the `schedule` integration (for later phases) and minimum Home Assistant version of 2024.1.

**Step 1.3 — Implement const.py**

Define all constants including domain name, configuration keys, and default values for all parameters we discussed (sync look-ahead 45 min, min ignition level 20%, solar threshold 2000W, solar drop 5°C, window drop 5°C, min efficient delta-T 5°C, persistence interval 60 min, initial warmup guess 30 min/°C).

**Step 1.4 — Implement config_flow.py Step 1 (Heater)**

Create the first configuration step requesting the following entity selections and inputs:

- Egress setpoint entity (number) — the entity we write target flow temperature to
- Egress limit entity (number) — hardware maximum
- Egress sensor entity (sensor) — current supply temperature
- Ingress sensor entity (sensor) — current return temperature
- Boiler pressure sensor entity (sensor, optional)
- Pump status entity (binary_sensor or switch)
- Pump power in watts (integer input)
- Minimum runtime in minutes (integer input)

**Step 1.5 — Implement strings.json and translations**

Create user-facing text for the configuration flow in English.

**Step 1.6 — Implement **init**.py (basic)**

Implement `async_setup_entry` to load configuration and log successful setup. No coordinator logic yet.

**Verification:** Restart Home Assistant. Add the integration via Settings → Devices & Services. Confirm Step 1 appears correctly and accepts entity selections. Confirm the integration installs without errors (check logs).

---

### Phase 2: Global Settings and Zone Configuration Flow

**Objective:** Complete the configuration flow with global optimization settings and zone definition.

**Step 2.1 — Implement config_flow.py Step 2 (Global Settings)**

Add the second configuration step requesting:

- Solar power sensor entity (sensor, optional)
- Solar threshold in watts (integer)
- Solar temperature drop in °C (float)
- Valve maintenance frequency (selector: Weekly, Monthly, Disabled)
- Synchronization look-ahead time in minutes (integer)
- Persistence save interval in minutes (integer, with description warning about SD card wear)
- Minimum ignition level as percentage (integer)
- Minimum efficient Delta-T in °C (float)
- Outdoor temperature sensor entity (sensor, for Ke compensation)

**Step 2.2 — Implement config_flow.py Step 3 (Zone Configuration)**

Create a looping zone configuration step. For each zone:

- Zone name (string)
- Temperature sensor entity (sensor)
- Humidity sensor entity (sensor, optional)
- Window/door binary sensor entity (binary_sensor, optional)
- Window setpoint drop in °C (float, shown only if window sensor selected)
- Valve switch entities (multi-select of switch entities)
- Valve opening time in seconds (integer)
- Initial warmup guess in minutes per °C (float)
- Associated schedule entity (schedule helper)

After each zone, offer options to add another zone or finish configuration.

**Step 2.3 — Implement Options Flow**

Allow reconfiguration of global settings and zone parameters after initial setup without removing and re-adding the integration.

**Verification:** Complete the full configuration flow with at least one zone. Confirm all values are stored in the config entry. Test the options flow to modify settings.

---

### Phase 3: Data Coordinator and Persistence Store

**Objective:** Implement the central coordinator and persistent state storage.

**Step 3.1 — Create coordinator.py**

Implement `EmsZoneMasterCoordinator` extending `DataUpdateCoordinator`. Configure update interval of 30 seconds. Initialize data structures for:

- Heater state (current egress, ingress, delta-T, active strategy)
- Zone states (current temp, target temp, demand level, valve states)
- Learned warmup factors per zone
- Last valve maintenance timestamp

**Step 3.2 — Create store.py**

Implement `EmsZoneMasterStore` class handling JSON file persistence in `.storage/heating_pid.json`. Include methods for:

- `async_load()` — load state on startup
- `async_save()` — save current state
- `async_save_on_interval()` — periodic save based on configured interval
- Integration with `async_will_remove_from_hass` for shutdown save

Stored data structure:

```python
{
    "zones": {
        "zone_name": {
            "learned_warmup_factor": 30.0,
            "pid_integral": 0.0
        }
    },
    "last_valve_maintenance": "2026-01-09T10:00:00",
    "version": 1
}
```

**Step 3.3 — Update **init**.py**

Initialize the coordinator and store during setup. Load persisted state before first coordinator update.

**Verification:** Restart Home Assistant. Confirm the coordinator initializes and runs updates every 30 seconds (check debug logs). Manually trigger a save and verify the JSON file is created in `.storage/`. Restart again and confirm state is restored.

---

### Phase 4: Climate Entity and Basic PID Control

**Objective:** Create functional climate entities with PID-based demand calculation.

**Step 4.1 — Create climate.py**

Implement `EmsZoneClimate` extending `ClimateEntity`. Features:

- HVAC modes: `heat` and `off`
- Temperature range: 5°C to 30°C
- Current temperature from configured sensor
- Target temperature (setpoint)
- Manual setpoint tracking with timestamp

**Step 4.2 — Implement PID controller**

Create `pid.py` with `PIDController` class implementing:

- Proportional term: `Kp × error`
- Integral term with anti-windup (clamp integral when output saturates, reset when error crosses zero)
- Derivative term on process variable (rate of change of actual temperature, not error)
- Multiplicative outdoor compensation: `output × (1 + Ke × outdoor_factor)`
- Output clamped to 0-100% range

Default gains (tunable via number entities later):

- Kp: 30
- Ki: 0.5
- Kd: 10
- Ke: 0.02

**Step 4.3 — Implement demand calculation in coordinator**

Each update cycle:

1. For each zone, calculate PID demand based on current vs target temperature
2. Track highest demand across all active zones (max_demand)
3. Store demand values in coordinator data

**Step 4.4 — Create number entities for PID tuning**

Create `number.py` implementing number entities for each zone's Kp, Ki, Kd, Ke values. Changes take effect immediately without restart.

**Verification:** Add the climate entity to a dashboard. Adjust setpoint and observe demand values in coordinator data (via developer tools or logging). Verify PID integral resets appropriately when setpoint is reached. Test outdoor compensation by observing demand changes with different outdoor temperatures.

---

### Phase 5: Heater Strategy and Valve Control

**Objective:** Implement the heater control logic and valve management.

**Step 5.1 — Implement demand curve calculation**

In coordinator, calculate target egress temperature:

```
target = min_egress + (max_demand / 100) × (max_egress - min_egress)
```

Apply constraints in order:

1. Low level filter: if max_demand < min_ignition_level, target = 0
2. Solar limiter: if solar_power > threshold, subtract solar_drop from target
3. Clamp to hardware maximum (egress limit entity value)

**Step 5.2 — Implement Delta-T monitoring and cooldown mode**

Track Delta-T (egress - ingress). When Delta-T falls below min_efficient_delta:

1. Enter cooldown mode
2. Set egress setpoint to minimum (effectively burner off)
3. Keep pump running (do not close valves)
4. Exit cooldown when Delta-T recovers above threshold + hysteresis (e.g., threshold + 2°C)

**Step 5.3 — Implement minimum runtime protection**

Track burner start timestamp. Prevent setting egress to zero until minimum runtime has elapsed, unless safety override.

**Step 5.4 — Implement valve control**

For each zone with demand > 0:

1. Turn on valve switch entities
2. Wait for valve opening time before considering zone "ready"
3. Only include zone in active demand calculation once valves are confirmed open

For zones with demand = 0:

1. Close valves after configurable delay (prevent rapid cycling)

**Step 5.5 — Implement heater command execution**

Write calculated target egress temperature to the setpoint entity. Log all commands for debugging.

**Verification:** Observe the system responding to demand changes. Verify valves open before heating begins. Test solar limiting by simulating high solar power. Trigger cooldown mode by observing behavior when Delta-T drops. Confirm minimum runtime prevents premature shutdown.

---

### Phase 6: Schedule Integration, Adaptive Start, and Window Logic

**Objective:** Implement schedule reading, adaptive start learning, and window override logic.

**Step 6.1 — Implement schedule reader**

Create `schedule.py` with functions to:

- Read current and next scheduled setpoint from Home Assistant schedule entity
- Calculate time until next schedule change
- Determine if zone is in "scheduled active" period

**Step 6.2 — Implement window logic**

In climate entity and coordinator:

1. Monitor window binary sensor state
2. When window opens: reduce target setpoint by configured drop (maintain frost protection)
3. When window closes: restore original setpoint
4. Window state takes priority over schedule and manual setpoints

**Step 6.3 — Implement manual setpoint handling**

Track when user manually adjusts setpoint:

1. Store manual setpoint and timestamp
2. Manual setpoint overrides schedule until next schedule event
3. When next schedule event occurs, clear manual override and follow schedule

**Step 6.4 — Implement adaptive start**

Using learned warmup factor and schedule data:

1. Read next scheduled setpoint and time from schedule entity
2. Calculate required start time: `start = scheduled_time - (temp_delta × warmup_factor)`
3. If current time > calculated start time, begin heating early
4. Expose pre-heating state as attribute

**Step 6.5 — Implement warmup factor learning**

After reaching target temperature:

1. Calculate actual warmup speed: `elapsed_minutes / temp_rise`
2. Update learned factor using exponential moving average: `new = 0.8 × old + 0.2 × measured`
3. Apply bounds: new factor must be within ±10% of previous (prevents outlier overcorrection)
4. Persist updated factor to store

**Step 6.6 — Create time-to-target sensor**

Create `sensor.py` implementing sensor entity showing estimated minutes remaining:

```
minutes = (target - current) × learned_warmup_factor
```

**Verification:** Create a schedule helper with multiple setpoints. Verify climate entity follows schedule. Test manual override persists until next schedule event. Test window logic reduces setpoint when opened. Observe adaptive start triggering early heating. Monitor learned warmup factor adjusting over multiple heating cycles.

---

### Phase 7: Smart Synchronization and Valve Maintenance

**Objective:** Implement efficiency optimization features.

**Step 7.1 — Implement smart synchronization**

In coordinator update cycle, when any zone is actively heating:

1. Iterate through inactive zones
2. For each inactive zone, check schedule for next event time
3. If next event is within sync_look_ahead_time and would start heating:
   - Force zone to begin heating now (open valves, include in demand)
   - Mark zone as "synchronized" for status reporting
4. Clear synchronization flag when zone reaches its scheduled start time

**Step 7.2 — Implement valve maintenance routine**

In coordinator:

1. Track last maintenance timestamp from store
2. On each update, check if maintenance is due based on configured frequency
3. When due:
   - Log maintenance start
   - Open all valves sequentially
   - Run pump for 5 minutes
   - Close all valves
   - Update timestamp and persist

**Step 7.3 — Create master status sensor**

Implement `sensor.ems_master_status` with:

- State: current strategy (Idle, Heating, Solar Limited, Cooldown, Maintenance, Synchronizing)
- Attributes:
  - `active_zones`: list of currently heating zones
  - `synchronized_zones`: list of zones started early
  - `max_demand`: current highest demand percentage
  - `target_egress`: calculated target temperature
  - `delta_t`: current supply/return difference
  - `next_maintenance`: timestamp of next scheduled maintenance

**Step 7.4 — Implement sensor unavailability handling**

Add error handling throughout coordinator:

1. If critical sensor (egress, ingress, zone temp) becomes unavailable:
   - Log warning
   - Fire Home Assistant event for notification automation
   - After configurable timeout: enter frost protection mode (setpoint 7°C)
2. When sensor recovers, resume normal operation

**Step 7.5 — Final testing and refinement**

Comprehensive testing across all features:

- Multiple zone coordination
- Schedule transitions
- Edge cases (all zones off, all zones max demand)
- Restart recovery
- Long-running stability

**Verification:** Test synchronization by configuring two zones with staggered schedules within the look-ahead window. Verify both start together. Trigger valve maintenance manually by setting last maintenance date in the past. Verify status sensor shows correct state throughout all operating modes. Test sensor failure handling by disabling an entity temporarily.

---

## Deliverables Summary

At completion, you will have:

| Component        | Files                                                      |
| ---------------- | ---------------------------------------------------------- |
| Integration Core | `__init__.py`, `manifest.json`, `const.py`                 |
| Configuration    | `config_flow.py`, `strings.json`, `translations/en.json`   |
| Coordinator      | `coordinator.py`, `store.py`, `schedule.py`                |
| Control Logic    | `pid.py`                                                   |
| Entities         | `climate.py`, `sensor.py`, `number.py`, `binary_sensor.py` |

---

## Next Steps

Shall I proceed with generating the code for Phase 1? I will provide complete, tested code files with inline documentation explaining each component. We will work through each phase sequentially, verifying functionality before advancing.
