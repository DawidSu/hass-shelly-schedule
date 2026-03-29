"""Shelly Schedule sensor platform."""
from __future__ import annotations
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors — store callback for dynamic entity creation."""
    coord = hass.data[DOMAIN][entry.entry_id]
    coord.async_add_sensor_entities = async_add_entities


class ShellyScheduleSensor(SensorEntity):
    """Schedule sensor linked to an existing Shelly device."""

    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        device_name: str,
        hostname: str,
        gen: int,
        device_identifiers: set | frozenset,
    ) -> None:
        self._coordinator = coordinator
        self._device_name = device_name
        self._hostname = hostname
        self._gen = gen

        # Build slug for unique_id and entity_id (same logic as _name_to_entity_id)
        slug = device_name.lower().replace(" ", "_").replace("-", "_")
        clean = "".join(c for c in slug if ("a" <= c <= "z") or ("0" <= c <= "9") or c == "_")
        prefix = "shelly" if gen >= 2 else "shelly_gen1"
        self._attr_unique_id = f"shelly_schedule_{prefix}_{clean}"
        # Preserve existing entity IDs so dashboards keep working
        self.entity_id = f"sensor.{prefix}_{clean}_schedule"

        self._attr_name = None
        # Link to the existing Shelly device so HA knows device name, area, etc.
        self._attr_device_info = DeviceInfo(identifiers=device_identifiers)

        # Runtime data
        self._jobs: list = []
        self._schedule_rules: list = []
        self._schedule_enabled: bool = False
        self._login_user: str = "admin"
        self._login_password: str = ""
        self._device_profile: str = "switch"
        self._attr_available: bool = False

    # ── Data setters called by coordinator ────────────────────────────────

    def set_gen2_data(self, jobs: list, password: str, profile: str) -> None:
        self._jobs = jobs
        self._login_password = password
        self._device_profile = profile
        self._attr_available = True
        if self.hass:
            self.async_write_ha_state()

    def set_gen1_data(self, rules: list, schedule_enabled: bool) -> None:
        self._schedule_rules = rules
        self._schedule_enabled = schedule_enabled
        self._attr_available = True
        if self.hass:
            self.async_write_ha_state()

    def set_unavailable(self) -> None:
        self._attr_available = False
        if self.hass:
            self.async_write_ha_state()

    # ── HA properties ─────────────────────────────────────────────────────

    @property
    def native_value(self):
        if not self._attr_available:
            return None
        return len(self._jobs) if self._gen >= 2 else len(self._schedule_rules)

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {
            "hostname": self._hostname,
            "device_name": self._device_name,
        }
        if self._gen >= 2:
            attrs.update({
                "jobs": self._jobs,
                "device_profile": self._device_profile,
                "login_user": self._login_user,
                "login_password": self._login_password,
            })
        else:
            attrs.update({
                "schedule_rules": self._schedule_rules,
                "schedule": self._schedule_enabled,
            })
        return attrs
