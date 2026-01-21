"""EMS Zone Master integration for Home Assistant.

This integration provides modulating heating control via EMS-ESP with:
- Multi-zone temperature management
- PID-based demand calculation
- Adaptive start learning
- Efficiency optimizations

The control method modulates boiler flow temperature based on aggregated
zone demand rather than simple on/off control.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.components.persistent_notification import async_create as async_notify

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_HEATER_ENTITY,
    CONF_FLOW_TEMP_ENTITY,
    CONF_RETURN_TEMP_ENTITY,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_ZONE_TEMP_ENTITY,
    CONF_ZONE_VALVE_ENTITY,
    CONF_ZONE_WINDOW_ENTITY,
    CONF_ZONE_SCHEDULE_ENTITY,
    CONF_ZONE_NAME,
    CONF_ZONES,
    VALVE_MAINTENANCE_DURATION,
)
from .coordinator import EmsZoneMasterCoordinator
from .store import EmsZoneMasterStore

_LOGGER = logging.getLogger(__name__)

type EmsZoneMasterConfigEntry = ConfigEntry[EmsZoneMasterCoordinator]


async def _handle_reset_zone_learning(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle reset_zone_learning service call.

    Args:
        hass: Home Assistant instance
        call: Service call with optional zone_name parameter

    Returns:
        Service response
    """
    zone_name = call.data.get("zone_name")

    # Get all entries and find coordinators
    entries: list[EmsZoneMasterConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state.loaded  # type: ignore
    ]

    reset_count = 0
    for entry in entries:
        coordinator: EmsZoneMasterCoordinator = entry.runtime_data
        if zone_name:
            # Reset specific zone
            if zone_name in coordinator.zones:
                coordinator.zones[zone_name].warmup_factor = 30.0
                coordinator.store.set_warmup_factor(zone_name, 30.0)
                reset_count += 1
                _LOGGER.info("Reset warmup factor for zone: %s", zone_name)
            else:
                _LOGGER.warning("Zone not found: %s", zone_name)
        else:
            # Reset all zones
            for name in coordinator.zones:
                coordinator.zones[name].warmup_factor = 30.0
                coordinator.store.set_warmup_factor(name, 30.0)
                reset_count += 1
            _LOGGER.info("Reset warmup factor for all zones in entry: %s", entry.entry_id)

    # Persist changes
    for entry in entries:
        await entry.runtime_data.store.async_save()

    _LOGGER.info("Reset learning for %d zones", reset_count)
    return {}


async def _handle_reset_zone_pid(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle reset_zone_pid service call.

    Args:
        hass: Home Assistant instance
        call: Service call with optional zone_name parameter

    Returns:
        Service response
    """
    zone_name = call.data.get("zone_name")

    # Get all entries and find coordinators
    entries: list[EmsZoneMasterConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state.loaded  # type: ignore
    ]

    reset_count = 0
    for entry in entries:
        coordinator: EmsZoneMasterCoordinator = entry.runtime_data
        if zone_name:
            # Reset specific zone
            if zone_name in coordinator.zones:
                coordinator.zones[zone_name].pid.integral = 0.0
                coordinator.store.set_pid_integral(zone_name, 0.0)
                reset_count += 1
                _LOGGER.info("Reset PID integral for zone: %s", zone_name)
            else:
                _LOGGER.warning("Zone not found: %s", zone_name)
        else:
            # Reset all zones
            for name in coordinator.zones:
                coordinator.zones[name].pid.integral = 0.0
                coordinator.store.set_pid_integral(name, 0.0)
                reset_count += 1
            _LOGGER.info("Reset PID integral for all zones in entry: %s", entry.entry_id)

    # Persist changes
    for entry in entries:
        await entry.runtime_data.store.async_save()

    _LOGGER.info("Reset PID for %d zones", reset_count)
    return {}


async def _handle_force_valve_maintenance(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle force_valve_maintenance service call.

    Args:
        hass: Home Assistant instance
        call: Service call with required zone_name parameter

    Returns:
        Service response
    """
    zone_name = call.data.get("zone_name")

    if not zone_name:
        _LOGGER.error("force_valve_maintenance requires zone_name")
        return {}

    # Find the zone
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state.loaded and zone_name in entry.runtime_data.zones:  # type: ignore
            coordinator: EmsZoneMasterCoordinator = entry.runtime_data
            zone = coordinator.zones[zone_name]

            # Trigger maintenance
            zone.valve_maintenance_pending = True
            _LOGGER.info("Forced valve maintenance for zone: %s", zone_name)

            # Trigger maintenance cycle with default duration
            await coordinator._perform_valve_maintenance(zone, VALVE_MAINTENANCE_DURATION)
            return {}

    _LOGGER.error("Zone not found: %s", zone_name)
    return {}


async def _handle_clear_manual_setpoint(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle clear_manual_setpoint service call.

    Args:
        hass: Home Assistant instance
        call: Service call with optional zone_name parameter

    Returns:
        Service response
    """
    zone_name = call.data.get("zone_name")

    # Get all entries and find coordinators
    entries: list[EmsZoneMasterConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state.loaded  # type: ignore
    ]

    cleared_count = 0
    for entry in entries:
        coordinator: EmsZoneMasterCoordinator = entry.runtime_data
        if zone_name:
            # Clear specific zone
            if zone_name in coordinator.zones:
                coordinator.zones[zone_name].manual_setpoint = None
                coordinator.zones[zone_name].manual_setpoint_schedule_state = None
                coordinator.store.set_manual_setpoint(zone_name, None)
                cleared_count += 1
                _LOGGER.info("Cleared manual setpoint for zone: %s", zone_name)
            else:
                _LOGGER.warning("Zone not found: %s", zone_name)
        else:
            # Clear all zones
            for name in coordinator.zones:
                coordinator.zones[name].manual_setpoint = None
                coordinator.zones[name].manual_setpoint_schedule_state = None
                coordinator.store.set_manual_setpoint(name, None)
                cleared_count += 1
            _LOGGER.info("Cleared manual setpoint for all zones in entry: %s", entry.entry_id)

    # Persist changes
    for entry in entries:
        await entry.runtime_data.store.async_save()

    _LOGGER.info("Cleared manual setpoint for %d zones", cleared_count)
    return {}


async def _validate_core_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[str]:
    """Validate that core heater entities exist.

    Args:
        hass: Home Assistant instance
        entry: Config entry

    Returns:
        List of missing entity descriptions
    """
    missing = []

    for key, name in [
        (CONF_HEATER_ENTITY, "Heater"),
        (CONF_FLOW_TEMP_ENTITY, "Flow Temperature"),
        (CONF_RETURN_TEMP_ENTITY, "Return Temperature"),
        (CONF_OUTDOOR_TEMP_ENTITY, "Outdoor Temperature"),
    ]:
        entity_id = entry.data.get(key)
        if entity_id and hass.states.get(entity_id) is None:
            missing.append(f"{name}: {entity_id}")

    return missing


async def _validate_zone_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: EmsZoneMasterCoordinator
) -> list[dict[str, str]]:
    """Validate zone entities and disable zones with missing entities.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        coordinator: Data coordinator

    Returns:
        List of disabled zone info with 'zone' and 'missing' keys
    """
    disabled = []

    for zone_config in entry.data.get(CONF_ZONES, []):
        zone_name = zone_config[CONF_ZONE_NAME]
        missing_zone = []

        # Check required zone entities
        for key, name in [
            (CONF_ZONE_TEMP_ENTITY, "Temperature"),
            (CONF_ZONE_VALVE_ENTITY, "Valve"),
        ]:
            entity_id = zone_config.get(key)
            if entity_id and hass.states.get(entity_id) is None:
                missing_zone.append(f"{name}: {entity_id}")

        # Check optional zone entities
        for key, name in [
            (CONF_ZONE_WINDOW_ENTITY, "Window"),
            (CONF_ZONE_SCHEDULE_ENTITY, "Schedule"),
        ]:
            entity_id = zone_config.get(key)
            if entity_id and hass.states.get(entity_id) is None:
                missing_zone.append(f"{name}: {entity_id}")

        if missing_zone:
            zone = coordinator.zones.get(zone_name)
            if zone:
                zone.disabled = True
                zone.disabled_reason = f"Missing entities: {', '.join(missing_zone)}"
            disabled.append({"zone": zone_name, "missing": ", ".join(missing_zone)})

    return disabled


async def async_setup_entry(hass: HomeAssistant, entry: EmsZoneMasterConfigEntry) -> bool:
    """Set up EMS Zone Master from a config entry.

    This function initializes the integration by:
    1. Validating core entities exist
    2. Creating the persistence store
    3. Loading stored state (warmup factors, PID integrals)
    4. Creating the data coordinator
    5. Validating zone entities
    6. Starting the coordinator's first refresh
    7. Setting up all platforms (climate, sensor, number, binary_sensor)

    Args:
        hass: Home Assistant instance
        entry: Config entry containing integration configuration

    Returns:
        True if setup was successful, False otherwise
    """
    _LOGGER.debug("Setting up EMS Zone Master entry: %s", entry.entry_id)

    # Validate core entities
    missing_core = await _validate_core_entities(hass, entry)
    if missing_core:
        async_notify(
            hass,
            f"Missing required entities:\n- " + "\n- ".join(missing_core),
            title="EMS Zone Master - Configuration Error",
            notification_id=f"{DOMAIN}_{entry.entry_id}_config_error",
        )
        _LOGGER.error("Missing core entities: %s", missing_core)
        return False

    # Initialize the persistence store
    store = EmsZoneMasterStore(hass)
    await store.async_load()

    # Create and initialize the coordinator
    coordinator = EmsZoneMasterCoordinator(hass, entry, store)

    # Validate zone entities
    disabled_zones = await _validate_zone_entities(hass, entry, coordinator)

    if disabled_zones:
        zone_messages = "\n".join(
            f"- {z['zone']}: {z['missing']}" for z in disabled_zones
        )
        async_notify(
            hass,
            f"The following zones have been disabled due to missing entities:\n{zone_messages}",
            title="EMS Zone Master - Zone Warning",
            notification_id=f"{DOMAIN}_{entry.entry_id}_zone_warning",
        )
        _LOGGER.warning("Disabled zones due to missing entities: %s", disabled_zones)

    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime data
    entry.runtime_data = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register services (only once per domain)
    if DOMAIN not in hass.data.get("services_registered", []):
        hass.services.async_register(
            DOMAIN,
            "reset_zone_learning",
            _handle_reset_zone_learning,
        )
        hass.services.async_register(
            DOMAIN,
            "reset_zone_pid",
            _handle_reset_zone_pid,
        )
        hass.services.async_register(
            DOMAIN,
            "force_valve_maintenance",
            _handle_force_valve_maintenance,
        )
        hass.services.async_register(
            DOMAIN,
            "clear_manual_setpoint",
            _handle_clear_manual_setpoint,
        )
        hass.data.setdefault("services_registered", []).append(DOMAIN)

    _LOGGER.info("EMS Zone Master setup complete for entry: %s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EmsZoneMasterConfigEntry) -> bool:
    """Unload a config entry.

    This function tears down the integration by:
    1. Unloading all platforms
    2. Persisting current state to storage
    3. Cleaning up resources

    Args:
        hass: Home Assistant instance
        entry: Config entry being unloaded

    Returns:
        True if unload was successful, False otherwise
    """
    _LOGGER.debug("Unloading EMS Zone Master entry: %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Shutdown coordinator (cancels timers and persists state)
        coordinator: EmsZoneMasterCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
        _LOGGER.info("EMS Zone Master unloaded: %s", entry.entry_id)

    # Unregister services if this is the last entry
    remaining_entries = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.state.loaded and e.entry_id != entry.entry_id  # type: ignore
    ]
    if not remaining_entries:
        hass.services.async_remove(DOMAIN, "reset_zone_learning")
        hass.services.async_remove(DOMAIN, "reset_zone_pid")
        hass.services.async_remove(DOMAIN, "force_valve_maintenance")
        hass.services.async_remove(DOMAIN, "clear_manual_setpoint")
        hass.data.pop("services_registered", None)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: EmsZoneMasterConfigEntry) -> None:
    """Handle options update.

    Called when the user updates integration options via the UI.
    Reloads the config entry to apply changes.

    Args:
        hass: Home Assistant instance
        entry: Config entry with updated options
    """
    _LOGGER.debug("Options updated for EMS Zone Master: %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
