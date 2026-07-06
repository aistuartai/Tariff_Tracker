"""Binary sensor platform for Tariff Tracker: bonus window + bonus result."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import tariff_engine as engine
from .const import CONF_PERIOD_BONUS, CONF_PERIOD_NAME, DOMAIN
from .runtime import PlanRuntime


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: PlanRuntime = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = []
    for period in runtime.periods:
        if not period.get(CONF_PERIOD_BONUS):
            continue
        name = period[CONF_PERIOD_NAME]
        entities.append(BonusActiveWindowSensor(runtime, entry, period))
        entities.append(BonusEarnedTodaySensor(runtime, entry, period))

    async_add_entities(entities)


class _BaseBonusSensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry, period: dict, key: str, name: str) -> None:
        self._runtime = runtime
        self._period = period
        self._attr_unique_id = f"{entry.entry_id}_{period[CONF_PERIOD_NAME]}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=runtime.plan_name,
            manufacturer="Tariff Tracker",
            model="Tariff Plan",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._runtime.register_update_callback(self._handle_runtime_update)
        )

    def _handle_runtime_update(self) -> None:
        self.async_write_ha_state()


class BonusActiveWindowSensor(_BaseBonusSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry, period: dict) -> None:
        super().__init__(
            runtime, entry, period, "bonus_active_window",
            f"{period[CONF_PERIOD_NAME]} bonus window active",
        )

    @property
    def is_on(self) -> bool:
        return engine.period_contains_time(self._period, dt_util.now())


class BonusEarnedTodaySensor(_BaseBonusSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry, period: dict) -> None:
        super().__init__(
            runtime, entry, period, "bonus_earned_today",
            f"{period[CONF_PERIOD_NAME]} bonus earned today",
        )

    @property
    def is_on(self) -> bool | None:
        return self._runtime.bonus_earned_today.get(self._period[CONF_PERIOD_NAME])
