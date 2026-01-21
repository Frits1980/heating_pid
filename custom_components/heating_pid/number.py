"""Number entities for live PID tuning.

Provides number entities for each zone to allow real-time adjustment
of PID controller gains:
- Kp (Proportional gain)
- Ki (Integral gain)
- Kd (Derivative gain)
- Ke (Outdoor compensation gain)

These entities allow fine-tuning the heating response without
modifying the integration configuration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_KD,
    CONF_KE,
    CONF_KI,
    CONF_KP,
    DEFAULT_KD,
    DEFAULT_KE,
    DEFAULT_KI,
    DEFAULT_KP,
    DOMAIN,
)

if TYPE_CHECKING:
    from .coordinator import EmsZoneMasterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for PID tuning.

    Creates four number entities per zone:
    - Kp, Ki, Kd, Ke

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: EmsZoneMasterCoordinator = entry.runtime_data

    entities: list[NumberEntity] = []

    for zone_name in coordinator.zones:
        entities.extend([
            PIDGainNumber(coordinator, zone_name, "kp", DEFAULT_KP, 0, 100, 0.5),
            PIDGainNumber(coordinator, zone_name, "ki", DEFAULT_KI, 0, 2, 0.01),
            PIDGainNumber(coordinator, zone_name, "kd", DEFAULT_KD, 0, 500, 5),
            PIDGainNumber(coordinator, zone_name, "ke", DEFAULT_KE, 0, 0.2, 0.005),
        ])

    async_add_entities(entities)
    _LOGGER.debug("Added %d PID tuning number entities", len(entities))


class PIDGainNumber(CoordinatorEntity["EmsZoneMasterCoordinator"], NumberEntity):
    """Number entity for adjusting a PID gain parameter.

    Allows real-time adjustment of PID controller gains for a zone.
    Changes take effect immediately and are used in the next
    coordinator update cycle.

    Attributes:
        _zone_name: Zone this gain belongs to
        _gain_name: Name of the gain (kp, ki, kd, ke)
    """

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    # Gain configuration mapping
    GAIN_CONFIG = {
        "kp": {
            "name": "Kp (Proportional)",
            "icon": "mdi:alpha-p-box",
            "description": "Proportional gain - how aggressively to respond to current error",
        },
        "ki": {
            "name": "Ki (Integral)",
            "icon": "mdi:alpha-i-box",
            "description": "Integral gain - how much to compensate for accumulated error",
        },
        "kd": {
            "name": "Kd (Derivative)",
            "icon": "mdi:alpha-d-box",
            "description": "Derivative gain - how much to dampen rapid changes",
        },
        "ke": {
            "name": "Ke (Outdoor)",
            "icon": "mdi:thermometer-lines",
            "description": "Outdoor compensation gain - boost output when cold outside",
        },
    }

    def __init__(
        self,
        coordinator: EmsZoneMasterCoordinator,
        zone_name: str,
        gain_name: str,
        default: float,
        min_value: float,
        max_value: float,
        step: float,
    ) -> None:
        """Initialize the number entity.

        Args:
            coordinator: Data coordinator
            zone_name: Name of the zone
            gain_name: Name of the gain (kp, ki, kd, ke)
            default: Default value
            min_value: Minimum allowed value
            max_value: Maximum allowed value
            step: Step size for adjustments
        """
        super().__init__(coordinator)
        self._zone_name = zone_name
        self._gain_name = gain_name

        config = self.GAIN_CONFIG[gain_name]
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone_name}_{gain_name}"
        self._attr_name = config["name"]
        self._attr_icon = config["icon"]
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_device_info = coordinator.get_zone_device_info(zone_name)

    @property
    def native_value(self) -> float:
        """Return current gain value from the PID controller."""
        zone = self.coordinator.zones[self._zone_name]
        return getattr(zone.pid, self._gain_name)

    async def async_set_native_value(self, value: float) -> None:
        """Update the gain value.

        Args:
            value: New gain value
        """
        zone = self.coordinator.zones[self._zone_name]

        _LOGGER.info(
            "Setting %s %s to %.4f",
            self._zone_name,
            self._gain_name,
            value,
        )

        # Update the PID controller
        zone.pid.set_gains(**{self._gain_name: value})

        # Persist all gains for this zone
        self.coordinator.store.set_pid_gains(
            self._zone_name,
            zone.pid.kp,
            zone.pid.ki,
            zone.pid.kd,
            zone.pid.ke,
        )
        # Trigger immediate save
        await self.coordinator.store.async_save()

        # Trigger state update
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return additional attributes."""
        config = self.GAIN_CONFIG[self._gain_name]
        return {
            "description": config["description"],
            "zone": self._zone_name,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
