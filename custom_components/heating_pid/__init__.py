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
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import EmsZoneMasterCoordinator
from .store import EmsZoneMasterStore

_LOGGER = logging.getLogger(__name__)

type EmsZoneMasterConfigEntry = ConfigEntry[EmsZoneMasterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: EmsZoneMasterConfigEntry) -> bool:
    """Set up EMS Zone Master from a config entry.

    This function initializes the integration by:
    1. Creating the persistence store
    2. Loading stored state (warmup factors, PID integrals)
    3. Creating the data coordinator
    4. Starting the coordinator's first refresh
    5. Setting up all platforms (climate, sensor, number, binary_sensor)

    Args:
        hass: Home Assistant instance
        entry: Config entry containing integration configuration

    Returns:
        True if setup was successful, False otherwise
    """
    _LOGGER.debug("Setting up EMS Zone Master entry: %s", entry.entry_id)

    # Initialize the persistence store
    store = EmsZoneMasterStore(hass)
    await store.async_load()

    # Create and initialize the coordinator
    coordinator = EmsZoneMasterCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime data
    entry.runtime_data = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

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
