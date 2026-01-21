"""Heater controller for EMS Zone Master.

Manages heater flow temperature based on aggregated zone demand.
"""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.core import HomeAssistant

from .const import MIN_EFFICIENT_DELTA_T

_LOGGER = logging.getLogger(__name__)


class HeaterController:
    """Manages heater flow temperature control.

    This class handles:
    - Calculating target flow temperature from demand curve
    - Setting the heater entity
    - Checking cooldown efficiency (delta-T)
    - Quiet mode flow limiting

    Attributes:
        hass: Home Assistant instance
        heater_entity_id: Heater control entity ID
        min_egress: Minimum flow temperature
        max_egress: Maximum flow temperature
        min_ignition_level: Minimum demand to activate burner
        quiet_mode_max_flow: Max flow during quiet mode
        quiet_mode_ramp_minutes: Time to ramp up from quiet mode
    """

    def __init__(
        self,
        hass: HomeAssistant,
        heater_entity_id: str,
        min_egress: float,
        max_egress: float,
        min_ignition_level: float,
        quiet_mode_max_flow: float = 0.0,
        quiet_mode_ramp_minutes: int = 60,
    ) -> None:
        """Initialize the heater controller.

        Args:
            hass: Home Assistant instance
            heater_entity_id: Heater control entity ID
            min_egress: Minimum flow temperature (°C)
            max_egress: Maximum flow temperature (°C)
            min_ignition_level: Minimum demand level to activate (%)
            quiet_mode_max_flow: Max flow temp during quiet mode (0 = disabled)
            quiet_mode_ramp_minutes: Time to ramp from quiet to normal (minutes)
        """
        self.hass = hass
        self._heater_entity_id = heater_entity_id
        self._min_egress = min_egress
        self._max_egress = max_egress
        self._min_ignition_level = min_ignition_level
        self._quiet_mode_max_flow = quiet_mode_max_flow
        self._quiet_mode_ramp_minutes = quiet_mode_ramp_minutes

        # Runtime state
        self._heater_was_active: bool = False
        self._cooldown_active: bool = False

    def calculate_target_flow_temp(
        self,
        max_demand: float,
        flow_temp: float | None,
        return_temp: float | None,
        quiet_mode_active: bool,
        first_block_start_time: datetime | None,
        now: datetime,
    ) -> tuple[float, bool]:
        """Calculate target flow temperature from demand curve.

        Args:
            max_demand: Maximum demand across all zones (0-100%)
            flow_temp: Current flow temperature
            return_temp: Current return temperature
            quiet_mode_active: Whether quiet mode is active
            first_block_start_time: When first heating block started today
            now: Current time

        Returns:
            Tuple of (target_temperature, cooldown_active)
        """
        # Check cooldown efficiency (delta-T too low = inefficient operation)
        cooldown_active = self._check_cooldown(
            flow_temp, return_temp, max_demand, self._heater_was_active
        )
        self._cooldown_active = cooldown_active

        # Calculate target flow temperature from demand curve
        # Formula: target = min + (demand / 100) × (effective_max - min)
        if max_demand < self._min_ignition_level or cooldown_active:
            # Below ignition threshold or in cooldown - turn off
            target_temp = 0.0
        else:
            effective_max = self._get_effective_max_flow(
                quiet_mode_active, first_block_start_time, now
            )
            target_temp = self._min_egress + (
                max_demand / 100.0
            ) * (effective_max - self._min_egress)

        _LOGGER.debug(
            "Heater control: demand=%.1f%%, target=%.1f°C, cooldown=%s",
            max_demand,
            target_temp,
            cooldown_active,
        )

        return target_temp, cooldown_active

    def _check_cooldown(
        self,
        flow_temp: float | None,
        return_temp: float | None,
        max_demand: float,
        heater_was_active: bool,
    ) -> bool:
        """Check if cooldown mode should be active.

        Cooldown activates when delta-T is too low while actively heating,
        indicating inefficient operation.

        Args:
            flow_temp: Current flow temperature
            return_temp: Current return temperature
            max_demand: Current demand level
            heater_was_active: Whether heater was active last cycle

        Returns:
            True if cooldown should be active
        """
        if flow_temp is None or return_temp is None:
            return False

        delta_t = flow_temp - return_temp
        boiler_is_responding = flow_temp >= self._min_egress

        if (
            heater_was_active
            and boiler_is_responding
            and delta_t < MIN_EFFICIENT_DELTA_T
            and max_demand > 0
        ):
            if not self._cooldown_active:
                _LOGGER.info(
                    "Entering cooldown mode: delta-T=%.1f°C < %.1f°C threshold",
                    delta_t,
                    MIN_EFFICIENT_DELTA_T,
                )
            return True
        else:
            if self._cooldown_active:
                _LOGGER.info("Exiting cooldown mode: delta-T=%.1f°C", delta_t)
            return False

    def _get_effective_max_flow(
        self,
        quiet_mode_active: bool,
        first_block_start_time: datetime | None,
        now: datetime,
    ) -> float:
        """Get the effective maximum flow temperature, accounting for quiet mode.

        Args:
            quiet_mode_active: Whether quiet mode is active
            first_block_start_time: When first heating block started
            now: Current time

        Returns:
            Maximum flow temperature, possibly reduced for quiet mode ramp
        """
        if not quiet_mode_active or first_block_start_time is None:
            return self._max_egress

        # Calculate ramp progress (0.0 to 1.0)
        minutes_since_start = (now - first_block_start_time).total_seconds() / 60
        ramp_progress = min(1.0, minutes_since_start / self._quiet_mode_ramp_minutes)

        # Clamp quiet mode max to at least min_egress
        quiet_max = max(self._quiet_mode_max_flow, self._min_egress)

        # Linear interpolation from quiet_max to max_egress
        effective_max = quiet_max + ramp_progress * (self._max_egress - quiet_max)

        _LOGGER.debug(
            "Quiet mode: %.0f%% ramp progress, effective max flow: %.1f°C",
            ramp_progress * 100,
            effective_max,
        )

        return effective_max

    async def set_flow_temperature(self, temperature: float) -> None:
        """Set the heater flow temperature setpoint.

        Args:
            temperature: Target flow temperature in °C (0 to turn off)
        """
        await self._safe_service_call(
            "number",
            "set_value",
            {
                "entity_id": self._heater_entity_id,
                "value": temperature,
            },
        )
        _LOGGER.debug("Set heater to %.1f°C", temperature)

        # Track heater state for next cycle's cooldown check
        self._heater_was_active = temperature > 0

    @property
    def cooldown_active(self) -> bool:
        """Return whether cooldown mode is active."""
        return self._cooldown_active

    @property
    def heater_was_active(self) -> bool:
        """Return whether heater was active last cycle."""
        return self._heater_was_active

    async def _safe_service_call(
        self, domain: str, service: str, data: dict[str, str | float]
    ) -> bool:
        """Call a service with error handling.

        Args:
            domain: Service domain (e.g., "number", "climate")
            service: Service name (e.g., "set_value")
            data: Service data parameters

        Returns:
            True if service call succeeded, False otherwise
        """
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
            return True
        except Exception as err:
            entity_id = data.get("entity_id", "unknown")
            _LOGGER.error(
                "Service call %s.%s failed for %s: %s", domain, service, entity_id, err
            )
            return False
