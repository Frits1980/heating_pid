# Feature Design: Manual Setpoint Expiration, Entity Options, Away Mode

**Date:** 2026-01-18
**Status:** Approved

## Overview

Three features plus two improvements to the EMS Zone Master integration:

1. **Manual Setpoint Expiration** - Clear manual overrides when schedule transitions
2. **Heater Entities Options** - Allow changing core entities after initial setup
3. **Away Mode** - Reduce heating when nobody is home
4. **Time Handling** - Consistent timezone-aware time handling
5. **Error Handling** - Robust service call error handling

---

## Feature 1: Manual Setpoint Expiration

### Problem
Manual setpoints persist forever, locking zones out of their schedules. The code comments claim manual setpoints "persist until next schedule event" but no expiration logic exists.

### Solution
Track the schedule state when manual setpoint is set. Clear the manual setpoint when the schedule transitions (on→off or off→on).

### Changes

**coordinator.py - ZoneState.__init__:**
```python
self.manual_setpoint_schedule_state: bool | None = None  # Schedule state when manual was set
```

**coordinator.py - _update_zone_demands():**
```python
# Before checking manual_setpoint:
if zone.manual_setpoint is not None and zone.schedule_reader is not None:
    current_schedule_state = zone.schedule_reader.is_schedule_active(now)
    if zone.manual_setpoint_schedule_state is not None:
        if current_schedule_state != zone.manual_setpoint_schedule_state:
            # Schedule transitioned - clear manual override
            _LOGGER.info("Zone %s: clearing manual setpoint (schedule transitioned)", zone.name)
            zone.manual_setpoint = None
            zone.manual_setpoint_schedule_state = None
```

**climate.py - async_set_temperature():**
```python
# After setting manual_setpoint:
if self._zone.schedule_reader is not None:
    from homeassistant.util import dt as dt_util
    now = dt_util.now()
    self._zone.manual_setpoint_schedule_state = self._zone.schedule_reader.is_schedule_active(now)
else:
    self._zone.manual_setpoint_schedule_state = None
```

### Persistence
The `manual_setpoint_schedule_state` does NOT need to be persisted. On restart, if there's a stored manual setpoint but no schedule state, it will clear on the first schedule transition.

---

## Feature 2: Heater Entities Options Step

### Problem
Cannot change heater/flow/return/outdoor/solar entities after initial setup.

### Solution
Add new "heater_entities" menu option to options flow.

### Changes

**config_flow.py - EmsZoneMasterOptionsFlow.async_step_init():**
```python
async def async_step_init(self, user_input=None):
    return self.async_show_menu(
        step_id="init",
        menu_options=["heater_entities", "global_settings", "add_zone", "manage_zones"],
    )
```

**config_flow.py - New method:**
```python
async def async_step_heater_entities(self, user_input=None):
    """Handle heater entity configuration."""
    errors = {}

    if user_input is not None:
        # Validate all required entities exist
        for key in [CONF_HEATER_ENTITY, CONF_FLOW_TEMP_ENTITY,
                    CONF_RETURN_TEMP_ENTITY, CONF_OUTDOOR_TEMP_ENTITY]:
            if not _validate_entity_exists(self.hass, user_input.get(key)):
                errors[key] = "entity_not_found"

        # Validate optional solar entity
        if not _validate_entity_exists(self.hass, user_input.get(CONF_SOLAR_POWER_ENTITY)):
            errors[CONF_SOLAR_POWER_ENTITY] = "entity_not_found"

        if not errors:
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

    schema = vol.Schema({
        vol.Required(CONF_HEATER_ENTITY,
            default=self.config_entry.data.get(CONF_HEATER_ENTITY)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="number")),
        vol.Required(CONF_FLOW_TEMP_ENTITY,
            default=self.config_entry.data.get(CONF_FLOW_TEMP_ENTITY)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
        vol.Required(CONF_RETURN_TEMP_ENTITY,
            default=self.config_entry.data.get(CONF_RETURN_TEMP_ENTITY)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
        vol.Required(CONF_OUTDOOR_TEMP_ENTITY,
            default=self.config_entry.data.get(CONF_OUTDOOR_TEMP_ENTITY)
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
        vol.Optional(CONF_SOLAR_POWER_ENTITY,
            description={"suggested_value": self.config_entry.data.get(CONF_SOLAR_POWER_ENTITY)}
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
    })

    return self.async_show_form(step_id="heater_entities", data_schema=schema, errors=errors)
```

**strings.json - Add menu option:**
```json
"options": {
  "step": {
    "init": {
      "menu_options": {
        "heater_entities": "Heater Entities",
        "global_settings": "Global Settings",
        "add_zone": "Add Zone",
        "manage_zones": "Manage Zones"
      }
    },
    "heater_entities": {
      "title": "Heater Entities",
      "description": "Configure the core heater and sensor entities"
    }
  }
}
```

---

## Feature 3: Away Mode

### Problem
No way to reduce heating when nobody is home.

### Solution
Add presence entity selector and away delay globally. Each zone gets its own away temperature setpoint.

### New Constants (const.py)

```python
CONF_PRESENCE_ENTITY = "presence_entity"
CONF_AWAY_DELAY = "away_delay"  # minutes before applying away mode
CONF_ZONE_AWAY_TEMP = "away_temp"  # zone-specific away temperature

DEFAULT_AWAY_DELAY = 30  # 30 minutes
DEFAULT_AWAY_TEMP = 15.0  # 15°C when away
```

### Config Flow Changes

**Global settings (async_step_global and async_step_global_settings):**
```python
vol.Optional(CONF_PRESENCE_ENTITY): selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean", "person", "group"])
),
vol.Optional(CONF_AWAY_DELAY, default=DEFAULT_AWAY_DELAY): selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=120, step=5, unit_of_measurement="min")
),
```

**Zone configuration (async_step_zones, async_step_add_zone, async_step_edit_zone):**
```python
vol.Optional(CONF_ZONE_AWAY_TEMP, default=DEFAULT_AWAY_TEMP): selector.NumberSelector(
    selector.NumberSelectorConfig(min=5, max=25, step=0.5, unit_of_measurement="°C")
),
```

### Coordinator Changes

**New instance variables in __init__:**
```python
self._presence_entity_id: str | None = entry.data.get(CONF_PRESENCE_ENTITY)
self._away_delay: int = entry.data.get(CONF_AWAY_DELAY, DEFAULT_AWAY_DELAY)
self._away_mode_active: bool = False
self._presence_lost_at: datetime | None = None  # When presence went "off"
```

**ZoneState.__init__:**
```python
self.away_temp: float = DEFAULT_AWAY_TEMP  # Set from config during _init_zones
```

**_init_zones():**
```python
zone.away_temp = zone_config.get(CONF_ZONE_AWAY_TEMP, DEFAULT_AWAY_TEMP)
```

**New method _update_away_mode():**
```python
def _update_away_mode(self, now: datetime) -> None:
    """Update away mode state based on presence entity."""
    if not self._presence_entity_id:
        self._away_mode_active = False
        return

    state = self.hass.states.get(self._presence_entity_id)
    if state is None:
        return

    # Check if "home" (on/home) or "away" (off/not_home)
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
```

**_update_zone_demands() - priority hierarchy:**
```python
if self._away_mode_active:
    zone.setpoint = zone.away_temp
    zone.adaptive_start_active = False
    _LOGGER.debug("Zone %s: away mode, using away temp %.1f°C", zone.name, zone.away_temp)
elif zone.manual_setpoint is not None:
    # ... existing manual setpoint logic
elif zone.schedule_reader is not None:
    # ... existing schedule logic
else:
    zone.setpoint = zone.default_setpoint
```

**Call _update_away_mode(now) in _async_update_data() before _update_zone_demands().**

### Priority Hierarchy (Updated)

1. Away mode → use zone's away_temp
2. Window open → setpoint reduced
3. Manual setpoint → persists until schedule transition
4. Schedule setpoint → from schedule helper
5. Default setpoint → configured during setup

---

## Improvement 4: Time Handling

### Problem
`datetime.now()` and `time.monotonic()` used directly, causing timezone issues and making PID non-deterministic.

### Solution
- Replace `datetime.now()` with `homeassistant.util.dt.now()`
- Pass time delta explicitly to PID controller from coordinator

### Changes

**pid.py:**
```python
def update(self, setpoint: float, process_variable: float, outdoor_temp: float | None, dt: float) -> float:
    """
    Args:
        dt: Time delta in seconds since last update
    """
    # Remove internal time.monotonic() tracking
    # Use passed dt parameter instead
```

**coordinator.py:**
```python
# Track last update time
self._last_update: datetime | None = None

# In _async_update_data:
now = dt_util.now()
dt = (now - self._last_update).total_seconds() if self._last_update else 30.0
self._last_update = now

# Pass dt to PID:
zone.demand = zone.pid.update(
    setpoint=effective_setpoint,
    process_variable=zone.current_temp,
    outdoor_temp=self._outdoor_temp,
    dt=dt,
)
```

---

## Improvement 5: Error Handling in Service Calls

### Problem
Blocking service calls can crash or hang the update loop if they fail.

### Solution
Wrap all service calls with error handling.

### Changes

**coordinator.py - New helper method:**
```python
async def _safe_service_call(self, domain: str, service: str, data: dict) -> bool:
    """Call a service with error handling. Returns True on success."""
    try:
        await self.hass.services.async_call(domain, service, data, blocking=True)
        return True
    except Exception as err:
        _LOGGER.error("Service call %s.%s failed for %s: %s", domain, service, data.get("entity_id"), err)
        return False
```

**Update all service calls to use this helper:**
- `_control_switch_valve()`
- `_control_climate_valve()`
- `_set_heater_temperature()`
- `_perform_valve_maintenance()`

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `const.py` | Add CONF_PRESENCE_ENTITY, CONF_AWAY_DELAY, CONF_ZONE_AWAY_TEMP, defaults |
| `config_flow.py` | Add heater_entities step, add away mode fields to global and zone forms |
| `coordinator.py` | Manual setpoint expiration, away mode logic, time handling, error handling |
| `climate.py` | Set manual_setpoint_schedule_state when setting temperature |
| `pid.py` | Accept dt parameter instead of internal time tracking |
| `strings.json` | Add heater_entities translations |
| `translations/en.json` | Add heater_entities translations |

---

## Implementation Order

1. Manual setpoint expiration (isolated bugfix)
2. Time handling improvement (affects PID, needed before other changes)
3. Error handling improvement (foundation for reliability)
4. Heater entities options (config_flow only)
5. Away mode (const, config_flow, coordinator)
