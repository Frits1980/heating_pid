# Schedule Improvements and Quiet Mode Design

**Goal:** Fix schedule reading to use HA's `schedule.get_schedule` service for full schedule data, enabling proper adaptive start and a new quiet mode feature.

**Problem Solved:**
1. Schedule setpoints weren't being applied (HA doesn't expose weekday blocks in entity attributes)
2. Adaptive start couldn't determine next block's temperature
3. No way to limit flow temperature during early morning heating to avoid pipe noise

---

## Part 1: Schedule Reader Improvements

### Current Issue

Home Assistant schedule helpers expose via entity attributes:
- `state`: "on" or "off"
- `temp`: Current block's temperature (when on)
- `next_event`: Next transition datetime

But they **don't** expose the weekday block structure in attributes. We need to call the `schedule.get_schedule` service to get the full data.

### Solution

Add a method to call `schedule.get_schedule` service and cache the result. Use this to:
1. Get next block's temperature for adaptive start
2. Identify first block of day for quiet mode

### Implementation

**File:** `custom_components/heating_pid/schedule.py`

Add method to fetch full schedule:

```python
async def _fetch_full_schedule(self) -> dict[str, Any] | None:
    """Fetch full schedule data via schedule.get_schedule service.

    Returns:
        Full schedule with weekday blocks, or None if unavailable
    """
    try:
        response = await self.hass.services.async_call(
            "schedule",
            "get_schedule",
            {"entity_id": self.entity_id},
            blocking=True,
            return_response=True,
        )
        if response and self.entity_id in response:
            return response[self.entity_id]
    except Exception as err:
        _LOGGER.warning("Failed to fetch schedule data: %s", err)
    return None
```

Update `get_next_block_setpoint()` to use this data when schedule is off.

---

## Part 2: Quiet Mode Feature

### Purpose

Limit maximum flow temperature during the first heating block of each day, ramping up linearly to normal operation. This prevents pipe noise from rapid heating while occupants are still sleeping.

### New Global Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `quiet_mode_max_flow` | float | 0 (disabled) | Maximum flow temp during quiet mode (°C). Must be >= min_egress or 0 to disable. |
| `quiet_mode_ramp_minutes` | int | 60 | Time to ramp from quiet max to normal max (minutes) |

### Behavior

1. **First block detection:** The first schedule block that becomes active after midnight (00:00)
2. **Ramp calculation:** Linear interpolation from quiet_max to normal_max over ramp_minutes
3. **Cancellation:** As soon as the second block becomes active, quiet mode ends immediately

### Flow Temperature Calculation

```python
def get_effective_max_flow(self, now: datetime) -> float:
    """Get the effective maximum flow temperature, accounting for quiet mode."""
    if not self._is_quiet_mode_active(now):
        return self._max_egress

    # Calculate ramp progress (0.0 to 1.0)
    minutes_since_block_start = self._get_minutes_since_first_block_start(now)
    ramp_progress = min(1.0, minutes_since_block_start / self._quiet_mode_ramp_minutes)

    # Linear interpolation
    return self._quiet_mode_max_flow + ramp_progress * (self._max_egress - self._quiet_mode_max_flow)
```

### First Block Detection Logic

```python
def _is_first_block_of_day(self, now: datetime) -> bool:
    """Check if currently in the first schedule block of the day."""
    schedule_data = self._get_cached_schedule()
    if not schedule_data:
        return False

    day_name = WEEKDAY_NAMES[now.weekday()]
    day_blocks = schedule_data.get(day_name, [])

    if not day_blocks:
        return False

    # Sort blocks by start time to find first block
    sorted_blocks = sorted(day_blocks, key=lambda b: b.get("from", "99:99:99"))
    first_block = sorted_blocks[0]

    # Check if we're currently in this first block
    from_time = parse_time(first_block.get("from"))
    to_time = parse_time(first_block.get("to"))
    current_time = now.time()

    return from_time <= current_time < to_time
```

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| `quiet_mode_max_flow = 0` | Quiet mode disabled |
| `quiet_mode_max_flow < min_egress` | Clamp to min_egress |
| First block shorter than ramp time | Ramp completes when block ends |
| Schedule becomes off during ramp | Quiet mode ends (no heating anyway) |
| Second block starts | Quiet mode ends immediately, normal max flow |

---

## Part 3: Config Flow Changes

### Global Settings Step

Add to `async_step_global` and `async_step_global_settings`:

```python
vol.Optional(CONF_QUIET_MODE_MAX_FLOW, default=0): vol.All(
    vol.Coerce(float),
    vol.Range(min=0, max=60),
),
vol.Optional(CONF_QUIET_MODE_RAMP_MINUTES, default=60): vol.All(
    vol.Coerce(int),
    vol.Range(min=10, max=180),
),
```

### Strings/Translations

```json
"quiet_mode_max_flow": "Quiet Mode Max Flow Temperature",
"quiet_mode_ramp_minutes": "Quiet Mode Ramp-up Time",
```

```json
"quiet_mode_max_flow": "Maximum flow temperature during first heating block of the day. Set to 0 to disable quiet mode.",
"quiet_mode_ramp_minutes": "Minutes to gradually increase from quiet mode to normal max flow temperature."
```

---

## Part 4: Coordinator Changes

### New Properties

```python
self._quiet_mode_max_flow: float = entry.data.get(CONF_QUIET_MODE_MAX_FLOW, 0)
self._quiet_mode_ramp_minutes: int = entry.data.get(CONF_QUIET_MODE_RAMP_MINUTES, 60)
self._first_block_start_time: datetime | None = None  # Track when first block started
```

### Integration Points

1. In `_update_heater_control()`, replace `self._max_egress` with `self.get_effective_max_flow(now)` when calculating target flow temperature

2. Track first block start time when schedule transitions from off to on

3. Reset tracking at midnight or when entering second block

---

## Implementation Tasks

1. **schedule.py:** Add `_fetch_full_schedule()` method
2. **schedule.py:** Update `get_next_block_setpoint()` to use full schedule data
3. **schedule.py:** Add `get_first_block_of_day()` method
4. **const.py:** Add `CONF_QUIET_MODE_MAX_FLOW`, `CONF_QUIET_MODE_RAMP_MINUTES`
5. **config_flow.py:** Add quiet mode settings to global step
6. **strings.json / translations:** Add quiet mode labels and descriptions
7. **coordinator.py:** Add quiet mode state tracking
8. **coordinator.py:** Implement `get_effective_max_flow()` method
9. **coordinator.py:** Integrate quiet mode into heater control

---

## Testing Checklist

- [ ] Schedule setpoints now work correctly
- [ ] Adaptive start can determine next block temperature
- [ ] Quiet mode disabled when max_flow = 0
- [ ] Quiet mode activates on first block of day
- [ ] Flow temp ramps linearly over configured time
- [ ] Quiet mode ends when second block starts
- [ ] European comma decimals handled in schedule data
