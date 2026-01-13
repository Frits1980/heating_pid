# Zone Management Design

**Date:** 2025-01-13
**Issues:** #1, #2, #3

## Problem

Users cannot edit or delete zones after the initial setup wizard completes.

## Solution

Add a "Manage Zones" menu to the options flow that allows editing and deleting existing zones.

## Menu Structure

```
Options (cogwheel)
├── Global Settings        (existing)
├── Add Zone              (existing)
└── Manage Zones          (NEW)
    └── Select zone dropdown
        ├── Edit Zone
        └── Delete Zone → Confirm
```

## New Options Flow Steps

### async_step_manage_zones
- Shows dropdown of existing zones
- Stores selected zone in `_selected_zone` instance variable
- Proceeds to zone_action step

### async_step_zone_action
- Shows menu: Edit Zone / Delete Zone
- Uses `{zone_name}` placeholder in title

### async_step_delete_zone
- Confirmation checkbox
- On confirm: removes zone from config, reloads integration
- Associated entities automatically removed on reload

### async_step_edit_zone
- Pre-fills form with zone's current values
- Same fields as add_zone: temp sensor, valve, window sensor, schedule, PID gains
- On save: updates zone in config, reloads integration

## State Tracking

```python
class EmsZoneMasterOptionsFlow(OptionsFlow):
    _selected_zone: str | None = None
```

## Files Changed

| File | Changes |
|------|---------|
| config_flow.py | Add 4 new async steps |
| strings.json | Add translations for new steps |
| translations/en.json | Same translations |

## Issue Coverage

- **#1** (modify sensors): Solved by edit_zone step
- **#2** (delete zone): Solved by delete_zone step
- **#3** (documentation): Already addressed by CONFIG.md
