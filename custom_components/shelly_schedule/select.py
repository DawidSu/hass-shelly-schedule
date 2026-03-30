"""Select entities for Shelly Schedule.

Provides four select entities used as service-call parameters:

- ShellyDeviceSelect  – active Gen2/Gen3 device (populated dynamically after discovery)
- ShellyDeviceSelect  – active Gen1 device (same class, gen1=True)
- ShellyFixedSelect   – weekday selector (Täglich … Sonntag)
- ShellyFixedSelect   – action selector (Einschalten / Ausschalten / Öffnen …)

All entities belong to the virtual "Shelly Schedule" service device and are
EntityCategory.CONFIG so they don't appear on the main dashboard.
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TAGE_OPTIONS, AKTION_OPTIONS

SCHEDULE_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, DOMAIN)},
    name="Shelly Schedule",
    entry_type=DeviceEntryType.SERVICE,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up select entities for Shelly Schedule."""
    coord = hass.data[DOMAIN][entry.entry_id]

    dev_sel = ShellyDeviceSelect(coord, False)
    gen1_sel = ShellyDeviceSelect(coord, True)
    days_sel = ShellyFixedSelect(
        "Shelly Schedule Wochentage",
        "shelly_schedule_wochentage",
        TAGE_OPTIONS,
        TAGE_OPTIONS[0],
    )
    action_sel = ShellyFixedSelect(
        "Shelly Schedule Aktion",
        "shelly_schedule_aktion",
        AKTION_OPTIONS,
        AKTION_OPTIONS[0],
    )

    coord.device_select = dev_sel
    coord.gen1_device_select = gen1_sel
    coord.days_select = days_sel
    coord.action_select = action_sel

    async_add_entities([dev_sel, gen1_sel, days_sel, action_sel])


class ShellyDeviceSelect(SelectEntity):
    """Select entity for choosing the active Shelly device."""

    _attr_should_poll = False
    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, gen1: bool):
        """Initialize device select."""
        self._coordinator = coordinator
        self._gen1 = gen1
        if gen1:
            self._attr_name = "Shelly Schedule Gen1 Gerät"
            self._attr_unique_id = "shelly_schedule_gen1_geraet"
        else:
            self._attr_name = "Shelly Schedule Gerät"
            self._attr_unique_id = "shelly_schedule_geraet"
        self._attr_options = ["–"]
        self._attr_current_option = "–"
        self._attr_device_info = SCHEDULE_DEVICE_INFO

    async def async_select_option(self, option: str) -> None:
        """Change the selected option and trigger sensor update."""
        self._attr_current_option = option
        self.async_write_ha_state()
        await self._coordinator.update_sensors()

    def update_options(self, options: list[str]) -> None:
        """Update available options (called by coordinator after device discovery)."""
        if not options:
            options = ["–"]
        self._attr_options = options
        if self._attr_current_option not in options:
            self._attr_current_option = options[0]
        if self.hass:
            self.async_write_ha_state()


class ShellyFixedSelect(SelectEntity):
    """Select entity with a fixed set of options."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, name: str, unique_id: str, options: list[str], default: str):
        """Initialize fixed select."""
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_options = options
        self._attr_current_option = default
        self._attr_device_info = SCHEDULE_DEVICE_INFO

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._attr_current_option = option
        self.async_write_ha_state()
