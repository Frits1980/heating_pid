"""Binary sensor entities for EMS Zone Master.

Provides binary sensors for:
- Cooldown indicator: Shows when efficiency cooldown is active
- Per-zone window state: Shows window open/closed state
- Per-zone heating active: Shows if zone is actively heating
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MIN_EFFICIENT_DELTA_T

if TYPE_CHECKING:
    from .coordinator import EmsZoneMasterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities for EMS Zone Master.

    Creates:
    - One cooldown indicator sensor (global)
    - One window sensor per zone (mirrors window entity state)
    - One heating indicator per zone

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: EmsZoneMasterCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = []

    # Global cooldown sensor
    entities.append(CooldownIndicator(coordinator))

    # Per-zone sensors
    for zone_name, zone in coordinator.zones.items():
        entities.append(ZoneHeatingIndicator(coordinator, zone_name))

        # Only add window sensor if zone has a window entity configured
        if zone.window_entity_id:
            entities.append(ZoneWindowSensor(coordinator, zone_name))

    async_add_entities(entities)
    _LOGGER.debug("Added %d binary sensor entities", len(entities))


class CooldownIndicator(CoordinatorEntity["EmsZoneMasterCoordinator"], BinarySensorEntity):
    """Binary sensor indicating efficiency cooldown mode.

    Cooldown mode activates when the delta-T (flow temp - return temp)
    drops below the efficiency threshold. This indicates the heating
    system is not running efficiently and should pause.

    When cooldown is active:
    - Heater is turned off
    - Zones continue to be monitored
    - Heating resumes when delta-T recovers

    Attributes:
        _attr_device_class: RUNNING - sensor is "on" when cooldown is active
    """

    _attr_has_entity_name = True
    _attr_name = "Cooldown Active"
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: EmsZoneMasterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_cooldown"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        """Return True if cooldown mode is active."""
        return self.coordinator.cooldown_active

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Return additional cooldown information."""
        data = self.coordinator.data or {}
        flow_temp = data.get("flow_temp")
        return_temp = data.get("return_temp")

        delta_t = None
        if flow_temp is not None and return_temp is not None:
            delta_t = flow_temp - return_temp

        return {
            "delta_t": round(delta_t, 1) if delta_t is not None else None,
            "threshold": MIN_EFFICIENT_DELTA_T,
            "flow_temp": flow_temp,
            "return_temp": return_temp,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class ZoneHeatingIndicator(CoordinatorEntity["EmsZoneMasterCoordinator"], BinarySensorEntity):
    """Binary sensor indicating if a zone is actively heating.

    Shows "on" when the zone has demand > 0 and its valve is open.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_icon = "mdi:radiator"

    def __init__(
        self,
        coordinator: EmsZoneMasterCoordinator,
        zone_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._zone_name = zone_name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone_name}_heating"
        self._attr_name = "Heating"
        self._attr_device_info = coordinator.get_zone_device_info(zone_name)

    @property
    def is_on(self) -> bool:
        """Return True if zone is actively heating."""
        zone = self.coordinator.zones[self._zone_name]
        return zone.demand > 0

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        """Return zone heating details."""
        zone = self.coordinator.zones[self._zone_name]
        return {
            "demand": round(zone.demand, 1),
            "setpoint": zone.setpoint,
            "current_temp": zone.current_temp,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class ZoneWindowSensor(CoordinatorEntity["EmsZoneMasterCoordinator"], BinarySensorEntity):
    """Binary sensor mirroring window state for a zone.

    This sensor reflects whether the zone's configured window
    sensor detects an open window. When the window is open:
    - Zone setpoint is reduced by WINDOW_DROP
    - Heating continues at reduced level

    Attributes:
        _zone_name: Zone this sensor belongs to
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_icon = "mdi:window-open-variant"

    def __init__(
        self,
        coordinator: EmsZoneMasterCoordinator,
        zone_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._zone_name = zone_name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone_name}_window"
        self._attr_name = "Window"
        self._attr_device_info = coordinator.get_zone_device_info(zone_name)

    @property
    def is_on(self) -> bool:
        """Return True if window is open."""
        zone = self.coordinator.zones[self._zone_name]
        return zone.window_open

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return window sensor source."""
        zone = self.coordinator.zones[self._zone_name]
        return {
            "source_entity": zone.window_entity_id,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
