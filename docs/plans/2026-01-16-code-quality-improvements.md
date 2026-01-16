# Code Quality Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all code quality issues from analysis, remove deprecated global solar drop setting, and add schedule validation in config flow.

**Architecture:** Incremental fixes organized by file, maintaining backwards compatibility where needed. Schedule validation adds a helper function that validates schedule entities and displays results in config flow.

**Tech Stack:** Python, Home Assistant integration patterns, voluptuous for config validation.

---

## Task 1: Fix Timezone Issues (High Priority)

**Files:**
- Modify: `custom_components/heating_pid/coordinator.py` (lines 441, 519, 629, 965, 1025, 603)
- Modify: `custom_components/heating_pid/schedule.py` (lines 104, 188, 220, 249, 414)

**Step 1: Update coordinator.py imports**

Add `homeassistant.util.dt` import and replace all `datetime.now()` calls.

In coordinator.py, add to imports section (around line 23):

```python
from homeassistant.util import dt as dt_util
```

**Step 2: Replace datetime.now() in coordinator.py**

Replace these occurrences:
- Line 441: `now = datetime.now()` → `now = dt_util.now()`
- Line 519: `now = datetime.now()` → `now = dt_util.now()`
- Line 629: `now = datetime.now()` → `now = dt_util.now()`
- Line 965: `now = datetime.now()` → `now = dt_util.now()`
- Line 1025: `now = datetime.now()` → `now = dt_util.now()`
- Line 603: `zone.last_valve_activity = datetime.now()` → `zone.last_valve_activity = dt_util.now()`

**Step 3: Update schedule.py imports**

Add import at line 26:

```python
from homeassistant.util import dt as dt_util
```

**Step 4: Replace datetime.now() in schedule.py**

Replace these occurrences:
- Line 104: `now = datetime.now()` → `now = dt_util.now()`
- Line 188: `now = datetime.now()` → `now = dt_util.now()`
- Line 220: `now = datetime.now()` → `now = dt_util.now()`
- Line 249: `now = datetime.now()` → `now = dt_util.now()`
- Line 414: `now = datetime.now()` → `now = dt_util.now()`

**Step 5: Commit**

```bash
git add custom_components/heating_pid/coordinator.py custom_components/heating_pid/schedule.py
git commit -m "fix: Use timezone-aware datetime throughout

Replace datetime.now() with homeassistant.util.dt.now() to prevent
issues with DST transitions and non-local timezones."
```

---

## Task 2: Add Error Handling to Valve Control (High Priority)

**Files:**
- Modify: `custom_components/heating_pid/coordinator.py` (methods `_control_switch_valve` and `_control_climate_valve`)

**Step 1: Wrap switch valve service calls in try/except**

Replace the `_control_switch_valve` method body with error handling:

```python
async def _control_switch_valve(
    self, entity_id: str, zone: ZoneState, should_open: bool
) -> None:
    """Control a switch-type valve entity.

    Args:
        entity_id: Switch entity ID
        zone: Zone state for tracking activity
        should_open: True to turn on (open), False to turn off (close)
    """
    current_state = self.hass.states.get(entity_id)
    if current_state is None:
        return

    is_on = current_state.state == "on"
    now = dt_util.now()

    try:
        # Apply valve anti-cycling protection
        if should_open and not is_on:
            # Check minimum off-time before opening
            if zone.valve_closed_at and self._valve_min_off_time > 0:
                time_since_close = (now - zone.valve_closed_at).total_seconds() / 60
                if time_since_close < self._valve_min_off_time:
                    _LOGGER.debug(
                        "Valve %s: skipping open, only %.1f min since close (min: %d)",
                        entity_id,
                        time_since_close,
                        self._valve_min_off_time,
                    )
                    return

            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": entity_id}, blocking=True
            )
            zone.last_valve_activity = now
            zone.valve_opened_at = now
            _LOGGER.debug("Opened valve: %s", entity_id)

        elif not should_open and is_on:
            # Check minimum on-time before closing
            if zone.valve_opened_at and self._valve_min_on_time > 0:
                time_since_open = (now - zone.valve_opened_at).total_seconds() / 60
                if time_since_open < self._valve_min_on_time:
                    _LOGGER.debug(
                        "Valve %s: skipping close, only %.1f min since open (min: %d)",
                        entity_id,
                        time_since_open,
                        self._valve_min_on_time,
                    )
                    return

            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": entity_id}, blocking=True
            )
            zone.valve_closed_at = now
            _LOGGER.debug("Closed valve: %s", entity_id)
    except Exception as err:
        _LOGGER.error("Failed to control switch valve %s: %s", entity_id, err)
```

**Step 2: Wrap climate valve service calls in try/except**

Replace the `_control_climate_valve` method body with error handling:

```python
async def _control_climate_valve(
    self, entity_id: str, zone: ZoneState, should_open: bool
) -> None:
    """Control a climate-type valve entity (e.g., TRV).

    For climate entities, we set HVAC mode to heat/off and
    optionally set the target temperature.

    Args:
        entity_id: Climate entity ID
        zone: Zone state with setpoint info
        should_open: True to enable heating, False to turn off
    """
    current_state = self.hass.states.get(entity_id)
    if current_state is None:
        return

    current_mode = current_state.state
    now = dt_util.now()

    try:
        if should_open:
            # Check minimum off-time before opening
            if current_mode != "heat":
                if zone.valve_closed_at and self._valve_min_off_time > 0:
                    time_since_close = (now - zone.valve_closed_at).total_seconds() / 60
                    if time_since_close < self._valve_min_off_time:
                        _LOGGER.debug(
                            "Climate %s: skipping heat, only %.1f min since off (min: %d)",
                            entity_id,
                            time_since_close,
                            self._valve_min_off_time,
                        )
                        return

                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "heat"},
                    blocking=True,
                )
                zone.last_valve_activity = now
                zone.valve_opened_at = now
                _LOGGER.debug("Set climate to heat: %s", entity_id)

            # Also set temperature to zone setpoint
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": zone.setpoint},
                blocking=True,
            )
        elif current_mode not in ("off", "unavailable"):
            # Check minimum on-time before closing
            if zone.valve_opened_at and self._valve_min_on_time > 0:
                time_since_open = (now - zone.valve_opened_at).total_seconds() / 60
                if time_since_open < self._valve_min_on_time:
                    _LOGGER.debug(
                        "Climate %s: skipping off, only %.1f min since heat (min: %d)",
                        entity_id,
                        time_since_open,
                        self._valve_min_on_time,
                    )
                    return

            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": "off"},
                blocking=True,
            )
            zone.valve_closed_at = now
            _LOGGER.debug("Set climate to off: %s", entity_id)
    except Exception as err:
        _LOGGER.error("Failed to control climate valve %s: %s", entity_id, err)
```

**Step 3: Commit**

```bash
git add custom_components/heating_pid/coordinator.py
git commit -m "fix: Add error handling to valve control methods

Wrap service calls in try/except blocks to prevent valve control
failures from crashing the entire update cycle."
```

---

## Task 3: Create translations/en.json (High Priority)

**Files:**
- Create: `custom_components/heating_pid/translations/en.json`

**Step 1: Copy strings.json to translations/en.json**

The content should be identical to strings.json. Home Assistant loads translations from this directory.

```bash
cp custom_components/heating_pid/strings.json custom_components/heating_pid/translations/en.json
```

**Step 2: Commit**

```bash
git add custom_components/heating_pid/translations/en.json
git commit -m "fix: Add translations/en.json for Home Assistant

Copy strings.json to translations directory for proper localization support."
```

---

## Task 4: Remove Dead Code in Manual Setpoint Clearing (Medium Priority)

**Files:**
- Modify: `custom_components/heating_pid/coordinator.py` (lines 694-703)

**Step 1: Remove the unreachable code block**

The code at lines 694-703 checks `zone.manual_setpoint is not None` inside the `elif zone.schedule_reader is not None` branch, but this branch is only reached when `zone.manual_setpoint is None` (line 640). This is dead code.

Remove lines 694-703:
```python
                # Clear manual setpoint when schedule changes
                if (
                    zone.manual_setpoint is not None
                    and scheduled_setpoint != previous_setpoint
                ):
                    _LOGGER.info(
                        "Zone %s: clearing manual setpoint due to schedule change",
                        zone.name,
                    )
                    zone.manual_setpoint = None
```

**Step 2: Commit**

```bash
git add custom_components/heating_pid/coordinator.py
git commit -m "fix: Remove dead code in manual setpoint clearing

The condition checking manual_setpoint inside the schedule branch
could never be true since that branch only executes when
manual_setpoint is None."
```

---

## Task 5: Implement Solar Limited State Detection (Medium Priority)

**Files:**
- Modify: `custom_components/heating_pid/sensor.py` (MasterStatusSensor.native_value)
- Modify: `custom_components/heating_pid/coordinator.py` (add solar_limited property)

**Step 1: Add solar_limited property to coordinator**

Add after the `cooldown_active` property (around line 1136):

```python
@property
def solar_limited(self) -> bool:
    """Return whether solar limiting is currently active."""
    return (
        self._solar_power is not None
        and self._solar_power > self._solar_threshold
        and self._max_demand > 0
    )
```

**Step 2: Update MasterStatusSensor to use solar_limited**

Replace the `native_value` property in MasterStatusSensor:

```python
@property
def native_value(self) -> str:
    """Return current system status."""
    if self.coordinator.cooldown_active:
        return "cooldown"

    if self.coordinator.max_demand <= 0:
        return "idle"

    if self.coordinator.solar_limited:
        return "solar_limited"

    return "heating"
```

**Step 3: Add solar_limited to extra_state_attributes**

Update the `extra_state_attributes` property:

```python
@property
def extra_state_attributes(self) -> dict[str, float | bool]:
    """Return additional status information."""
    return {
        "max_demand": round(self.coordinator.max_demand, 1),
        "target_flow_temp": round(self.coordinator.target_flow_temp, 1),
        "cooldown_active": self.coordinator.cooldown_active,
        "solar_limited": self.coordinator.solar_limited,
    }
```

**Step 4: Commit**

```bash
git add custom_components/heating_pid/coordinator.py custom_components/heating_pid/sensor.py
git commit -m "feat: Implement solar_limited state detection

Add solar_limited property to coordinator and update MasterStatusSensor
to display solar_limited state when solar power exceeds threshold."
```

---

## Task 6: Remove Unused Imports (Low Priority)

**Files:**
- Modify: `custom_components/heating_pid/binary_sensor.py` (line 23)
- Modify: `custom_components/heating_pid/sensor.py` (line 26)
- Modify: `custom_components/heating_pid/coordinator.py` (line 626)

**Step 1: Remove DOMAIN from binary_sensor.py**

Change line 23 from:
```python
from .const import DOMAIN, MIN_EFFICIENT_DELTA_T
```
to:
```python
from .const import MIN_EFFICIENT_DELTA_T
```

**Step 2: Remove ATTR_TIME_TO_TARGET from sensor.py**

Change line 26 from:
```python
from .const import ATTR_TIME_TO_TARGET, DOMAIN
```
to:
```python
from .const import DOMAIN
```

**Step 3: Remove SYNC_LOOK_AHEAD from coordinator.py line 626**

Change line 626 from:
```python
from .const import DEFAULT_WINDOW_DROP, SYNC_LOOK_AHEAD
```
to:
```python
from .const import DEFAULT_WINDOW_DROP
```

**Step 4: Commit**

```bash
git add custom_components/heating_pid/binary_sensor.py custom_components/heating_pid/sensor.py custom_components/heating_pid/coordinator.py
git commit -m "chore: Remove unused imports

Remove DOMAIN from binary_sensor.py, ATTR_TIME_TO_TARGET from sensor.py,
and SYNC_LOOK_AHEAD from coordinator.py _update_zone_demands method."
```

---

## Task 7: Use Platform Enum for PLATFORMS (Low Priority)

**Files:**
- Modify: `custom_components/heating_pid/const.py` (line 12)

**Step 1: Add Platform import and update PLATFORMS**

Add import at top of file:
```python
from homeassistant.const import Platform
```

Change line 12 from:
```python
PLATFORMS: Final = ["climate", "sensor", "number", "binary_sensor"]
```
to:
```python
PLATFORMS: Final = [Platform.CLIMATE, Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR]
```

**Step 2: Commit**

```bash
git add custom_components/heating_pid/const.py
git commit -m "chore: Use Platform enum for PLATFORMS constant

Replace string literals with Platform enum values for type safety
and IDE support."
```

---

## Task 8: Remove Global Solar Drop from Settings (User Request)

**Files:**
- Modify: `custom_components/heating_pid/config_flow.py`
- Modify: `custom_components/heating_pid/strings.json`
- Modify: `custom_components/heating_pid/translations/en.json`

**Step 1: Remove CONF_SOLAR_DROP from config_flow.py imports**

Remove `CONF_SOLAR_DROP` and `DEFAULT_SOLAR_DROP` from the imports at the top of the file.

**Step 2: Remove solar_drop from async_step_global schema**

In `async_step_global`, remove the entire `vol.Required(CONF_SOLAR_DROP...)` block (lines 225-231).

**Step 3: Remove solar_drop from async_step_global_settings schema**

In `EmsZoneMasterOptionsFlow.async_step_global_settings`, remove the entire `vol.Required(CONF_SOLAR_DROP...)` block (lines 450-457).

**Step 4: Update strings.json**

Remove from `config.step.global.data`:
```json
"solar_drop": "Solar Temperature Reduction",
```

Remove from `config.step.global.data_description`:
```json
"solar_drop": "How much to lower water temperature when solar limit is reached",
```

Remove from `options.step.global_settings.data`:
```json
"solar_drop": "Solar Temperature Reduction",
```

Remove from `options.step.global_settings.data_description`:
```json
"solar_drop": "How much to lower temperature when solar limit is reached",
```

**Step 5: Update translations/en.json**

Same changes as strings.json.

**Step 6: Update coordinator.py to handle missing global solar_drop**

In coordinator `__init__`, change line 173 to have a default of 0:
```python
self._solar_drop: float = entry.data.get(CONF_SOLAR_DROP, 0.0)
```

**Step 7: Commit**

```bash
git add custom_components/heating_pid/config_flow.py custom_components/heating_pid/strings.json custom_components/heating_pid/translations/en.json custom_components/heating_pid/coordinator.py
git commit -m "feat: Remove global Solar Temperature Reduction setting

Solar drop is now configured per-zone only. Existing configs will
default to 0 for the global value, using zone-specific settings."
```

---

## Task 9: Add Schedule Validation in Config Flow (User Request)

**Files:**
- Modify: `custom_components/heating_pid/config_flow.py`
- Modify: `custom_components/heating_pid/strings.json`
- Modify: `custom_components/heating_pid/translations/en.json`

**Step 1: Add schedule validation helper function**

Add this function after `_validate_entity_exists`:

```python
def _validate_schedule_format(hass, entity_id: str | None) -> dict[str, Any]:
    """Validate a schedule entity has valid temperature blocks.

    Args:
        hass: Home Assistant instance
        entity_id: Schedule entity ID to validate

    Returns:
        Dictionary with 'valid' bool, 'message' str, and 'temps' list
    """
    if not entity_id:
        return {"valid": True, "message": "", "temps": []}

    state = hass.states.get(entity_id)
    if state is None:
        return {"valid": False, "message": "Schedule entity not found", "temps": []}

    weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    attributes = dict(state.attributes)

    # Check for weekday data
    valid_days = [d for d in weekday_names if d in attributes]
    if not valid_days:
        return {
            "valid": False,
            "message": "No schedule blocks configured",
            "temps": [],
        }

    # Collect all temperature values
    temps: list[float] = []
    blocks_without_temp = 0
    total_blocks = 0

    for day in valid_days:
        day_schedule = attributes.get(day, [])
        for block in day_schedule:
            if not isinstance(block, dict):
                continue
            total_blocks += 1
            data = block.get("data", {})
            if isinstance(data, dict) and "temp" in data:
                try:
                    temps.append(float(data["temp"]))
                except (ValueError, TypeError):
                    pass
            else:
                blocks_without_temp += 1

    if total_blocks == 0:
        return {
            "valid": False,
            "message": "No time blocks found in schedule",
            "temps": [],
        }

    unique_temps = sorted(set(temps))

    if not temps:
        return {
            "valid": False,
            "message": f"Found {total_blocks} blocks but none have temperature values. "
                       "Add 'temp' to each block's data field.",
            "temps": [],
        }

    if blocks_without_temp > 0:
        return {
            "valid": True,
            "message": f"Found {len(temps)} temperature blocks ({', '.join(f'{t}°C' for t in unique_temps)}). "
                       f"Note: {blocks_without_temp} blocks have no temp (will use default).",
            "temps": unique_temps,
        }

    return {
        "valid": True,
        "message": f"Valid: {len(temps)} temperature blocks ({', '.join(f'{t}°C' for t in unique_temps)})",
        "temps": unique_temps,
    }
```

**Step 2: Add validation step for zones**

Add a new step `async_step_validate_schedule` to `EmsZoneMasterConfigFlow`:

```python
async def async_step_validate_schedule(
    self, user_input: dict[str, Any] | None = None
) -> ConfigFlowResult:
    """Show schedule validation result and allow proceeding."""
    if user_input is not None:
        # User confirmed, proceed to zones step
        return await self.async_step_zones()

    # Get the schedule entity from stored data
    schedule_entity = self._pending_zone_data.get(CONF_ZONE_SCHEDULE_ENTITY)
    validation = _validate_schedule_format(self.hass, schedule_entity)

    return self.async_show_form(
        step_id="validate_schedule",
        data_schema=vol.Schema({}),
        description_placeholders={
            "validation_result": validation["message"],
            "status_icon": "✓" if validation["valid"] else "⚠",
        },
    )
```

**Step 3: Modify async_step_zones to store pending data**

Add `self._pending_zone_data: dict[str, Any] = {}` to `__init__`.

In `async_step_zones`, when a schedule entity is provided and validation passes, store the data and go to validation step:

```python
if not errors:
    zone_data = {k: v for k, v in user_input.items() if k != "add_another"}

    # If schedule entity provided, show validation step
    if zone_data.get(CONF_ZONE_SCHEDULE_ENTITY):
        self._pending_zone_data = zone_data
        self._pending_add_another = user_input.get("add_another", False)
        return await self.async_step_validate_schedule()

    # No schedule, proceed directly
    if user_input.get("add_another", False):
        self._zones.append(zone_data)
        return await self.async_step_zones()
    else:
        self._zones.append(zone_data)
        self._data[CONF_ZONES] = self._zones
        return self.async_create_entry(
            title="EMS Zone Master",
            data=self._data,
        )
```

**Step 4: Update strings.json**

Add to `config.step`:
```json
"validate_schedule": {
    "title": "Schedule Validation",
    "description": "{status_icon} {validation_result}\n\nClick Submit to continue adding this zone."
}
```

**Step 5: Update translations/en.json**

Same changes as strings.json.

**Step 6: Add validation to options flow edit_zone**

Similar changes to `async_step_edit_zone` in `EmsZoneMasterOptionsFlow`.

**Step 7: Commit**

```bash
git add custom_components/heating_pid/config_flow.py custom_components/heating_pid/strings.json custom_components/heating_pid/translations/en.json
git commit -m "feat: Add schedule validation in config flow

When adding/editing a zone with a schedule entity, display validation
results showing detected temperature blocks or warnings about missing
temperature data in schedule blocks."
```

---

## Task 10: Update Version Number

**Files:**
- Modify: `custom_components/heating_pid/const.py`
- Modify: `custom_components/heating_pid/manifest.json`

**Step 1: Update version to 0.5.0**

In const.py, change line 6:
```python
VERSION: Final = "0.5.0"
```

In manifest.json, change line 4:
```json
"version": "0.5.0",
```

**Step 2: Commit and tag**

```bash
git add custom_components/heating_pid/const.py custom_components/heating_pid/manifest.json
git commit -m "chore: Bump version to 0.5.0"
git tag -a v0.5.0 -m "v0.5.0: Code quality improvements and schedule validation"
```

---

## Summary

| Task | Priority | Description |
|------|----------|-------------|
| 1 | High | Fix timezone issues with datetime.now() |
| 2 | High | Add error handling to valve control |
| 3 | High | Create translations/en.json |
| 4 | Medium | Remove dead code in manual setpoint clearing |
| 5 | Medium | Implement solar_limited state detection |
| 6 | Low | Remove unused imports |
| 7 | Low | Use Platform enum for PLATFORMS |
| 8 | User | Remove global solar drop setting |
| 9 | User | Add schedule validation in config flow |
| 10 | - | Update version number |

**Estimated complexity:** Low-Medium (mostly straightforward edits, schedule validation is the most complex)
