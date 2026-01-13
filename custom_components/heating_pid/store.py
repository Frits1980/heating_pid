"""Persistence store for EMS Zone Master.

Handles JSON storage of learned data in `.storage/heating_pid.json`:
- Warmup factors per zone (learned minutes per degree for adaptive start)
- PID integral values per zone (for bumpless transfer on restart)

The store is loaded on integration startup and saved periodically
(default: every 60 minutes) and on shutdown.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class EmsZoneMasterStore:
    """Persistence store for EMS Zone Master learned data.

    This class manages persistent storage of:
    - Warmup factors: Learned time per degree for each zone, used by
      adaptive start to begin heating at the right time
    - PID integrals: Accumulated integral values for bumpless transfer
      when the integration restarts

    Data is stored in Home Assistant's .storage directory as JSON.

    Attributes:
        hass: Home Assistant instance
        _store: HA storage helper
        _data: Current stored data dictionary
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store.

        Args:
            hass: Home Assistant instance
        """
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, Any] = {
            "warmup_factors": {},
            "pid_integrals": {},
            "manual_setpoints": {},
        }

    async def async_load(self) -> None:
        """Load stored data from disk.

        Called during integration setup to restore learned state.
        If no stored data exists, starts with empty defaults.
        """
        stored = await self._store.async_load()
        if stored:
            self._data = stored
            _LOGGER.debug(
                "Loaded EMS Zone Master store: %d warmup factors, %d PID integrals",
                len(self._data.get("warmup_factors", {})),
                len(self._data.get("pid_integrals", {})),
            )
        else:
            _LOGGER.debug("No stored data found, starting fresh")

    async def async_save(self) -> None:
        """Save current data to disk.

        Called periodically and on integration shutdown to persist
        learned warmup factors and PID integrals.
        """
        await self._store.async_save(self._data)
        _LOGGER.debug("Saved EMS Zone Master store")

    def get_warmup_factor(self, zone_name: str) -> float | None:
        """Get the stored warmup factor for a zone.

        Args:
            zone_name: Name of the zone

        Returns:
            Warmup factor in minutes per degree, or None if not stored
        """
        return self._data.get("warmup_factors", {}).get(zone_name)

    def set_warmup_factor(self, zone_name: str, factor: float) -> None:
        """Store a warmup factor for a zone.

        Args:
            zone_name: Name of the zone
            factor: Warmup factor in minutes per degree
        """
        if "warmup_factors" not in self._data:
            self._data["warmup_factors"] = {}
        self._data["warmup_factors"][zone_name] = factor
        _LOGGER.debug("Updated warmup factor for %s: %.2f min/°C", zone_name, factor)

    def get_pid_integral(self, zone_name: str) -> float | None:
        """Get the stored PID integral for a zone.

        Args:
            zone_name: Name of the zone

        Returns:
            PID integral value, or None if not stored
        """
        return self._data.get("pid_integrals", {}).get(zone_name)

    def set_pid_integral(self, zone_name: str, integral: float) -> None:
        """Store a PID integral for a zone.

        Args:
            zone_name: Name of the zone
            integral: PID integral value
        """
        if "pid_integrals" not in self._data:
            self._data["pid_integrals"] = {}
        self._data["pid_integrals"][zone_name] = integral

    def get_manual_setpoint(self, zone_name: str) -> float | None:
        """Get the stored manual setpoint for a zone.

        Args:
            zone_name: Name of the zone

        Returns:
            Manual setpoint temperature, or None if not stored/cleared
        """
        return self._data.get("manual_setpoints", {}).get(zone_name)

    def set_manual_setpoint(self, zone_name: str, setpoint: float | None) -> None:
        """Store or clear a manual setpoint for a zone.

        Args:
            zone_name: Name of the zone
            setpoint: Manual setpoint temperature, or None to clear
        """
        if "manual_setpoints" not in self._data:
            self._data["manual_setpoints"] = {}
        if setpoint is None:
            self._data["manual_setpoints"].pop(zone_name, None)
            _LOGGER.debug("Cleared manual setpoint for %s", zone_name)
        else:
            self._data["manual_setpoints"][zone_name] = setpoint
            _LOGGER.debug("Stored manual setpoint for %s: %.1f°C", zone_name, setpoint)

    def clear_zone(self, zone_name: str) -> None:
        """Clear all stored data for a zone.

        Used when a zone is removed from configuration.

        Args:
            zone_name: Name of the zone to clear
        """
        if "warmup_factors" in self._data:
            self._data["warmup_factors"].pop(zone_name, None)
        if "pid_integrals" in self._data:
            self._data["pid_integrals"].pop(zone_name, None)
        if "manual_setpoints" in self._data:
            self._data["manual_setpoints"].pop(zone_name, None)
        _LOGGER.debug("Cleared stored data for zone: %s", zone_name)

    def get_all_warmup_factors(self) -> dict[str, float]:
        """Get all stored warmup factors.

        Returns:
            Dictionary mapping zone names to warmup factors
        """
        return dict(self._data.get("warmup_factors", {}))

    def get_all_pid_integrals(self) -> dict[str, float]:
        """Get all stored PID integrals.

        Returns:
            Dictionary mapping zone names to PID integrals
        """
        return dict(self._data.get("pid_integrals", {}))
