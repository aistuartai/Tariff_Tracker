"""Baseline handling when a plan is repointed at a different source sensor."""
import tariff_engine as engine


IMPORT_A = "sensor.old_grid_import"
IMPORT_B = "sensor.new_grid_import"
EXPORT_A = "sensor.old_export"
EXPORT_B = "sensor.new_export"


def test_unchanged_sensors_keep_their_baselines():
    clear_in, src_in, clear_out, src_out, changed = engine.resolve_baseline_sources(
        IMPORT_A, EXPORT_A, IMPORT_A, EXPORT_A
    )
    assert (clear_in, clear_out, changed) == (False, False, False)
    assert (src_in, src_out) == (IMPORT_A, EXPORT_A)


def test_changed_import_sensor_clears_only_the_import_baseline():
    clear_in, src_in, clear_out, src_out, changed = engine.resolve_baseline_sources(
        IMPORT_A, EXPORT_A, IMPORT_B, EXPORT_A
    )
    assert clear_in is True
    assert src_in == IMPORT_B
    assert clear_out is False
    assert src_out == EXPORT_A
    assert changed is True


def test_changed_export_sensor_clears_only_the_export_baseline():
    clear_in, _, clear_out, src_out, changed = engine.resolve_baseline_sources(
        IMPORT_A, EXPORT_A, IMPORT_A, EXPORT_B
    )
    assert (clear_in, clear_out, changed) == (False, True, True)
    assert src_out == EXPORT_B


def test_legacy_state_without_recorded_sources_keeps_its_baselines():
    # Saved before the source ids were persisted: assume they belong to the
    # configured sensors rather than discarding a valid baseline on upgrade.
    clear_in, src_in, clear_out, src_out, changed = engine.resolve_baseline_sources(
        None, None, IMPORT_A, EXPORT_A
    )
    assert (clear_in, clear_out) == (False, False)
    assert (src_in, src_out) == (IMPORT_A, EXPORT_A)
    assert changed is True  # the ids themselves need recording


def test_removing_the_export_sensor_drops_its_baseline():
    clear_in, _, clear_out, src_out, changed = engine.resolve_baseline_sources(
        IMPORT_A, EXPORT_A, IMPORT_A, None
    )
    assert (clear_in, clear_out, changed) == (False, True, True)
    assert src_out is None


def test_no_export_sensor_before_or_after_is_not_a_change():
    _, _, clear_out, src_out, changed = engine.resolve_baseline_sources(
        IMPORT_A, None, IMPORT_A, None
    )
    assert (clear_out, src_out, changed) == (False, None, False)


def test_meter_reading_accepts_plain_numbers():
    assert engine.coerce_meter_reading("2961.05") == 2961.05
    assert engine.coerce_meter_reading("0") == 0.0


def test_meter_reading_rejects_non_readings():
    # Seeding a baseline from any of these, then differencing the next real
    # reading against it, would book a meter's whole total as usage.
    for state in (None, "unknown", "unavailable", "", "on", "1,234"):
        assert engine.coerce_meter_reading(state) is None


def test_meter_reading_rejects_negatives():
    assert engine.coerce_meter_reading("-1.5") is None
