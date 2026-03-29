"""Switch entity for Shelly Schedule Gen1."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .select import SCHEDULE_DEVICE_INFO


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up switch entity for Shelly Schedule."""
    coord = hass.data[DOMAIN][entry.entry_id]
    entity = ShellyGen1Switch()
    coord.gen1_switch = entity
    async_add_entities([entity])


class ShellyGen1Switch(SwitchEntity):
    """Switch entity for Gen1 schedule on/off action."""

    _attr_should_poll = False
    _attr_name = "Shelly Schedule Gen1 Einschalten"
    _attr_unique_id = "shelly_schedule_gen1_einschalten"
    _attr_icon = "mdi:power"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_is_on = True

    def __init__(self):
        """Initialize switch entity."""
        self._attr_device_info = SCHEDULE_DEVICE_INFO

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off."""
        self._attr_is_on = False
        self.async_write_ha_state()
