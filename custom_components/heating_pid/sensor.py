"""Sensor entities for EMS Zone Master.

Provides sensors for:
- Time to target: Estimated time for zone to reach setpoint
- Master status: Overall heating system state
- Flow temperature: Target flow temperature
- Total demand: Aggregated demand from all zones
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_TIME_TO_TARGET, DOMAIN

if TYPE_CHECKING:
    from .coordinator import EmsZoneMasterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for EMS Zone Master.

    Creates:
    - One time-to-target sensor per zone
    - One master status sensor
    - One target flow temperature sensor
    - One total demand sensor

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: EmsZoneMasterCoordinator = entry.runtime_data

    entities: list[SensorEntity] = []

    # Per-zone sensors
    for zone_name in coordinator.zones:
        entities.append(TimeToTargetSensor(coordinator, zone_name))

    # Global sensors
    entities.extend([
        MasterStatusSensor(coordinator),
        TargetFlowTempSensor(coordinator),
        TotalDemandSensor(coordinator),
    ])

    async_add_entities(entities)
    _LOGGER.debug("Added %d sensor entities", len(entities))


class TimeToTargetSensor(CoordinatorEntity["EmsZoneMasterCoordinator"], SensorEntity):
    """Sensor showing estimated time to reach target temperature.

    Uses the zone's learned warmup factor to estimate how long
    until the zone reaches its setpoint.

    The estimate is calculated as:
        time_to_target = (setpoint - current_temp) × warmup_factor

    Attributes:
        _zone_name: Name of the zone this sensor represents
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: EmsZoneMasterCoordinator,
        zone_name: str,
    ) -> None:
        """Initialize the sensor.

        Args:
            coordinator: Data coordinator
            zone_name: Name of the zone
        """
        super().__init__(coordinator)
        self._zone_name = zone_name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone_name}_time_to_target"
        self._attr_name = "Time to Target"
        self._attr_device_info = coordinator.get_zone_device_info(zone_name)

    @property
    def native_value(self) -> float | None:
        """Return estimated minutes to reach target temperature.

        Returns None if:
        - Current temperature is unknown
        - Zone is already at or above setpoint
        """
        zone = self.coordinator.zones[self._zone_name]

        if zone.current_temp is None:
            return None

        temp_delta = zone.setpoint - zone.current_temp

        if temp_delta <= 0:
            # Already at or above setpoint
            return 0

        # Estimate based on learned warmup factor
        return round(temp_delta * zone.warmup_factor, 0)

    @property
    def extra_state_attributes(self) -> dict[str, float | bool | None]:
        """Return additional attributes."""
        zone = self.coordinator.zones[self._zone_name]
        return {
            "warmup_factor": zone.warmup_factor,
            "setpoint": zone.setpoint,
            "current_temp": zone.current_temp,
            "adaptive_start": zone.adaptive_start_active,
            "sync_forced": zone.sync_forced,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class MasterStatusSensor(CoordinatorEntity["EmsZoneMasterCoordinator"], SensorEntity):
    """Sensor showing overall heating system status.

    Displays one of:
    - idle: No heating demand
    - heating: Active heating
    - cooldown: Efficiency cooldown mode
    - solar_limited: Reduced output due to solar power
    """

    _attr_has_entity_name = True
    _attr_name = "Master Status"
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: EmsZoneMasterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_master_status"
        self._attr_device_info = coordinator.device_info

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

    @property
    def extra_state_attributes(self) -> dict[str, float | bool]:
        """Return additional status information."""
        return {
            "max_demand": round(self.coordinator.max_demand, 1),
            "target_flow_temp": round(self.coordinator.target_flow_temp, 1),
            "cooldown_active": self.coordinator.cooldown_active,
            "solar_limited": self.coordinator.solar_limited,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class TargetFlowTempSensor(CoordinatorEntity["EmsZoneMasterCoordinator"], SensorEntity):
    """Sensor showing the target flow temperature.

    Displays the calculated flow temperature setpoint that will be
    sent to the heater based on the current demand.
    """

    _attr_has_entity_name = True
    _attr_name = "Target Flow Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:thermometer-water"

    def __init__(self, coordinator: EmsZoneMasterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_target_flow_temp"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        """Return target flow temperature."""
        return round(self.coordinator.target_flow_temp, 1)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class TotalDemandSensor(CoordinatorEntity["EmsZoneMasterCoordinator"], SensorEntity):
    """Sensor showing the total/maximum heating demand.

    Displays the highest demand value from all zones,
    which determines the target flow temperature.
    """

    _attr_has_entity_name = True
    _attr_name = "Total Demand"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: EmsZoneMasterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_total_demand"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float:
        """Return maximum demand across all zones."""
        return round(self.coordinator.max_demand, 0)

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        """Return per-zone demand breakdown."""
        return {
            f"{name}_demand": round(zone.demand, 1)
            for name, zone in self.coordinator.zones.items()
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
