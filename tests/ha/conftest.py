"""Fixtures for the Home Assistant tests; helpers live in plan_helpers."""
import pytest

from homeassistant.core import HomeAssistant

from plan_helpers import START, local


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
async def melbourne(hass: HomeAssistant, freezer):
    """Run every test in the plan's own time zone, frozen at START."""
    await hass.config.async_set_time_zone("Australia/Melbourne")
    freezer.move_to(local(START))
    yield
