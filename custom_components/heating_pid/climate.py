"""Climate entities for EMS Zone Master zones.

Each configured heating zone gets a climate entity that:
- Shows current temperature from the zone's sensor
- Allows setting target temperature (manual setpoint)
- Shows heating demand as a percentage
- Respects priority hierarchy (window > manual > schedule)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_DEMAND,
    ATTR_OUTDOOR_COMPENSATION,
    ATTR_PID_OUTPUT,
    ATTR_WARMUP_FACTOR,
    DEFAULT_WINDOW_DROP,
    DOMAIN,
)

if TYPE_CHECKING:
    from .coordinator import EmsZoneMasterCoordinator, ZoneState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities for EMS Zone Master.

    Creates one climate entity per configured zone.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: EmsZoneMasterCoordinator = entry.runtime_data

    entities = [
        EmsZoneClimate(coordinator, zone_name)
        for zone_name in coordinator.zones
    ]

    async_add_entities(entities)
    _LOGGER.debug("Added %d climate entities", len(entities))


class EmsZoneClimate(CoordinatorEntity["EmsZoneMasterCoordinator"], ClimateEntity):
    """Climate entity for a single EMS Zone Master zone.

    This entity represents one heating zone and provides:
    - Current temperature display from zone sensor
    - Target temperature control (setpoint)
    - HVAC mode (heat/off)
    - Current action (heating/idle)
    - Extra state attributes (demand, PID output, warmup factor)

    The priority hierarchy for setpoints is:
    1. Window open → setpoint reduced by WINDOW_DROP
    2. Manual setpoint → set via this entity, persists until next schedule event
    3. Schedule setpoint → from schedule helper entity
    4. Default setpoint → configured during setup

    Attributes:
        _zone_name: Name of this zone
        _attr_has_entity_name: Use device name as entity name prefix
    """

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0

    def __init__(
        self,
        coordinator: EmsZoneMasterCoordinator,
        zone_name: str,
    ) -> None:
        """Initialize the climate entity.

        Args:
            coordinator: Data coordinator
            zone_name: Name of the zone this entity represents
        """
        super().__init__(coordinator)
        self._zone_name = zone_name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone_name}_climate"
        self._attr_name = "Climate"
        self._attr_device_info = coordinator.get_zone_device_info(zone_name)

    @property
    def _zone(self) -> ZoneState:
        """Get the zone state object."""
        return self.coordinator.zones[self._zone_name]

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature from zone sensor."""
        return self._zone.current_temp

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature.

        Takes into account window state - if window is open,
        returns the reduced setpoint.
        """
        setpoint = self._zone.setpoint
        if self._zone.window_open:
            setpoint -= DEFAULT_WINDOW_DROP
        return setpoint

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode.

        Returns HEAT if zone has any demand, OFF otherwise.
        """
        if self._zone.demand > 0:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action.

        Returns:
            HEATING if demand > 0 and valve is open
            IDLE otherwise
        """
        if self._zone.demand > 0:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes.

        Provides diagnostic information:
        - demand: Current heating demand (0-100%)
        - pid_output: Raw PID controller output
        - warmup_factor: Learned minutes per degree
        - outdoor_compensation: Applied compensation factor
        - adaptive_start: Whether preheating is active
        - sync_forced: Whether zone was forced to start early
        """
        return {
            ATTR_DEMAND: round(self._zone.demand, 1),
            ATTR_PID_OUTPUT: round(self._zone.pid.last_output, 1),
            ATTR_WARMUP_FACTOR: round(self._zone.warmup_factor, 1),
            ATTR_OUTDOOR_COMPENSATION: self._zone.pid.ke,
            "window_open": self._zone.window_open,
            "manual_setpoint": self._zone.manual_setpoint,
            "adaptive_start": self._zone.adaptive_start_active,
            "sync_forced": self._zone.sync_forced,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature.

        This sets a manual setpoint that overrides the schedule
        until the next scheduled event.

        Args:
            **kwargs: Service call data containing ATTR_TEMPERATURE
        """
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        _LOGGER.info(
            "Setting manual temperature for %s: %.1f°C",
            self._zone_name,
            temperature,
        )

        # Set manual setpoint
        self._zone.manual_setpoint = temperature
        self._zone.setpoint = temperature

        # Store current schedule state for expiration tracking
        if self._zone.schedule_reader is not None:
            now = dt_util.now()
            self._zone.manual_setpoint_schedule_state = self._zone.schedule_reader.is_schedule_active(now)
        else:
            self._zone.manual_setpoint_schedule_state = None

        # Request coordinator update
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode.

        Currently supports:
        - HEAT: Enable zone (use scheduled/manual setpoint)
        - OFF: Disable zone (set demand to 0)

        Args:
            hvac_mode: Target HVAC mode
        """
        if hvac_mode == HVACMode.OFF:
            _LOGGER.info("Disabling zone: %s", self._zone_name)
            self._zone.demand = 0
            self._zone.pid.reset()
        elif hvac_mode == HVACMode.HEAT:
            _LOGGER.info("Enabling zone: %s", self._zone_name)
            # Zone will resume normal operation on next update

        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
