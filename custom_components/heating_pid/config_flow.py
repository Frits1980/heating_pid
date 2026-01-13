"""Config flow for EMS Zone Master integration.

Implements a 3-step configuration wizard:
1. Heater configuration - Select EMS-ESP entities for boiler control
2. Global settings - Configure temperature limits and thresholds
3. Zone configuration - Add heating zones with temperature sensors, valves, etc.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_FLOW_TEMP_ENTITY,
    CONF_HEATER_ENTITY,
    CONF_KD,
    CONF_KE,
    CONF_KI,
    CONF_KP,
    CONF_MAX_EGRESS,
    CONF_MIN_EGRESS,
    CONF_MIN_IGNITION_LEVEL,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_RETURN_TEMP_ENTITY,
    CONF_SOLAR_DROP,
    CONF_SOLAR_POWER_ENTITY,
    CONF_SOLAR_THRESHOLD,
    CONF_ZONE_DEFAULT_SETPOINT,
    CONF_ZONE_NAME,
    CONF_ZONE_SCHEDULE_ENTITY,
    CONF_ZONE_TEMP_ENTITY,
    CONF_ZONE_VALVE_ENTITY,
    CONF_ZONE_WINDOW_ENTITY,
    CONF_ZONES,
    DEFAULT_KD,
    DEFAULT_KE,
    DEFAULT_KI,
    DEFAULT_KP,
    DEFAULT_MAX_EGRESS,
    DEFAULT_MIN_EGRESS,
    DEFAULT_MIN_IGNITION_LEVEL,
    DEFAULT_SETPOINT,
    DEFAULT_SOLAR_DROP,
    DEFAULT_SOLAR_THRESHOLD,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class EmsZoneMasterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EMS Zone Master.

    The flow progresses through three steps:
    1. async_step_user - Heater entity selection
    2. async_step_global - Global settings
    3. async_step_zones - Zone configuration (repeatable)
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._zones: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the heater configuration step.

        Collects EMS-ESP entity IDs for:
        - Heater control (number entity for flow temperature setpoint)
        - Flow temperature sensor
        - Return temperature sensor
        - Outdoor temperature sensor
        - Solar power sensor (optional)

        Args:
            user_input: Form data if submitted, None for initial display

        Returns:
            Flow result - either show form or proceed to next step
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate entities exist
            # TODO: Phase 1 - Add entity validation
            self._data.update(user_input)
            return await self.async_step_global()

        schema = vol.Schema(
            {
                vol.Required(CONF_HEATER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Required(CONF_FLOW_TEMP_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_RETURN_TEMP_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_OUTDOOR_TEMP_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_SOLAR_POWER_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"name": "EMS Zone Master"},
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the global settings step.

        Collects global parameters:
        - Min/max egress (flow) temperatures
        - Minimum ignition level (demand threshold)
        - Solar threshold and temperature drop

        Args:
            user_input: Form data if submitted, None for initial display

        Returns:
            Flow result - either show form or proceed to zones step
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate temperature range
            if user_input[CONF_MIN_EGRESS] >= user_input[CONF_MAX_EGRESS]:
                errors["base"] = "invalid_temp_range"
            else:
                self._data.update(user_input)
                return await self.async_step_zones()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIN_EGRESS, default=DEFAULT_MIN_EGRESS
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20, max=40, step=1, unit_of_measurement="°C"
                    )
                ),
                vol.Required(
                    CONF_MAX_EGRESS, default=DEFAULT_MAX_EGRESS
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=35, max=80, step=1, unit_of_measurement="°C"
                    )
                ),
                vol.Required(
                    CONF_MIN_IGNITION_LEVEL, default=DEFAULT_MIN_IGNITION_LEVEL
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=50, step=5, unit_of_measurement="%"
                    )
                ),
                vol.Required(
                    CONF_SOLAR_THRESHOLD, default=DEFAULT_SOLAR_THRESHOLD
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=10000, step=100, unit_of_measurement="W"
                    )
                ),
                vol.Required(
                    CONF_SOLAR_DROP, default=DEFAULT_SOLAR_DROP
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=10, step=0.5, unit_of_measurement="°C"
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="global",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the zone configuration step.

        Collects per-zone configuration:
        - Zone name
        - Temperature sensor entity
        - Valve entity (switch or climate)
        - Window sensor entity (optional)
        - Schedule entity (optional)
        - Default setpoint
        - PID gains (Kp, Ki, Kd, Ke)

        This step can be repeated to add multiple zones.

        Args:
            user_input: Form data if submitted, None for initial display

        Returns:
            Flow result - show form, add another zone, or complete setup
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("add_another", False):
                # Store this zone and show form again
                zone_data = {k: v for k, v in user_input.items() if k != "add_another"}
                self._zones.append(zone_data)
                return await self.async_step_zones()
            else:
                # Store final zone and complete
                zone_data = {k: v for k, v in user_input.items() if k != "add_another"}
                self._zones.append(zone_data)
                self._data[CONF_ZONES] = self._zones
                return self.async_create_entry(
                    title="EMS Zone Master",
                    data=self._data,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE_NAME): selector.TextSelector(),
                vol.Required(CONF_ZONE_TEMP_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_ZONE_VALVE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate"])
                ),
                vol.Optional(CONF_ZONE_WINDOW_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
                ),
                vol.Optional(CONF_ZONE_SCHEDULE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Required(
                    CONF_ZONE_DEFAULT_SETPOINT, default=DEFAULT_SETPOINT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=30, step=0.5, unit_of_measurement="°C"
                    )
                ),
                vol.Required(CONF_KP, default=DEFAULT_KP): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=0.5)
                ),
                vol.Required(CONF_KI, default=DEFAULT_KI): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=2, step=0.01)
                ),
                vol.Required(CONF_KD, default=DEFAULT_KD): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=500, step=5)
                ),
                vol.Required(CONF_KE, default=DEFAULT_KE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=0.2, step=0.005)
                ),
                vol.Optional("add_another", default=False): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="zones",
            data_schema=schema,
            errors=errors,
            description_placeholders={"zone_count": str(len(self._zones) + 1)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler.

        Returns:
            Options flow handler instance
        """
        return EmsZoneMasterOptionsFlow()


class EmsZoneMasterOptionsFlow(OptionsFlow):
    """Handle options flow for EMS Zone Master.

    Allows modification of:
    - Global temperature settings
    - Adding new zones
    - Managing existing zones (edit/delete)
    """

    _selected_zone: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options menu.

        Shows options to adjust global settings, add, or manage zones.
        """
        return self.async_show_menu(
            step_id="init",
            menu_options=["global_settings", "add_zone", "manage_zones"],
        )

    async def async_step_global_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle global settings modification."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_MIN_EGRESS] >= user_input[CONF_MAX_EGRESS]:
                errors["base"] = "invalid_temp_range"
            else:
                # Merge with existing data
                new_data = {**self.config_entry.data, **user_input}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIN_EGRESS,
                    default=self.config_entry.data.get(CONF_MIN_EGRESS, DEFAULT_MIN_EGRESS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=20, max=40, step=1, unit_of_measurement="°C"
                    )
                ),
                vol.Required(
                    CONF_MAX_EGRESS,
                    default=self.config_entry.data.get(CONF_MAX_EGRESS, DEFAULT_MAX_EGRESS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=35, max=80, step=1, unit_of_measurement="°C"
                    )
                ),
                vol.Required(
                    CONF_MIN_IGNITION_LEVEL,
                    default=self.config_entry.data.get(CONF_MIN_IGNITION_LEVEL, DEFAULT_MIN_IGNITION_LEVEL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=50, step=5, unit_of_measurement="%"
                    )
                ),
                vol.Required(
                    CONF_SOLAR_THRESHOLD,
                    default=self.config_entry.data.get(CONF_SOLAR_THRESHOLD, DEFAULT_SOLAR_THRESHOLD),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=10000, step=100, unit_of_measurement="W"
                    )
                ),
                vol.Required(
                    CONF_SOLAR_DROP,
                    default=self.config_entry.data.get(CONF_SOLAR_DROP, DEFAULT_SOLAR_DROP),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=10, step=0.5, unit_of_measurement="°C"
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="global_settings",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle adding a new zone."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check for duplicate zone name
            existing_zones = self.config_entry.data.get(CONF_ZONES, [])
            existing_names = [z.get(CONF_ZONE_NAME) for z in existing_zones]

            if user_input[CONF_ZONE_NAME] in existing_names:
                errors["base"] = "zone_name_exists"
            else:
                # Add new zone to existing zones
                new_zones = list(existing_zones)
                new_zones.append(user_input)

                # Update config entry with new zone
                new_data = {**self.config_entry.data, CONF_ZONES: new_zones}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )

                # Trigger reload to pick up new zone
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE_NAME): selector.TextSelector(),
                vol.Required(CONF_ZONE_TEMP_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_ZONE_VALVE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate"])
                ),
                vol.Optional(CONF_ZONE_WINDOW_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
                ),
                vol.Optional(CONF_ZONE_SCHEDULE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Required(
                    CONF_ZONE_DEFAULT_SETPOINT, default=DEFAULT_SETPOINT
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=30, step=0.5, unit_of_measurement="°C"
                    )
                ),
                vol.Required(CONF_KP, default=DEFAULT_KP): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=0.5)
                ),
                vol.Required(CONF_KI, default=DEFAULT_KI): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=2, step=0.01)
                ),
                vol.Required(CONF_KD, default=DEFAULT_KD): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=500, step=5)
                ),
                vol.Required(CONF_KE, default=DEFAULT_KE): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=0.2, step=0.005)
                ),
            }
        )

        return self.async_show_form(
            step_id="add_zone",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_manage_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle zone selection for management."""
        errors: dict[str, str] = {}
        zones = self.config_entry.data.get(CONF_ZONES, [])

        if not zones:
            errors["base"] = "no_zones"
            return self.async_abort(reason="no_zones")

        if user_input is not None:
            self._selected_zone = user_input["selected_zone"]
            return await self.async_step_zone_action()

        zone_names = [z[CONF_ZONE_NAME] for z in zones]

        schema = vol.Schema(
            {
                vol.Required("selected_zone"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=zone_names,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="manage_zones",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_zone_action(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle zone action selection (edit/delete)."""
        return self.async_show_menu(
            step_id="zone_action",
            menu_options=["edit_zone", "delete_zone"],
            description_placeholders={"zone_name": self._selected_zone or ""},
        )

    async def async_step_delete_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle zone deletion with confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("confirm", False):
                # Remove zone from config
                zones = list(self.config_entry.data.get(CONF_ZONES, []))
                zones = [z for z in zones if z[CONF_ZONE_NAME] != self._selected_zone]

                new_data = {**self.config_entry.data, CONF_ZONES: zones}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )

                # Reload to remove entities
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(title="", data={})
            else:
                # User didn't confirm, go back to manage zones
                return await self.async_step_manage_zones()

        schema = vol.Schema(
            {
                vol.Required("confirm", default=False): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="delete_zone",
            data_schema=schema,
            errors=errors,
            description_placeholders={"zone_name": self._selected_zone or ""},
        )

    async def async_step_edit_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle zone editing."""
        errors: dict[str, str] = {}

        # Find the current zone data
        zones = self.config_entry.data.get(CONF_ZONES, [])
        current_zone = next(
            (z for z in zones if z[CONF_ZONE_NAME] == self._selected_zone),
            None,
        )

        if current_zone is None:
            return self.async_abort(reason="zone_not_found")

        if user_input is not None:
            # Check for duplicate zone name (if changed)
            existing_names = [
                z[CONF_ZONE_NAME] for z in zones if z[CONF_ZONE_NAME] != self._selected_zone
            ]

            if user_input[CONF_ZONE_NAME] in existing_names:
                errors["base"] = "zone_name_exists"
            else:
                # If zone name changed, remove old device first to avoid orphaned entities
                old_zone_name = self._selected_zone
                new_zone_name = user_input[CONF_ZONE_NAME]

                if old_zone_name != new_zone_name:
                    # Remove old device from registry (cascades to entities)
                    from homeassistant.helpers import device_registry as dr

                    device_registry = dr.async_get(self.hass)
                    old_device_id = (DOMAIN, f"{self.config_entry.entry_id}_{old_zone_name}")
                    old_device = device_registry.async_get_device(identifiers={old_device_id})
                    if old_device:
                        device_registry.async_remove_device(old_device.id)

                # Update zone in config
                new_zones = [
                    user_input if z[CONF_ZONE_NAME] == self._selected_zone else z
                    for z in zones
                ]

                new_data = {**self.config_entry.data, CONF_ZONES: new_zones}
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )

                # Reload to apply changes
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ZONE_NAME, default=current_zone.get(CONF_ZONE_NAME, "")
                ): selector.TextSelector(),
                vol.Required(
                    CONF_ZONE_TEMP_ENTITY, default=current_zone.get(CONF_ZONE_TEMP_ENTITY, "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_ZONE_VALVE_ENTITY, default=current_zone.get(CONF_ZONE_VALVE_ENTITY, "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "climate"])
                ),
                vol.Optional(
                    CONF_ZONE_WINDOW_ENTITY, default=current_zone.get(CONF_ZONE_WINDOW_ENTITY, "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
                ),
                vol.Optional(
                    CONF_ZONE_SCHEDULE_ENTITY, default=current_zone.get(CONF_ZONE_SCHEDULE_ENTITY, "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Required(
                    CONF_ZONE_DEFAULT_SETPOINT,
                    default=current_zone.get(CONF_ZONE_DEFAULT_SETPOINT, DEFAULT_SETPOINT),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=30, step=0.5, unit_of_measurement="°C"
                    )
                ),
                vol.Required(
                    CONF_KP, default=current_zone.get(CONF_KP, DEFAULT_KP)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=0.5)
                ),
                vol.Required(
                    CONF_KI, default=current_zone.get(CONF_KI, DEFAULT_KI)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=2, step=0.01)
                ),
                vol.Required(
                    CONF_KD, default=current_zone.get(CONF_KD, DEFAULT_KD)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=500, step=5)
                ),
                vol.Required(
                    CONF_KE, default=current_zone.get(CONF_KE, DEFAULT_KE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=0.2, step=0.005)
                ),
            }
        )

        return self.async_show_form(
            step_id="edit_zone",
            data_schema=schema,
            errors=errors,
            description_placeholders={"zone_name": self._selected_zone or ""},
        )
