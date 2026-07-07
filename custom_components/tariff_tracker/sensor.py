"""Sensor platform for Tariff Tracker."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EXPORT_ENERGY_SENSOR,
    CONF_IMPORT_POWER_SENSOR,
    CONF_PERIOD_NAME,
    DOMAIN,
)
from .runtime import PlanRuntime


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: PlanRuntime = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        CurrentPeriodSensor(runtime, entry),
        CurrentRateSensor(runtime, entry),
        CostTodaySensor(runtime, entry),
        CostMonthSensor(runtime, entry),
        CostBillingPeriodSensor(runtime, entry),
        BillingPeriodStartSensor(runtime, entry),
        DaysRemainingSensor(runtime, entry),
        BonusSavingsSensor(runtime, entry),
    ]
    if runtime.options.get(CONF_IMPORT_POWER_SENSOR):
        entities.append(CurrentWindowAvgWattsSensor(runtime, entry))

    for period in runtime.periods:
        entities.append(PeriodAvgWattsSensor(runtime, entry, period))

    if runtime.options.get(CONF_EXPORT_ENERGY_SENSOR):
        entities.extend(
            [
                CurrentExportPeriodSensor(runtime, entry),
                CurrentExportRateSensor(runtime, entry),
                ExportCreditTodaySensor(runtime, entry),
                ExportCreditMonthSensor(runtime, entry),
                ExportCreditBillingPeriodSensor(runtime, entry),
            ]
        )

    async_add_entities(entities)


class _BaseTariffSensor(SensorEntity):
    """Shared device grouping + push-update wiring for one plan."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry, key: str, name: str) -> None:
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{key}"
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


class CurrentPeriodSensor(_BaseTariffSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "current_period", "Current period")

    @property
    def native_value(self) -> str | None:
        period = self._runtime.current_period()
        return period[CONF_PERIOD_NAME] if period else None


class CurrentRateSensor(_BaseTariffSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 4

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "current_rate", "Current rate")

    @property
    def native_unit_of_measurement(self) -> str:
        return f"{self._runtime.hass.config.currency}/kWh"

    @property
    def native_value(self) -> float | None:
        return self._runtime.current_rate()


class _CostSensor(_BaseTariffSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    @property
    def native_unit_of_measurement(self) -> str:
        return self._runtime.hass.config.currency


class CostTodaySensor(_CostSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "cost_today", "Cost today")

    @property
    def native_value(self) -> float:
        return round(self._runtime.cost_today, 4)


class CostMonthSensor(_CostSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "cost_month", "Cost this month")

    @property
    def native_value(self) -> float:
        return round(self._runtime.cost_month, 4)


class CostBillingPeriodSensor(_CostSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "cost_billing_period", "Cost this billing period")

    @property
    def native_value(self) -> float:
        return round(self._runtime.cost_billing_period, 4)


class BonusSavingsSensor(_CostSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "bonus_savings", "Bonus savings this billing period")

    @property
    def native_value(self) -> float:
        return round(self._runtime.bonus_savings_billing_period, 4)


class BillingPeriodStartSensor(_BaseTariffSensor):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "billing_period_start", "Billing period start")

    @property
    def native_value(self):
        return self._runtime.billing_period_start


class DaysRemainingSensor(_BaseTariffSensor):
    _attr_native_unit_of_measurement = "d"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "days_remaining", "Billing period days remaining")

    @property
    def native_value(self) -> int | None:
        return self._runtime.days_remaining()


class CurrentWindowAvgWattsSensor(_BaseTariffSensor):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "bonus_window_avg_w", "Bonus window average import power")

    @property
    def native_value(self) -> float | None:
        period = self._runtime.current_period()
        if period is None:
            return None
        name = period[CONF_PERIOD_NAME]
        sample = self._runtime.bonus_samples.get(name)
        if sample is None:
            return None
        return round(sample.average(), 1)


class PeriodAvgWattsSensor(_BaseTariffSensor):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry, period: dict) -> None:
        self._period_name = period[CONF_PERIOD_NAME]
        super().__init__(
            runtime,
            entry,
            f"{self._period_name}_avg_watts_today",
            f"{self._period_name} avg power today",
        )

    @property
    def native_value(self) -> float | None:
        value = self._runtime.current_period_avg_watts(self._period_name)
        return round(value, 1) if value is not None else None


class CurrentExportPeriodSensor(_BaseTariffSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "current_export_period", "Current export period")

    @property
    def native_value(self) -> str | None:
        period = self._runtime.current_export_period()
        return period[CONF_PERIOD_NAME] if period else None


class CurrentExportRateSensor(_BaseTariffSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 4

    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "current_export_rate", "Current export rate")

    @property
    def native_unit_of_measurement(self) -> str:
        return f"{self._runtime.hass.config.currency}/kWh"

    @property
    def native_value(self) -> float | None:
        return self._runtime.current_export_rate()


class ExportCreditTodaySensor(_CostSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "export_credit_today", "Export credit today")

    @property
    def native_value(self) -> float:
        return round(self._runtime.export_credit_today, 4)


class ExportCreditMonthSensor(_CostSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(runtime, entry, "export_credit_month", "Export credit this month")

    @property
    def native_value(self) -> float:
        return round(self._runtime.export_credit_month, 4)


class ExportCreditBillingPeriodSensor(_CostSensor):
    def __init__(self, runtime: PlanRuntime, entry: ConfigEntry) -> None:
        super().__init__(
            runtime, entry, "export_credit_billing_period", "Export credit this billing period"
        )

    @property
    def native_value(self) -> float:
        return round(self._runtime.export_credit_billing_period, 4)
