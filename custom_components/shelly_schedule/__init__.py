"""Shelly Schedule – native HA custom integration.

Config-flow based setup: Settings → Integrations → Add Integration → Shelly Schedule.
Supports Gen2/Gen3 (Digest-Auth) and Gen1 (Basic-Auth) Shelly devices.
All helper entities are native HA entities (select, number, time, switch).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import timedelta
from functools import partial

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, callback
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    SCAN_INTERVAL_SECONDS,
    TAGE_MAP,
    CONF_GEN2_PASSWORD,
    CONF_GEN1_USERNAME,
    CONF_GEN1_PASSWORD,
    CONF_DEVICE_CREDENTIALS,
    device_name_to_slug,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["select", "number", "time", "switch", "sensor"]


# ── Slug helper ───────────────────────────────────────────────────────────────

def _name_to_entity_id(name: str, prefix: str = "shelly") -> str:
    """Convert a device display name to a valid HA sensor entity ID."""
    return f"sensor.{prefix}_{device_name_to_slug(name)}_schedule"


# ── Blocking HTTP helpers (run via executor) ──────────────────────────────────

def _http_get_sync(hostname: str, path: str, password: str) -> dict | None:
    """Synchronous GET to Shelly RPC endpoint (Digest-Auth)."""
    try:
        url = f"http://{hostname}/rpc/{path}"
        resp = requests.get(url, auth=HTTPDigestAuth("admin", password), timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _LOGGER.warning("Shelly GET error %s/%s: %s", hostname, path, exc)
        return None


def _http_post_sync(hostname: str, method: str, payload: str, password: str) -> dict | None:
    """Synchronous POST to Shelly RPC endpoint (Digest-Auth)."""
    try:
        url = f"http://{hostname}/rpc/{method}"
        resp = requests.post(
            url,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            auth=HTTPDigestAuth("admin", password),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _LOGGER.error("Shelly POST error %s/%s: %s", hostname, method, exc)
        return None


def _gen1_http_get_sync(hostname: str, path: str, user: str, password: str) -> dict | None:
    """Synchronous GET to Shelly Gen1 endpoint (Basic-Auth)."""
    try:
        url = f"http://{hostname}/{path}"
        resp = requests.get(url, auth=HTTPBasicAuth(user, password), timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        _LOGGER.warning("Shelly Gen1 GET error %s/%s: %s", hostname, path, exc)
        return None


def _gen1_http_post_form_sync(
    hostname: str, path: str, params, user: str, password: str
) -> bytes | None:
    """Synchronous POST with form data to Shelly Gen1 endpoint (Basic-Auth).
    params may be a dict or a list of (key, value) tuples for repeated keys."""
    try:
        url = f"http://{hostname}/{path}"
        resp = requests.post(url, data=params, auth=HTTPBasicAuth(user, password), timeout=10)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        _LOGGER.error("Shelly Gen1 POST error %s/%s: %s", hostname, path, exc)
        return None


def _gen1_http_post_raw_sync(
    hostname: str, path: str, body: str, user: str, password: str
) -> bytes | None:
    """Synchronous POST with a pre-built body string to Shelly Gen1 endpoint.

    Unlike _gen1_http_post_form_sync (which uses requests' built-in form encoding),
    this function sends `body` verbatim so that bracket characters like `[]` are NOT
    percent-encoded.  Shelly Gen1 firmware requires literal `schedule_rules[]` keys;
    the percent-encoded form `schedule_rules%5B%5D` is silently ignored.
    """
    try:
        url = f"http://{hostname}/{path}"
        resp = requests.post(
            url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=HTTPBasicAuth(user, password),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        _LOGGER.error("Shelly Gen1 POST error %s/%s: %s", hostname, path, exc)
        return None


def _find_device_identifiers(hass, device_reg, name: str):
    """Find HA device identifiers for a Shelly device by display name.

    Matches against name_by_user, dev.name, and entry.title so that both
    preferred and canonical names (used after collision resolution) work.
    """
    dev_id = None
    shelly_entries = hass.config_entries.async_entries("shelly")
    for dev in device_reg.devices.values():
        for entry in shelly_entries:
            if entry.entry_id in dev.config_entries:
                if name in (dev.name_by_user, dev.name, entry.title):
                    dev_id = dev.id
                    break
        if dev_id:
            break
    dev_entry = device_reg.async_get(dev_id) if dev_id else None
    return dev_entry.identifiers if dev_entry else None


# ── Coordinator ───────────────────────────────────────────────────────────────

class ShellyScheduleCoordinator:
    """Central coordinator holding entity refs and device maps."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise coordinator."""
        self.hass = hass
        self.entry = entry

        # Primary maps — keyed by sensor entity_id (e.g. "sensor.shelly_schedule_aabbcc112233")
        # entity_ids are MAC-based and therefore guaranteed unique by HA.
        self.device_map: dict[str, str] = {}        # entity_id → hostname  (Gen2/Gen3)
        self.gen1_device_map: dict[str, str] = {}   # entity_id → hostname  (Gen1)
        self._device_profiles: dict[str, str] = {}  # entity_id → "switch"|"cover"
        self._shelly_creds: dict[str, tuple[str, str]] = {}  # entity_id → (user, pw)
        self._display_names: dict[str, str] = {}    # entity_id → human-readable name
        self._sensors: dict[str, "ShellyScheduleSensor"] = {}  # entity_id → sensor

        # Reverse lookup for backwards-compat (old `device` param in service calls)
        self._entity_by_name: dict[str, str] = {}   # display_name → entity_id
        # Callback set by sensor platform to add new entities dynamically
        self.async_add_sensor_entities = None

        # Entity refs – populated by platform setup
        self.device_select = None
        self.gen1_device_select = None
        self.days_select = None
        self.action_select = None
        self.schedule_id_number = None
        self.position_number = None
        self.time_entity = None
        self.gen1_switch = None

    def _get_credentials(self, entity_id: str, gen: int) -> tuple[str, str]:
        """Return (user, password) for a device identified by sensor entity_id.

        Priority: per-device options override → Shelly integration config entry → empty.
        Also accepts a legacy display_name via _entity_by_name reverse lookup.
        """
        # Normalise: accept either entity_id or display_name (backwards compat)
        key = entity_id if entity_id in self._shelly_creds else self._entity_by_name.get(entity_id, entity_id)

        device_creds = self.entry.options.get(CONF_DEVICE_CREDENTIALS, {})
        override = device_creds.get(key, {})

        if gen >= 2:
            password = (
                override.get(CONF_GEN2_PASSWORD)
                or self._shelly_creds.get(key, ("admin", ""))[1]
            )
            return ("admin", password)
        else:
            shelly_user, shelly_pw = self._shelly_creds.get(key, ("admin", ""))
            user = override.get(CONF_GEN1_USERNAME) or shelly_user
            password = override.get(CONF_GEN1_PASSWORD) or shelly_pw
            return (user, password)

    async def load_devices(self) -> None:
        """Discover Shelly devices from config entries and device registry.

        Sensor entity_id is derived from the canonical device name (dev.name, not
        name_by_user) so renames don't cause collisions.  unique_id is MAC-based
        so HA entity registry keeps entities stable across renames.
        """
        try:
            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er

            device_reg = dr.async_get(self.hass)
            entity_reg = er.async_get(self.hass)
            entries = self.hass.config_entries.async_entries("shelly")
            _LOGGER.info("Shelly config entries found: %d", len(entries))

            new_gen2: dict[str, str] = {}
            new_gen1: dict[str, str] = {}
            new_creds: dict[str, tuple[str, str]] = {}
            new_profiles: dict[str, str] = {}
            new_names: dict[str, str] = {}
            new_entity_by_name: dict[str, str] = {}
            # entity_id → device identifiers (for sensor → device linkage)
            new_identifiers: dict[str, set] = {}
            new_unique_ids: dict[str, str] = {}
            new_gens: dict[str, int] = {}

            for entry in entries:
                host = entry.data.get("host", "")
                gen = entry.data.get("gen", 1)
                if not host:
                    continue

                # Display name: what the user sees (may not be unique)
                display_name = entry.title
                # Canonical name: set by Shelly integration, stable even after renames
                canonical_name = entry.title
                device_identifiers = {(DOMAIN, entry.entry_id)}
                device_id = None

                for dev in device_reg.devices.values():
                    if entry.entry_id in dev.config_entries:
                        display_name = dev.name_by_user or dev.name or entry.title
                        canonical_name = dev.name or entry.title
                        device_identifiers = set(dev.identifiers) or device_identifiers
                        device_id = dev.id
                        break

                if not canonical_name:
                    continue

                # entity_id and unique_id based on canonical name (dev.name, not name_by_user)
                # — identical format to original, but ignores user renames so slugs stay unique
                prefix = "shelly" if gen >= 2 else "shelly_gen1"
                slug = device_name_to_slug(canonical_name)
                entity_id = f"sensor.{prefix}_{slug}_schedule"
                unique_id = f"shelly_schedule_{prefix}_{slug}"
                new_unique_ids[entity_id] = unique_id
                new_gens[entity_id] = gen

                # Profile detection
                entry_profile = entry.data.get("profile", "")
                if entry_profile == "cover":
                    profile = "cover"
                elif entry_profile in ("switch", "rgb", "rgbw", "light"):
                    profile = "switch"
                elif device_id:
                    profile = "switch"
                    for ent in er.async_entries_for_device(entity_reg, device_id):
                        if ent.entity_id.startswith("cover."):
                            profile = "cover"
                            break
                else:
                    profile = "switch"

                _LOGGER.debug(
                    "Device %r canonical=%r entity_id=%s profile=%s",
                    display_name, canonical_name, entity_id, profile,
                )

                new_creds[entity_id] = (entry.data.get("username", "admin"), entry.data.get("password", ""))
                new_names[entity_id] = display_name
                new_entity_by_name[display_name] = entity_id
                new_identifiers[entity_id] = device_identifiers

                if gen >= 2:
                    new_gen2[entity_id] = host
                    new_profiles[entity_id] = profile
                else:
                    new_gen1[entity_id] = host

            self._shelly_creds = new_creds
            self._device_profiles = new_profiles
            self._display_names = new_names
            self._entity_by_name = new_entity_by_name

            _LOGGER.info("Shelly found – Gen2/Gen3: %d, Gen1: %d", len(new_gen2), len(new_gen1))

            if new_gen2:
                self.device_map = new_gen2
            else:
                _LOGGER.warning("No Shelly Gen2/Gen3 devices found.")

            if new_gen1:
                self.gen1_device_map = new_gen1
            else:
                _LOGGER.warning("No Shelly Gen1 devices found.")

            # Create sensor entities for newly discovered devices
            from .sensor import ShellyScheduleSensor
            new_entities = []
            for eid, host in {**new_gen2, **new_gen1}.items():
                gen = new_gens.get(eid, 2 if eid in new_gen2 else 1)
                if eid in self._sensors:
                    # Update mutable fields on existing sensor (gen may have changed)
                    self._sensors[eid]._gen = gen
                    self._sensors[eid]._device_name = new_names[eid]
                    self._sensors[eid]._hostname = host
                else:
                    sensor = ShellyScheduleSensor(
                        coordinator=self,
                        device_name=new_names[eid],
                        hostname=host,
                        gen=gen,
                        device_identifiers=new_identifiers.get(eid, {(DOMAIN, eid)}),
                        sensor_entity_id=eid,
                        sensor_unique_id=new_unique_ids[eid],
                    )
                    self._sensors[eid] = sensor
                    new_entities.append(sensor)

            if new_entities and self.async_add_sensor_entities is not None:
                self.async_add_sensor_entities(new_entities, True)

            gen2_names = sorted(new_names[e] for e in new_gen2)
            gen1_names = sorted(new_names[e] for e in new_gen1)
            if self.device_select is not None:
                self.device_select.update_options(gen2_names)
            if self.gen1_device_select is not None:
                self.gen1_device_select.update_options(gen1_names)

        except Exception as exc:
            _LOGGER.exception("load_devices error: %s", exc)

    async def update_sensor(self, eid: str) -> None:
        """Update a single sensor by entity_id (fast, targeted refresh)."""
        sensor = self._sensors.get(eid)
        if eid in self.device_map:
            hostname = self.device_map[eid]
            _, password = self._get_credentials(eid, 2)
            data = await self.hass.async_add_executor_job(
                _http_get_sync, hostname, "Schedule.List", password
            )
            if data is not None:
                if sensor:
                    sensor.set_gen2_data(data.get("jobs", []), password, self._device_profiles.get(eid, "switch"))
            else:
                if sensor:
                    sensor.set_unavailable()
        elif eid in self.gen1_device_map:
            hostname = self.gen1_device_map[eid]
            user, password = self._get_credentials(eid, 1)
            data = await self.hass.async_add_executor_job(
                _gen1_http_get_sync, hostname, "settings/relay/0", user, password
            )
            if data is not None:
                if sensor:
                    sensor.set_gen1_data(data.get("schedule_rules", []), data.get("schedule", False))
            else:
                if sensor:
                    sensor.set_unavailable()

    async def update_sensors(self) -> None:
        """Update all Shelly schedule sensors via HTTP."""
        if not self.device_map and not self.gen1_device_map:
            await self.load_devices()

        _LOGGER.info("Updating %d Gen2/Gen3 + %d Gen1 devices...", len(self.device_map), len(self.gen1_device_map))

        for eid in list(self.device_map) + list(self.gen1_device_map):
            await self.update_sensor(eid)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_device(
    coord: "ShellyScheduleCoordinator", call: ServiceCall
) -> tuple[str | None, str | None]:
    """Return (entity_id, hostname) from call.data.

    Accepts:
      - entity_id  (preferred): the sensor entity_id, e.g. "sensor.shelly_schedule_aabbcc..."
      - device     (legacy):    display name, resolved via _entity_by_name reverse lookup
    Falls back to the currently selected device in the helper select entity.
    """
    # Prefer new entity_id param; fall back to old 'device' display-name param
    requested = call.data.get("entity_id") or call.data.get("device")
    if requested:
        # Direct entity_id hit
        hostname = coord.device_map.get(requested)
        if hostname:
            return requested, hostname
        # Legacy: display_name → entity_id
        eid = coord._entity_by_name.get(requested)
        if eid:
            hostname = coord.device_map.get(eid)
            if hostname:
                _LOGGER.debug("resolve_device: mapped display name %r → %s", requested, eid)
                return eid, hostname
        _LOGGER.error(
            "resolve_device: '%s' not found in device_map or name lookup", requested
        )
        return None, None

    # Fallback: legacy helper select entity
    name = coord.device_select._attr_current_option if coord.device_select else None
    if not name or name == "–":
        _LOGGER.error("resolve_device: no device selected")
        return None, None
    eid = coord._entity_by_name.get(name, name)
    return eid, coord.device_map.get(eid)


def _resolve_gen1_device(
    coord: "ShellyScheduleCoordinator",
    call: "ServiceCall | None" = None,
) -> tuple[str | None, str | None, str | None]:
    """Return (entity_id, hostname, error_msg) for a Gen1 device.

    Accepts entity_id or legacy display name via call.data, or falls back to
    the currently selected device in the helper select entity.
    """
    if call is not None:
        requested = call.data.get("entity_id") or call.data.get("device")
        if requested:
            hostname = coord.gen1_device_map.get(requested)
            if hostname:
                return requested, hostname, None
            eid = coord._entity_by_name.get(requested)
            if eid:
                hostname = coord.gen1_device_map.get(eid)
                if hostname:
                    return eid, hostname, None
            return None, None, f"Gen1 device not found: {requested!r}"

    if coord.gen1_device_select is None:
        return None, None, "gen1_device_select not initialised"
    name = coord.gen1_device_select._attr_current_option
    if not name or name == "–":
        return None, None, "No Gen1 device selected"
    eid = coord._entity_by_name.get(name, name)
    hostname = coord.gen1_device_map.get(eid)
    if not hostname:
        return None, None, f"Gen1 device unknown: {name}"
    return eid, hostname, None


# ── Service handler implementations ──────────────────────────────────────────

async def _svc_reload_devices(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: reload all devices from device registry."""
    await coord.load_devices()


async def _svc_update_sensors(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: refresh all schedule sensors."""
    await coord.update_sensors()


async def _svc_create_schedule(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: create a new schedule on the selected Gen2/Gen3 device."""
    geraet_name, hostname = _resolve_device(coord, call)
    if not hostname:
        return

    if "timespec" in call.data:
        timespec = call.data["timespec"]
    else:
        if coord.time_entity is None or coord.time_entity._attr_native_value is None:
            _LOGGER.error("time_entity not initialised or has no value")
            return
        zeit = coord.time_entity._attr_native_value
        tage_label = coord.days_select._attr_current_option if coord.days_select else "Täglich"
        tage = TAGE_MAP.get(tage_label, "*")
        timespec = f"0 {zeit.minute} {zeit.hour} * * {tage}"

    if "calls" in call.data:
        calls = call.data["calls"]
    else:
        aktion = coord.action_select._attr_current_option if coord.action_select else "Einschalten"
        if aktion == "Einschalten":
            calls = [{"method": "Switch.Set", "params": {"id": 0, "on": True}}]
        elif aktion == "Ausschalten":
            calls = [{"method": "Switch.Set", "params": {"id": 0, "on": False}}]
        elif aktion == "Öffnen":
            calls = [{"method": "Cover.Open", "params": {"id": 0}}]
        elif aktion == "Schließen":
            calls = [{"method": "Cover.Close", "params": {"id": 0}}]
        elif aktion == "Stoppen":
            calls = [{"method": "Cover.Stop", "params": {"id": 0}}]
        elif aktion == "Position":
            pos = int(coord.position_number._attr_native_value) if coord.position_number else 50
            calls = [{"method": "Cover.GoToPosition", "params": {"id": 0, "pos": pos}}]
        else:
            _LOGGER.error("Unknown action: %s", aktion)
            return

    enable = call.data.get("enable", True)
    _, password = coord._get_credentials(geraet_name, 2)
    payload = json.dumps({"timespec": timespec, "enable": enable, "calls": calls})
    result = await coord.hass.async_add_executor_job(
        _http_post_sync, hostname, "Schedule.Create", payload, password
    )
    if result:
        _LOGGER.info("Schedule created on %s: ID=%s, timespec=%s", geraet_name, result.get("id"), timespec)
        await coord.update_sensor(geraet_name)
    else:
        _LOGGER.error("Schedule creation failed on %s", geraet_name)


async def _svc_run_action(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: immediately execute the RPC calls of a schedule on the device."""
    geraet_name, hostname = _resolve_device(coord, call)
    if not hostname:
        return
    calls = call.data.get("calls", [])
    if not calls:
        _LOGGER.error("run_action: no calls provided")
        return
    _, password = coord._get_credentials(geraet_name, 2)
    for rpc_call in calls:
        method = rpc_call.get("method", "")
        params = rpc_call.get("params", {})
        payload = json.dumps(params)
        result = await coord.hass.async_add_executor_job(
            _http_post_sync, hostname, method, payload, password
        )
        if result is None:
            _LOGGER.error("run_action: RPC call %s failed on %s", method, geraet_name)
        else:
            _LOGGER.info("run_action: %s on %s → %s", method, geraet_name, result)


async def _svc_delete_schedule(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: delete a schedule by ID from the selected Gen2/Gen3 device."""
    geraet_name, hostname = _resolve_device(coord, call)
    if not hostname:
        return
    schedule_id_raw = call.data.get("schedule_id")
    if schedule_id_raw is not None:
        schedule_id = int(schedule_id_raw)
    elif coord.schedule_id_number:
        schedule_id = int(coord.schedule_id_number._attr_native_value)
    else:
        _LOGGER.error("delete_schedule: no schedule_id provided")
        return
    _LOGGER.info("Deleting schedule %d on %s", schedule_id, geraet_name)
    _, password = coord._get_credentials(geraet_name, 2)
    result = await coord.hass.async_add_executor_job(
        _http_post_sync, hostname, "Schedule.Delete", json.dumps({"id": schedule_id}), password
    )
    if result is not None:
        _LOGGER.info("Schedule %d deleted on %s", schedule_id, geraet_name)
        await coord.update_sensor(geraet_name)


async def _svc_set_schedule_enabled(
    coord: ShellyScheduleCoordinator, call: ServiceCall, enable: bool
) -> None:
    """Shared helper: enable or disable a schedule by ID."""
    geraet_name, hostname = _resolve_device(coord, call)
    if not hostname:
        return
    schedule_id = int(call.data.get("schedule_id") or coord.schedule_id_number._attr_native_value or 1)
    _, password = coord._get_credentials(geraet_name, 2)
    result = await coord.hass.async_add_executor_job(
        _http_post_sync, hostname, "Schedule.Update", json.dumps({"id": schedule_id, "enable": enable}), password,
    )
    if result is not None:
        await coord.update_sensor(geraet_name)


async def _svc_enable_schedule(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: enable a schedule by ID on the selected Gen2/Gen3 device."""
    await _svc_set_schedule_enabled(coord, call, True)


async def _svc_disable_schedule(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: disable a schedule by ID on the selected Gen2/Gen3 device."""
    await _svc_set_schedule_enabled(coord, call, False)


async def _svc_replace_schedule(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: replace a schedule (delete then create) on the selected Gen2/Gen3 device."""
    await _svc_delete_schedule(coord, call)
    await _svc_create_schedule(coord, call)


async def _svc_gen1_set_schedule(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: set a schedule rule on the selected Gen1 device (replaces all rules)."""
    eid, hostname, err = _resolve_gen1_device(coord)
    if err:
        _LOGGER.error(err)
        return

    if coord.time_entity is None or coord.time_entity._attr_native_value is None:
        _LOGGER.error("time_entity not initialised or has no value")
        return

    zeit = coord.time_entity._attr_native_value
    stunde = zeit.hour
    minute = zeit.minute
    action = "on" if (coord.gen1_switch is not None and coord.gen1_switch._attr_is_on) else "off"
    regel = f"{stunde:02d}{minute:02d}-0123456-{action}"

    user, password = coord._get_credentials(eid, 1)
    result = await coord.hass.async_add_executor_job(
        _gen1_http_post_form_sync,
        hostname,
        "settings/relay/0",
        {"schedule": "true", "schedule_rules[0]": regel},
        user,
        password,
    )
    if result is not None:
        _LOGGER.info("Gen1 schedule set on %s: %s", eid, regel)
        await coord.update_sensor(eid)


async def _svc_gen1_delete_schedule(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: delete all schedule rules from the selected Gen1 device."""
    eid, hostname, err = _resolve_gen1_device(coord)
    if err:
        return
    user, password = coord._get_credentials(eid, 1)
    result = await coord.hass.async_add_executor_job(
        _gen1_http_get_sync, hostname, "settings/relay/0?schedule=false", user, password
    )
    if result is not None:
        await coord.update_sensor(eid)


async def _svc_gen1_enable_scheduling(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: enable scheduling on the selected Gen1 device."""
    eid, hostname, err = _resolve_gen1_device(coord, call)
    if err:
        return
    user, password = coord._get_credentials(eid, 1)
    result = await coord.hass.async_add_executor_job(
        _gen1_http_get_sync, hostname, "settings/relay/0?schedule=true", user, password
    )
    if result is not None:
        await coord.update_sensor(eid)


async def _svc_gen1_disable_scheduling(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: disable scheduling on the selected Gen1 device."""
    eid, hostname, err = _resolve_gen1_device(coord, call)
    if err:
        return
    user, password = coord._get_credentials(eid, 1)
    result = await coord.hass.async_add_executor_job(
        _gen1_http_get_sync, hostname, "settings/relay/0?schedule=false", user, password
    )
    if result is not None:
        await coord.update_sensor(eid)


async def _svc_gen1_save_rules(coord: ShellyScheduleCoordinator, call: ServiceCall) -> None:
    """Service: replace all schedule rules on a Gen1 device.

    Parameters
    ----------
    entity_id : str  – sensor entity_id (preferred, e.g. "sensor.shelly_schedule_aabbcc...")
    device    : str  – legacy display name fallback
    rules     : list – rule strings; empty list → disable scheduling
    """
    eid, hostname, err = _resolve_gen1_device(coord, call)
    if err or not hostname:
        _LOGGER.error("gen1_save_rules: %s", err or "device not found")
        return

    rules: list[str] = list(call.data.get("rules", []))
    user, password = coord._get_credentials(eid, 1)

    if not rules:
        await coord.hass.async_add_executor_job(
            _gen1_http_get_sync, hostname, "settings/relay/0?schedule=false", user, password
        )
    else:
        # Shelly Gen1 firmware (SHPLG-S v1.14.1) only processes the FIRST entry when
        # schedule_rules[] or schedule_rules[n] keys are repeated — even with literal brackets.
        # The workaround is to pass all rules as a single comma-separated value:
        #   schedule_rules=rule1%2Crule2%2Crule3
        # The firmware splits on commas and stores all rules correctly.
        from urllib.parse import quote
        rules_csv = quote(",".join(rules), safe="")
        body = f"schedule=1&schedule_rules={rules_csv}"
        _LOGGER.debug("gen1_save_rules body: %s", body)
        await coord.hass.async_add_executor_job(
            _gen1_http_post_raw_sync, hostname, "settings/relay/0", body, user, password
        )
    await coord.update_sensor(eid)


# ── Integration setup ─────────────────────────────────────────────────────────

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Backwards-compat stub — YAML setup is not used; config-flow only."""
    return True


_LOVELACE_URL = "/shelly_schedule/shelly-schedule-card.js"
_LOVELACE_RES_URL = f"{_LOVELACE_URL}?v={int(os.path.getmtime(os.path.join(os.path.dirname(__file__), 'www', 'shelly-schedule-card.js.gz')))}"


async def _register_lovelace_resource(hass: HomeAssistant) -> None:
    """Auto-register the JS card as a Lovelace resource.

    Strategy 1: Use the live ResourceStorageCollection from hass.data["lovelace"]
                 → takes effect immediately without restart.
    Strategy 2: Write directly to .storage/lovelace_resources via Store
                 → takes effect after next HA restart (fallback).
    """
    import uuid
    from homeassistant.helpers.storage import Store

    # ── Strategy 1: in-memory collection ──────────────────────────────────
    try:
        lovelace = hass.data.get("lovelace")
        resources = None
        if isinstance(lovelace, dict):
            resources = lovelace.get("resources")
        elif lovelace is not None:
            resources = getattr(lovelace, "resources", None)

        if resources is not None:
            existing = resources.async_items() if hasattr(resources, "async_items") else []
            for item in existing:
                if _LOVELACE_URL in item.get("url", ""):
                    if item.get("url") == _LOVELACE_RES_URL:
                        _LOGGER.debug("Shelly Schedule card already registered (live, up to date)")
                        return
                    # URL veraltet — aktualisieren
                    try:
                        await resources.async_update_item(item["id"], {"res_type": "module", "url": _LOVELACE_RES_URL})
                        _LOGGER.info("Updated Lovelace resource (live): %s", _LOVELACE_RES_URL)
                    except Exception:
                        await resources.async_delete_item(item["id"])
                        await resources.async_create_item({"res_type": "module", "url": _LOVELACE_RES_URL})
                        _LOGGER.info("Replaced Lovelace resource (live): %s", _LOVELACE_RES_URL)
                    return
            await resources.async_create_item({"res_type": "module", "url": _LOVELACE_RES_URL})
            _LOGGER.info("Registered Lovelace resource (live): %s", _LOVELACE_RES_URL)
            return
    except Exception as exc:
        _LOGGER.debug("Live Lovelace resource registration failed: %s", exc)

    # ── Strategy 2: direct storage write ──────────────────────────────────
    try:
        store = Store(hass, version=1, key="lovelace_resources")
        data = await store.async_load() or {"items": []}
        items = data.get("items", [])

        for item in items:
            if _LOVELACE_URL in item.get("url", ""):
                if item.get("url") == _LOVELACE_RES_URL:
                    _LOGGER.debug("Shelly Schedule card already in storage (up to date)")
                    return
                # URL veraltet — aktualisieren
                item["url"] = _LOVELACE_RES_URL
                data["items"] = items
                await store.async_save(data)
                _LOGGER.info("Updated Lovelace resource (storage): %s", _LOVELACE_RES_URL)
                return

        items.append({"id": str(uuid.uuid4()), "type": "module", "url": _LOVELACE_RES_URL})
        data["items"] = items
        await store.async_save(data)
        _LOGGER.info(
            "Registered Lovelace resource (storage, active after restart): %s", _LOVELACE_RES_URL
        )
    except Exception as exc:
        _LOGGER.error("Could not register Lovelace resource: %s", exc)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shelly Schedule from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coord = ShellyScheduleCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coord

    # Serve the Lovelace card JS as a static file
    www_path = os.path.join(os.path.dirname(__file__), "www")
    await hass.http.async_register_static_paths([
        StaticPathConfig("/shelly_schedule", www_path, False),
    ])

    # Set up all entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register all 11 services
    hass.services.async_register(DOMAIN, "reload_devices",        partial(_svc_reload_devices,        coord))
    hass.services.async_register(DOMAIN, "update_sensors",        partial(_svc_update_sensors,        coord))
    hass.services.async_register(DOMAIN, "create_schedule",       partial(_svc_create_schedule,       coord))
    hass.services.async_register(DOMAIN, "delete_schedule",       partial(_svc_delete_schedule,       coord))
    hass.services.async_register(DOMAIN, "enable_schedule",       partial(_svc_enable_schedule,       coord))
    hass.services.async_register(DOMAIN, "disable_schedule",      partial(_svc_disable_schedule,      coord))
    hass.services.async_register(DOMAIN, "replace_schedule",      partial(_svc_replace_schedule,      coord))
    hass.services.async_register(DOMAIN, "gen1_set_schedule",     partial(_svc_gen1_set_schedule,     coord))
    hass.services.async_register(DOMAIN, "gen1_delete_schedule",  partial(_svc_gen1_delete_schedule,  coord))
    hass.services.async_register(DOMAIN, "gen1_enable_scheduling", partial(_svc_gen1_enable_scheduling, coord))
    hass.services.async_register(DOMAIN, "gen1_disable_scheduling", partial(_svc_gen1_disable_scheduling, coord))
    hass.services.async_register(DOMAIN, "run_action",             partial(_svc_run_action,             coord))
    hass.services.async_register(DOMAIN, "gen1_save_rules",       partial(_svc_gen1_save_rules,        coord))

    # Delayed startup: wait for Shelly integration to finish loading
    async def _startup(delay: int = 20):
        await asyncio.sleep(delay)
        await coord.load_devices()
        await coord.update_sensors()
        await _register_lovelace_resource(hass)

    if hass.state == CoreState.running:
        # Integration added while HA is already running — Shelly already loaded
        hass.async_create_task(_startup(delay=2))
    else:
        # HA cold start — wait for Shelly to finish loading
        @callback
        def _on_started(event):
            hass.async_create_task(_startup(delay=20))

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)

    # Periodic update every SCAN_INTERVAL_SECONDS
    async def _periodic_update(now):
        await coord.update_sensors()

    async_track_time_interval(
        hass,
        _periodic_update,
        timedelta(seconds=SCAN_INTERVAL_SECONDS),
    )

    _LOGGER.info("Shelly Schedule loaded.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
