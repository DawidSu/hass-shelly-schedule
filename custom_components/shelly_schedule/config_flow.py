"""Config flow for Shelly Schedule.

Setup flow (ShellyScheduleConfigFlow):
  - user step: no credentials needed; creates the single config entry.

Options flow (ShellyScheduleOptionsFlow):
  - init step: lists all Shelly devices discovered via the Shelly integration.
  - device_password step: lets the user enter per-device credential overrides
    (Gen2/Gen3: Digest-Auth password; Gen1: Basic-Auth username + password).

Stored credentials override those read from the Shelly integration config entries.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_GEN2_PASSWORD,
    CONF_GEN1_USERNAME,
    CONF_GEN1_PASSWORD,
    CONF_DEVICE_CREDENTIALS,
)


class ShellyScheduleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Shelly Schedule."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step — no credentials needed, uses Shelly integration."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Shelly Schedule", data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return ShellyScheduleOptionsFlow(config_entry)


class ShellyScheduleOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Shelly Schedule."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry
        self._selected_device = None
        self._selected_gen = None
        self._device_list = []  # list of (display_label, device_name, gen)

    async def async_step_init(self, user_input=None):
        """Discover devices and show device selector."""
        # Build device list from Shelly config entries + device registry
        device_reg = dr.async_get(self.hass)
        shelly_entries = self.hass.config_entries.async_entries("shelly")

        device_list = []
        for entry in shelly_entries:
            host = entry.data.get("host", "")
            gen = entry.data.get("gen", 1)
            if not host:
                continue
            name = entry.title
            for dev in device_reg.devices.values():
                if entry.entry_id in dev.config_entries:
                    name = dev.name_by_user or dev.name or entry.title
                    break
            if not name:
                continue
            gen_label = f"Gen{gen}" if gen >= 2 else "Gen1"
            label = f"{name} ({gen_label})"
            device_list.append((label, name, gen))

        device_list.sort(key=lambda x: x[0])
        self._device_list = device_list

        if not device_list:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            selected_label = user_input["device"]
            for label, name, gen in device_list:
                if label == selected_label:
                    self._selected_device = name
                    self._selected_gen = gen
                    break
            if self._selected_device:
                return await self.async_step_device_password()

        labels = [label for label, _, _ in device_list]
        schema = vol.Schema(
            {
                vol.Required("device"): vol.In(labels),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )

    async def async_step_device_password(self, user_input=None):
        """Enter credentials for the selected device."""
        device_name = self._selected_device
        gen = self._selected_gen

        existing_options = dict(self._config_entry.options)
        device_creds = dict(existing_options.get(CONF_DEVICE_CREDENTIALS, {}))
        existing_device_creds = device_creds.get(device_name, {})

        if user_input is not None:
            device_creds[device_name] = {}
            if gen and gen >= 2:
                device_creds[device_name][CONF_GEN2_PASSWORD] = user_input.get(CONF_GEN2_PASSWORD, "")
            else:
                device_creds[device_name][CONF_GEN1_USERNAME] = user_input.get(CONF_GEN1_USERNAME, "admin")
                device_creds[device_name][CONF_GEN1_PASSWORD] = user_input.get(CONF_GEN1_PASSWORD, "")

            existing_options[CONF_DEVICE_CREDENTIALS] = device_creds
            return self.async_create_entry(title="", data=existing_options)

        if gen and gen >= 2:
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_GEN2_PASSWORD,
                        default=existing_device_creds.get(CONF_GEN2_PASSWORD, ""),
                    ): str,
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_GEN1_USERNAME,
                        default=existing_device_creds.get(CONF_GEN1_USERNAME, "admin"),
                    ): str,
                    vol.Optional(
                        CONF_GEN1_PASSWORD,
                        default=existing_device_creds.get(CONF_GEN1_PASSWORD, ""),
                    ): str,
                }
            )

        return self.async_show_form(
            step_id="device_password",
            data_schema=schema,
            description_placeholders={"device_name": device_name},
        )
