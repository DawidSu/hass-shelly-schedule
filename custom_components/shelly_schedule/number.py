"""Number entities for Shelly Schedule.

Provides two number entities used as service-call parameters:

- ShellyNumber (schedule_id)  – integer 1–99, used for enable/disable/delete
- ShellyNumber (position)     – integer 0–100 %, used for Cover.GoToPosition

Both entities belong to the virtual "Shelly Schedule" service device.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .select import SCHEDULE_DEVICE_INFO


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up number entities for Shelly Schedule."""
    coord = hass.data[DOMAIN][entry.entry_id]

    id_num = ShellyNumber(
        "Shelly Schedule Zeitplan ID",
        "shelly_schedule_zeitplan_id",
        1,
        99,
        1,
        None,
        "mdi:identifier",
        1,
    )
    pos_num = ShellyNumber(
        "Shelly Schedule Position",
        "shelly_schedule_position",
        0,
        100,
        5,
        "%",
        "mdi:percent",
        50,
    )

    coord.schedule_id_number = id_num
    coord.position_number = pos_num

    async_add_entities([id_num, pos_num])


class ShellyNumber(NumberEntity):
    """Number entity for Shelly Schedule parameters."""

    _attr_should_poll = False
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        name: str,
        unique_id: str,
        min_val: float,
        max_val: float,
        step: float,
        unit: str | None,
        icon: str,
        default: float,
    ):
        """Initialize the number entity."""
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_native_min_value = min_val
        self._attr_native_max_value = max_val
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_native_value = float(default)
        self._attr_device_info = SCHEDULE_DEVICE_INFO

    async def async_set_native_value(self, value: float) -> None:
        """Update the number value."""
        self._attr_native_value = value
        self.async_write_ha_state()
