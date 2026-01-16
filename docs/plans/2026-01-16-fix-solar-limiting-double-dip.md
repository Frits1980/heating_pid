# Fix Solar Limiting Double-Dip Bug

**Date:** 2026-01-16
**Status:** Ready for implementation

---

## Problem Statement

Solar limiting is applied twice, causing under-heating when solar power exceeds the threshold:

1. **Zone level (correct):** Reduces PID setpoint by `solar_drop` → PID outputs lower demand
2. **Global level (bug):** Further reduces that demand by `(solar_power - threshold) / 100`

The second layer uses an arbitrary formula and compounds the effect unnecessarily.

## Solution

Remove Layer 2 entirely. The zone-level approach is sufficient and configurable:
- Uses `zone.solar_drop` if set, else falls back to `self._solar_drop` (global)
- UI temperature remains unchanged (good UX)
- PID naturally reduces demand based on the internally-lowered setpoint

---

## Code Changes

**File:** `custom_components/heating_pid/coordinator.py`

### Task 1: Remove solar limiting block from `_update_heater_control`

Delete lines 860-879 (the entire solar limiting block):

```python
# DELETE THIS BLOCK:
# Apply solar limiting if threshold exceeded
effective_demand = self._max_demand
if (
    self._solar_power is not None
    and self._solar_power > self._solar_threshold
    and effective_demand > 0
):
    # Reduce demand based on solar excess
    solar_reduction = min(
        effective_demand,
        (self._solar_power - self._solar_threshold) / 100,
    )
    effective_demand = max(0, effective_demand - solar_reduction)
    _LOGGER.debug(
        "Solar limiting: %.0fW > %.0fW threshold, demand reduced to %.1f%%",
        self._solar_power,
        self._solar_threshold,
        effective_demand,
    )
```

### Task 2: Update references to use `self._max_demand` directly

After removing the block, change remaining references from `effective_demand` to `self._max_demand`:
- Flow temperature calculation
- Debug logging

---

## Testing & Verification

**How to verify the fix works:**

1. Set a zone with `solar_drop = 5°C` and threshold at a value your system exceeds
2. Observe in logs: only one "solar limiting" debug message per zone (from `_update_zone_demands`)
3. Confirm UI target temperature stays at user-set value
4. Confirm PID demand reflects the reduced setpoint (lower demand when solar active)

**What should NOT happen anymore:**
- No "Solar limiting: ...demand reduced to..." log from `_update_heater_control`
- No double-reduction of heating output

---

## Files Affected

| File | Change |
|------|--------|
| `coordinator.py` | Remove solar limiting block from `_update_heater_control` |

**No other files affected** - zone-level logic stays as-is.
