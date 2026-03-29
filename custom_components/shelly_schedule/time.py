"""Time entity for Shelly Schedule."""
from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .select import SCHEDULE_DEVICE_INFO


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up time entity for Shelly Schedule."""
    coord = hass.data[DOMAIN][entry.entry_id]
    entity = ShellyTimeEntity()
    coord.time_entity = entity
    async_add_entities([entity])


class ShellyTimeEntity(TimeEntity):
    """Time entity for schedule time selection."""

    _attr_should_poll = False
    _attr_name = "Shelly Schedule Uhrzeit"
    _attr_unique_id = "shelly_schedule_uhrzeit"
    _attr_icon = "mdi:clock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_value = dt_time(7, 0)

    def __init__(self):
        """Initialize time entity."""
        self._attr_device_info = SCHEDULE_DEVICE_INFO

    async def async_set_value(self, value: dt_time) -> None:
        """Update the time value."""
        self._attr_native_value = value
        self.async_write_ha_state()
