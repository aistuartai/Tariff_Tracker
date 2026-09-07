"""Multi-window period behaviour.

A period may be split into several disjoint windows - the case that drove
this is a shoulder rate applying both just before peak and overnight, which
a single start/end pair cannot express.
"""
from datetime import datetime, time

import tariff_engine as engine

# The real shape this was built for: one shoulder band, two windows.
SHOULDER_SPLIT = {
    "name": "Shoulder",
    "start_time": "15:00:00",
    "end_time": "16:00:00",
    "windows": [
        {"start_time": "15:00:00", "end_time": "16:00:00"},
        {"start_time": "23:00:00", "end_time": "12:00:00"},
    ],
    "days": "all",
    "tiers": [{"limit_kwh": None, "rate": 0.33}],
}

# No `windows` key at all: how every period written before multi-window
# support looks on disk.
LEGACY_SINGLE = {
    "name": "Peak",
    "start_time": "16:00:00",
    "end_time": "23:00:00",
    "days": "all",
    "tiers": [{"limit_kwh": None, "rate": 0.44}],
}


def test_legacy_period_without_windows_key_still_works():
    assert engine.period_windows(LEGACY_SINGLE) == [(time(16, 0), time(23, 0))]
    assert engine.period_contains_time(LEGACY_SINGLE, datetime(2026, 9, 7, 18, 0))
    assert not engine.period_contains_time(LEGACY_SINGLE, datetime(2026, 9, 7, 14, 0))


def test_both_windows_are_active():
    # First window.
    assert engine.period_contains_time(SHOULDER_SPLIT, datetime(2026, 9, 7, 15, 30))
    # Second window, before midnight.
    assert engine.period_contains_time(SHOULDER_SPLIT, datetime(2026, 9, 7, 23, 30))
    # Second window, after midnight - it wraps.
    assert engine.period_contains_time(SHOULDER_SPLIT, datetime(2026, 9, 7, 6, 0))


def test_gaps_between_windows_are_not_active():
    # Peak sits between the two shoulder windows.
    assert not engine.period_contains_time(SHOULDER_SPLIT, datetime(2026, 9, 7, 18, 0))
    # Off-peak sits before the first shoulder window.
    assert not engine.period_contains_time(SHOULDER_SPLIT, datetime(2026, 9, 7, 13, 0))


def test_window_boundaries_are_half_open():
    # Start is inclusive, end exclusive - so adjacent periods never both match.
    assert engine.period_contains_time(SHOULDER_SPLIT, datetime(2026, 9, 7, 15, 0, 0))
    assert not engine.period_contains_time(SHOULDER_SPLIT, datetime(2026, 9, 7, 16, 0, 0))


def test_day_filter_still_applies_to_every_window():
    weekends_only = dict(SHOULDER_SPLIT, days="weekends")
    # 2026-09-07 is a Monday, 2026-09-05 a Saturday.
    assert not engine.period_contains_time(weekends_only, datetime(2026, 9, 7, 15, 30))
    assert engine.period_contains_time(weekends_only, datetime(2026, 9, 5, 15, 30))


def test_total_hours_sums_all_windows_including_the_wrap():
    # 15:00-16:00 is 1h; 23:00-12:00 wraps midnight for 13h.
    assert engine.period_total_hours(SHOULDER_SPLIT) == 14.0
    assert engine.period_total_hours(LEGACY_SINGLE) == 7.0


def test_window_hours_handles_a_full_day():
    # start == end would otherwise compute as zero rather than 24h.
    assert engine.window_hours(time(0, 0), time(0, 0)) == 24.0


def test_format_lists_every_window():
    assert engine.format_period_windows(SHOULDER_SPLIT) == "15:00-16:00, 23:00-12:00"
    assert engine.format_period_windows(LEGACY_SINGLE) == "16:00-23:00"


def test_overlap_detection():
    assert not engine.windows_overlap(
        [(time(15, 0), time(16, 0)), (time(23, 0), time(12, 0))]
    )
    # Plain overlap.
    assert engine.windows_overlap(
        [(time(15, 0), time(17, 0)), (time(16, 0), time(18, 0))]
    )
    # One window fully inside another.
    assert engine.windows_overlap(
        [(time(9, 0), time(17, 0)), (time(12, 0), time(13, 0))]
    )
    # An overnight window overlapping an early-morning one.
    assert engine.windows_overlap(
        [(time(23, 0), time(6, 0)), (time(5, 0), time(7, 0))]
    )


def test_find_active_period_picks_the_multi_window_period():
    periods = [LEGACY_SINGLE, SHOULDER_SPLIT]
    found = engine.find_active_period(periods, datetime(2026, 9, 7, 6, 0))
    assert found is not None and found["name"] == "Shoulder"
    found = engine.find_active_period(periods, datetime(2026, 9, 7, 18, 0))
    assert found is not None and found["name"] == "Peak"


def test_tiering_is_shared_across_a_period_s_windows():
    # The whole point of merging two bands into one period: the daily tier
    # allowance is counted once for the band, not once per window.
    tiered = dict(
        SHOULDER_SPLIT,
        tiers=[{"limit_kwh": 10, "rate": 0.0}, {"limit_kwh": None, "rate": 0.33}],
    )
    # 8 kWh already used in window 1 leaves 2 kWh free; the next 4 kWh
    # straddles the boundary regardless of which window it happens in.
    cost = engine.cost_of_delta(tiered, 8.0, 4.0)
    assert cost == 2.0 * 0.0 + 2.0 * 0.33


def test_elapsed_hours_today_caps_at_the_window_end():
    # Window 1 is 15:00-16:00, window 2 (23:00-12:00) contributes 00:00-12:00
    # of today. At 13:00 the second window's share is capped at 12h and the
    # first has not opened, so the figure has stopped growing.
    at_1300 = engine.period_elapsed_hours_today(
        SHOULDER_SPLIT, datetime(2026, 9, 7, 13, 0)
    )
    assert at_1300 == 12.0
    # Still 12h at 14:59, then it grows again while window 1 is open.
    assert engine.period_elapsed_hours_today(
        SHOULDER_SPLIT, datetime(2026, 9, 7, 14, 59)
    ) == 12.0
    assert engine.period_elapsed_hours_today(
        SHOULDER_SPLIT, datetime(2026, 9, 7, 15, 30)
    ) == 12.5
    assert engine.period_elapsed_hours_today(
        SHOULDER_SPLIT, datetime(2026, 9, 7, 16, 0)
    ) == 13.0


def test_elapsed_hours_today_mid_window():
    # 06:00: only the overnight window's 00:00-06:00 has elapsed.
    assert engine.period_elapsed_hours_today(
        SHOULDER_SPLIT, datetime(2026, 9, 7, 6, 0)
    ) == 6.0


def test_elapsed_hours_today_counts_the_evening_tail():
    # 23:30 - the full 12h head of day plus 1h window plus 30min of tonight's
    # tail of the overnight window.
    assert engine.period_elapsed_hours_today(
        SHOULDER_SPLIT, datetime(2026, 9, 7, 23, 30)
    ) == 13.5


def test_elapsed_hours_today_is_zero_before_any_window():
    # Peak starts at 16:00, so nothing has elapsed at 09:00.
    assert engine.period_elapsed_hours_today(
        LEGACY_SINGLE, datetime(2026, 9, 7, 9, 0)
    ) == 0.0


def test_elapsed_hours_today_respects_the_day_filter():
    weekends_only = dict(SHOULDER_SPLIT, days="weekends")
    # Monday.
    assert engine.period_elapsed_hours_today(
        weekends_only, datetime(2026, 9, 7, 13, 0)
    ) == 0.0
    # Saturday.
    assert engine.period_elapsed_hours_today(
        weekends_only, datetime(2026, 9, 5, 13, 0)
    ) == 12.0


def test_elapsed_hours_never_exceeds_total_hours():
    # End of day: every window has fully elapsed, so the two agree.
    end_of_day = datetime(2026, 9, 7, 23, 59, 59)
    for period in (SHOULDER_SPLIT, LEGACY_SINGLE):
        assert engine.period_elapsed_hours_today(
            period, end_of_day
        ) <= engine.period_total_hours(period) + 0.001
