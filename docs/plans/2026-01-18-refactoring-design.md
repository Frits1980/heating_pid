# Refactoring Design: Code Quality & Architecture Improvements

**Date:** 2026-01-18
**Status:** Approved

## Overview

Eight refactoring improvements to improve code quality, maintainability, and reliability:

1. **Import Organization** - PEP 8 compliant imports
2. **Type Safety** - Full mypy strict compliance
3. **Manifest & Documentation** - Complete manifest, README, CHANGELOG
4. **Persist PID Tuning** - Save tuned gains across restarts
5. **Configuration Validation** - Graceful handling of missing entities
6. **Service Calls** - Reset learning, PID, force maintenance
7. **Decompose Coordinator** - Extract ValveManager, HeaterController, ZoneLogic
8. **Event-Driven Updates** - Debounced state change reactions

## Version Control Strategy

**Commit after every refactoring step and push with a new tag.**

Tag format: `v[year].[month].[day][int_increment]`

Example sequence:
- `v2026.01.183` - Import organization
- `v2026.01.184` - Type safety
- `v2026.01.185` - Manifest & documentation
- etc.

---

## Refactoring 1: Import Organization

**Problem:** Imports inside methods violate PEP 8 and obscure dependencies.

**Files to fix:**

| File | Inline Import | Resolution |
|------|---------------|------------|
| `coordinator.py` | `import asyncio` in `_perform_valve_maintenance` | Move to top |
| `coordinator.py` | `from .const import ...` in `_init_zones` | Move to top |
| `coordinator.py` | `from .const import ...` in `_update_zone_demands` | Move to top |
| `coordinator.py` | `from .const import ...` in `_apply_synchronization` | Move to top |
| `coordinator.py` | `from .schedule import ScheduleReader` in `_init_zones` | Move to top with `TYPE_CHECKING` |

**Pattern for avoiding circular imports:**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

# Standard library
import asyncio
import logging
from datetime import datetime, timedelta

# Third party
from homeassistant.core import HomeAssistant

# Local - always available
from .const import (
    CONF_ZONES,
    DEFAULT_WINDOW_DROP,
    # ... all constants used anywhere in file
)

# Local - type checking only (breaks circular imports)
if TYPE_CHECKING:
    from .schedule import ScheduleReader
```

**Tag:** `v2026.01.183`

---

## Refactoring 2: Type Safety

**Problem:** `Any` types used throughout, no mypy compliance.

**New file: `types.py`**

```python
from typing import TypedDict
from datetime import time

class ScheduleBlock(TypedDict, total=False):
    from_: time
    to: time
    data: dict[str, str | float]

class ZoneConfig(TypedDict, total=False):
    zone_name: str
    temp_entity: str
    valve_entity: str
    window_entity: str | None
    schedule_entity: str | None
    default_setpoint: float
    away_temp: float
    kp: float
    ki: float
    kd: float
    ke: float
    solar_drop: float | None

class CoordinatorData(TypedDict):
    flow_temp: float | None
    return_temp: float | None
    outdoor_temp: float | None
    target_flow_temp: float
    max_demand: float
    cooldown_active: bool
    away_mode_active: bool
    zones: dict[str, "ZoneData"]

class ZoneData(TypedDict):
    setpoint: float
    current_temp: float | None
    demand: float
    window_open: bool
```

**Changes to all files:**
- Replace `Any` with specific types
- `ZoneState.schedule_reader: ScheduleReader | None`
- Add proper return type annotations to all methods

**Add `pyproject.toml` mypy config:**

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true

[[tool.mypy.overrides]]
module = "homeassistant.*"
ignore_missing_imports = true
```

**Tag:** `v2026.01.184`

---

## Refactoring 3: Manifest & Documentation

**Problem:** Incomplete manifest, missing documentation.

**Update `manifest.json`:**

```json
{
  "domain": "heating_pid",
  "name": "EMS Zone Master",
  "codeowners": ["@your-github-username"],
  "config_flow": true,
  "documentation": "https://github.com/your-username/heating_pid/blob/main/README.md",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/your-username/heating_pid/issues",
  "version": "1.0.0",
  "requirements": [],
  "dependencies": []
}
```

**Create `README.md`** with:
- Feature list
- Installation instructions
- Configuration guide
- Services documentation
- Entity documentation

**Create `CHANGELOG.md`** with version history.

**Tag:** `v2026.01.185`

---

## Refactoring 4: Persist PID Tuning

**Problem:** PID gains tuned via number entities reset on restart.

**Changes to `store.py`:**

```python
class EmsZoneMasterStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._data: dict[str, Any] = {
            "pid_integrals": {},
            "warmup_factors": {},
            "manual_setpoints": {},
            "pid_gains": {},  # New: {zone_name: {kp, ki, kd, ke}}
        }

    def get_pid_gains(self, zone_name: str) -> dict[str, float] | None:
        return self._data.get("pid_gains", {}).get(zone_name)

    def set_pid_gains(self, zone_name: str, kp: float, ki: float, kd: float, ke: float) -> None:
        if "pid_gains" not in self._data:
            self._data["pid_gains"] = {}
        self._data["pid_gains"][zone_name] = {"kp": kp, "ki": ki, "kd": kd, "ke": ke}
```

**Changes to `coordinator.py` (_init_zones):**

```python
stored_gains = self.store.get_pid_gains(name)
if stored_gains is not None:
    pid.kp = stored_gains["kp"]
    pid.ki = stored_gains["ki"]
    pid.kd = stored_gains["kd"]
    pid.ke = stored_gains["ke"]
```

**Changes to `number.py`:**

```python
async def async_set_native_value(self, value: float) -> None:
    setattr(self._zone.pid, self._gain_attr, value)
    self.coordinator.store.set_pid_gains(
        self._zone_name,
        self._zone.pid.kp,
        self._zone.pid.ki,
        self._zone.pid.kd,
        self._zone.pid.ke,
    )
```

**Tag:** `v2026.01.186`

---

## Refactoring 5: Configuration Validation

**Problem:** Deleted helper entities cause errors and unpredictable behavior.

**Changes to `__init__.py`:**

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Validate core entities
    missing_core = []
    for key, name in [
        (CONF_HEATER_ENTITY, "Heater"),
        (CONF_FLOW_TEMP_ENTITY, "Flow Temperature"),
        (CONF_RETURN_TEMP_ENTITY, "Return Temperature"),
        (CONF_OUTDOOR_TEMP_ENTITY, "Outdoor Temperature"),
    ]:
        entity_id = entry.data.get(key)
        if entity_id and hass.states.get(entity_id) is None:
            missing_core.append(f"{name}: {entity_id}")

    if missing_core:
        notify(hass, f"Missing entities:\n- " + "\n- ".join(missing_core),
               title="EMS Zone Master - Configuration Error",
               notification_id=f"{DOMAIN}_config_error")
        raise ConfigEntryNotReady(f"Missing required entities")

    # Validate zone entities after coordinator init
    disabled_zones = await _validate_zone_entities(hass, entry, coordinator)

    if disabled_zones:
        notify(hass, f"Zones disabled:\n" +
               "\n".join(f"- {z['zone']}: {z['missing']}" for z in disabled_zones),
               title="EMS Zone Master - Zone Warning",
               notification_id=f"{DOMAIN}_zone_warning")
```

**Changes to `coordinator.py` (ZoneState):**

```python
self.disabled: bool = False
self.disabled_reason: str | None = None
```

**Tag:** `v2026.01.187`

---

## Refactoring 6: Service Calls

**Problem:** No easy way to reset learned parameters.

**New file: `services.yaml`**

```yaml
reset_zone_learning:
  name: Reset Zone Learning
  description: Reset the learned warmup factor for a zone
  fields:
    zone_name:
      name: Zone Name
      description: Name of zone (empty for all)
      required: false
      selector:
        text:

reset_zone_pid:
  name: Reset Zone PID
  description: Reset the PID integral term
  fields:
    zone_name:
      name: Zone Name
      required: false
      selector:
        text:

force_valve_maintenance:
  name: Force Valve Maintenance
  description: Trigger immediate valve maintenance cycle
  fields:
    zone_name:
      name: Zone Name
      required: true
      selector:
        text:

clear_manual_setpoint:
  name: Clear Manual Setpoint
  description: Clear manual override and return to schedule
  fields:
    zone_name:
      name: Zone Name
      required: false
      selector:
        text:
```

**Changes to `__init__.py`:**
- Register service handlers in `async_setup_entry`
- Unregister services in `async_unload_entry`

**Tag:** `v2026.01.188`

---

## Refactoring 7: Decompose Coordinator

**Problem:** `coordinator.py` is ~900 lines handling too many responsibilities.

**New file: `valve_manager.py`**

```python
class ValveManager:
    """Handles valve control, anti-cycling, and maintenance."""

    def __init__(self, hass: HomeAssistant, min_on_time: int, min_off_time: int) -> None:
        ...

    async def set_valve_state(self, zone: ZoneState, should_open: bool) -> bool:
        """Control valve with anti-cycling protection."""

    async def perform_maintenance(self, zone: ZoneState, duration: int) -> None:
        """Cycle valve briefly to prevent seizing."""

    def check_maintenance_needed(self, zone: ZoneState, now: datetime) -> bool:
        """Check if valve needs maintenance cycling."""
```

**New file: `heater_controller.py`**

```python
class HeaterController:
    """Manages heater flow temperature based on demand."""

    def __init__(self, hass: HomeAssistant, heater_entity_id: str,
                 min_egress: float, max_egress: float, min_ignition_level: float) -> None:
        ...

    def calculate_target_flow_temp(self, max_demand: float,
                                    effective_max: float, cooldown_active: bool) -> float:
        """Calculate target flow temperature from demand curve."""

    async def set_flow_temperature(self, temperature: float) -> bool:
        """Set heater flow temperature."""

    def check_cooldown(self, flow_temp: float, return_temp: float,
                       heater_was_active: bool) -> bool:
        """Check if cooldown mode should be active."""
```

**New file: `zone_logic.py`**

```python
class ZoneLogic:
    """Handles setpoint calculation and adaptive start."""

    @staticmethod
    def calculate_effective_setpoint(zone: ZoneState, now: datetime,
                                      away_mode: bool, solar_power: float | None,
                                      solar_threshold: float) -> float:
        """Calculate effective setpoint with all modifiers."""

    @staticmethod
    def check_adaptive_start(zone: ZoneState, now: datetime) -> bool:
        """Check if adaptive start preheating should begin."""

    @staticmethod
    def check_manual_setpoint_expiration(zone: ZoneState, now: datetime) -> bool:
        """Check if manual setpoint should be cleared."""
```

**Simplified `coordinator.py`:**

```python
class EmsZoneMasterCoordinator(DataUpdateCoordinator):
    def __init__(self, ...):
        self._valve_manager = ValveManager(hass, min_on_time, min_off_time)
        self._heater_controller = HeaterController(hass, heater_entity_id, ...)

    async def _async_update_data(self) -> dict[str, Any]:
        await self._read_sensor_states()
        self._update_away_mode(now)

        for zone in self.zones.values():
            ZoneLogic.check_manual_setpoint_expiration(zone, now)
            zone.setpoint = ZoneLogic.calculate_effective_setpoint(zone, now, ...)
            zone.demand = zone.pid.update(...)

        target = self._heater_controller.calculate_target_flow_temp(...)
        await self._heater_controller.set_flow_temperature(target)

        for zone in self.zones.values():
            await self._valve_manager.set_valve_state(zone, zone.demand > 0)
```

**Tag:** `v2026.01.189`

---

## Refactoring 8: Event-Driven Updates

**Problem:** 30s polling means delayed reaction to state changes.

**Debounce configuration:**

| State Change | Delay |
|--------------|-------|
| Window opens | 30s |
| Window closes | 30s |
| Manual setpoint | 5s |
| Presence lost | Configurable (default 30 min) |
| Presence returns | Instant |

**New file: `state_debouncer.py`**

```python
@dataclass
class PendingChange:
    new_state: str
    detected_at: datetime
    delay_seconds: float
    callback: Callable[[], Awaitable[None]]
    cancel_timer: Callable[[], None] | None = None

class StateDebouncer:
    """Manages debounced state change reactions."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._pending: dict[str, PendingChange] = {}
        self._unsub_listeners: list[Callable[[], None]] = []

    def track_entity(self, entity_id: str, delay_seconds: float,
                     on_confirmed: Callable[[str], Awaitable[None]]) -> None:
        """Start tracking an entity for debounced state changes."""

    def shutdown(self) -> None:
        """Cancel all pending changes and listeners."""
```

**Integration with coordinator:**

```python
class EmsZoneMasterCoordinator:
    def __init__(self, ...):
        self._debouncer = StateDebouncer(hass)

        # Track window sensors (30s debounce)
        for zone in self.zones.values():
            if zone.window_entity_id:
                self._debouncer.track_entity(
                    zone.window_entity_id,
                    delay_seconds=30.0,
                    on_confirmed=lambda state, z=zone: self._on_window_change(z, state)
                )

    async def _on_window_change(self, zone: ZoneState, state: str) -> None:
        zone.window_open = state == "on"
        await self._update_single_zone(zone)

    async def _update_single_zone(self, zone: ZoneState) -> None:
        """Partial update for a single zone (no full PID cycle)."""
```

**Tag:** `v2026.01.1810`

---

## Implementation Order Summary

| Step | Refactoring | Tag |
|------|-------------|-----|
| 1 | Import organization | `v2026.01.183` |
| 2 | Type safety | `v2026.01.184` |
| 3 | Manifest & documentation | `v2026.01.185` |
| 4 | Persist PID tuning | `v2026.01.186` |
| 5 | Configuration validation | `v2026.01.187` |
| 6 | Service calls | `v2026.01.188` |
| 7 | Decompose coordinator | `v2026.01.189` |
| 8 | Event-driven updates | `v2026.01.1810` |

## Files Changed Summary

| File | Status |
|------|--------|
| `types.py` | New |
| `valve_manager.py` | New |
| `heater_controller.py` | New |
| `zone_logic.py` | New |
| `state_debouncer.py` | New |
| `services.yaml` | New |
| `README.md` | New |
| `CHANGELOG.md` | New |
| `pyproject.toml` | New (mypy config) |
| `coordinator.py` | Major refactor |
| `__init__.py` | Services, validation |
| `store.py` | PID gains |
| `number.py` | Persist gains |
| `climate.py` | Debounce integration |
| `manifest.json` | Update metadata |
| All `.py` files | Import cleanup, type annotations |
