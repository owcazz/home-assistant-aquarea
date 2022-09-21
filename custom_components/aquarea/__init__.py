"""The Aquarea Smart Cloud integration."""
from __future__ import annotations

from typing import Any

import aioaquarea

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry, device_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CLIENT, DEVICES, DOMAIN
from .coordinator import AquareaDataUpdateCoordinator

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.CLIMATE,
    Platform.BINARY_SENSOR,
    Platform.WATER_HEATER,
]


def initialize_data(hass: HomeAssistant, entry: ConfigEntry) -> None:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if entry.entry_id not in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.entry_id] = {
            CLIENT: None,
            DEVICES: dict[str, AquareaDataUpdateCoordinator](),
        }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aquarea Smart Cloud from a config entry."""

    initialize_data(hass, entry)

    client = hass.data[DOMAIN].get(entry.entry_id).get(CLIENT)
    if not client:
        username = entry.data.get(CONF_USERNAME)
        password = entry.data.get(CONF_PASSWORD)
        session = async_create_clientsession(hass)
        client = aioaquarea.Client(session, username, password)
        hass.data[DOMAIN][entry.entry_id][CLIENT] = client

    try:
        await client.login()
        # Get all the devices, we will filter the disabled ones later
        devices = await client.get_devices(include_long_id=True)

        # We create a Coordinator per Device and store it in the hass.data[DOMAIN] dict to be able to access it from the platform
        for device in devices:
            coordinator = AquareaDataUpdateCoordinator(
                hass=hass, entry=entry, client=client, device_info=device
            )
            hass.data[DOMAIN][entry.entry_id][DEVICES][device.device_id] = coordinator
            await coordinator.async_config_entry_first_refresh()

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except aioaquarea.AuthenticationError as err:
        if err.error_code in (
            aioaquarea.AuthenticationErrorCodes.INVALID_USERNAME_OR_PASSWORD,
            aioaquarea.AuthenticationErrorCodes.INVALID_CREDENTIALS,
        ):
            raise ConfigEntryAuthFailed from err

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    ent_reg = entity_registry.async_get(hass)
    dev_reg = device_registry.async_get(hass)
    devices = device_registry.async_entries_for_config_entry(
        dev_reg, config_entry.entry_id
    )
    entities = entity_registry.async_entries_for_config_entry(
        ent_reg, config_entry.entry_id
    )

    for entity in entities:
        if device := next(
            (device for device in devices if device.id == entity.device_id), None
        ):
            device_guid = next(
                (id[1] for id in device.identifiers if id[0] == DOMAIN), None
            )
    return False


class AquareaBaseEntity(CoordinatorEntity[AquareaDataUpdateCoordinator]):
    """Common base for Aquarea entities."""

    coordinator: AquareaDataUpdateCoordinator
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: AquareaDataUpdateCoordinator) -> None:
        """Initialize entity."""
        super().__init__(coordinator)

        self._attrs: dict[str, Any] = {
            "name": self.coordinator.device.name,
            "id": self.coordinator.device.device_id,
        }
        self._attr_unique_id = self.coordinator.device.device_id
        self._attr_name = self.coordinator.device.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device.device_id)},
            manufacturer=self.coordinator.device.manufacturer,
            model="",
            name=self.coordinator.device.name,
            sw_version=self.coordinator.device.version,
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()
