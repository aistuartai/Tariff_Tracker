"""Make tariff_engine importable without a Home Assistant install.

tariff_engine.py deliberately has zero `homeassistant` imports so its logic
is unit-testable on its own. It lives inside a package whose __init__.py
*does* import homeassistant though, so importing it as
`custom_components.tariff_tracker.tariff_engine` would drag that in. Instead
we add the component directory straight onto sys.path and import the module
directly.
"""
import importlib.util
import sys
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).parent.parent / "custom_components" / "tariff_tracker"
)
sys.path.insert(0, str(COMPONENT_DIR))

# tests/ha drives the integration inside a real Home Assistant instance and
# needs pytest-homeassistant-custom-component, which does not install on
# Windows. Skip that directory where it's missing so the engine tests still
# run anywhere; scripts/release_check.py runs it under WSL.
collect_ignore = []
if importlib.util.find_spec("pytest_homeassistant_custom_component") is None:
    collect_ignore.append("ha")
