from __future__ import annotations

import unittest
from datetime import timedelta

from yr_in_the_terminal import common
from yr_in_the_terminal import forecast as yr_forecast


def _point(iso_time: str, temp: float, **extra: object) -> dict:
    """Build one Locationforecast compact timeseries entry."""
    details: dict = {"air_temperature": temp}
    if "wind_speed" in extra:
        details["wind_speed"] = extra["wind_speed"]
    if "wind_from_direction" in extra:
        details["wind_from_direction"] = extra["wind_from_direction"]
    if "cloud_area_fraction" in extra:
        details["cloud_area_fraction"] = extra["cloud_area_fraction"]
    data: dict = {"instant": {"details": details}}
    if "next_1_hours" in extra:
        data["next_1_hours"] = extra["next_1_hours"]
    if "next_6_hours" in extra:
        data["next_6_hours"] = extra["next_6_hours"]
    return {"time": iso_time, "data": data}


class BuildHourlyTest(unittest.TestCase):
    def test_next_1_hours_precip_and_symbol_land_on_their_own_hour(self) -> None:
        timeseries = [
            _point(
                "2026-09-07T10:00:00Z",
                10.0,
                cloud_area_fraction=50.0,
                next_1_hours={
                    "summary": {"symbol_code": "rain"},
                    "details": {"precipitation_amount": 1.2},
                },
            ),
        ]
        precip, cloud, meta = yr_forecast.build_hourly(timeseries, yr_forecast.TZ)
        t = common.local_dt("2026-09-07T10:00:00Z", yr_forecast.TZ)
        self.assertAlmostEqual(precip[t], 1.2)
        d = t.date()
        self.assertEqual(cloud[d][t.hour], 50.0)
        self.assertEqual(meta[d]["syms"], ["rain"])

    def test_next_6_hours_precip_is_spread_evenly_across_its_window(self) -> None:
        timeseries = [
            _point(
                "2026-09-07T06:00:00Z",
                8.0,
                next_6_hours={
                    "summary": {"symbol_code": "cloudy"},
                    "details": {"precipitation_amount": 6.0},
                },
            ),
        ]
        precip, _cloud, _meta = yr_forecast.build_hourly(timeseries, yr_forecast.TZ)
        t0 = common.local_dt("2026-09-07T06:00:00Z", yr_forecast.TZ)
        for h in range(6):
            self.assertAlmostEqual(precip[t0 + timedelta(hours=h)], 1.0)

    def test_min_max_and_day_window_aggregation(self) -> None:
        timeseries = [
            _point("2026-09-07T04:00:00Z", 2.0),  # local 06:00, still counts for min/max
            _point("2026-09-07T12:00:00Z", 20.0),  # local 14:00, daytime (10-18)
        ]
        _precip, _cloud, meta = yr_forecast.build_hourly(timeseries, yr_forecast.TZ)
        t_first = common.local_dt("2026-09-07T04:00:00Z", yr_forecast.TZ)
        t_day = common.local_dt("2026-09-07T12:00:00Z", yr_forecast.TZ)
        d = t_first.date()
        rec = meta[d]
        self.assertEqual(rec["min"], 2.0)
        self.assertEqual(rec["max"], 20.0)
        self.assertIn(20.0, rec["day_temps"])
        self.assertEqual(rec["first"], t_first.hour)
        self.assertEqual(rec["last"], t_day.hour)

    def test_exclude_night_drops_pre_6am_hours_from_min_max(self) -> None:
        timeseries = [
            _point("2026-09-07T01:00:00Z", -5.0),  # local 03:00, before 06:00 -> excluded
            _point("2026-09-07T12:00:00Z", 15.0),  # local 14:00, included
        ]
        _precip, _cloud, meta = yr_forecast.build_hourly(timeseries, yr_forecast.TZ, exclude_night=True)
        d = common.local_dt("2026-09-07T01:00:00Z", yr_forecast.TZ).date()
        rec = meta[d]
        # Only the local-14:00 point (hour >= 6) contributes when exclude_night is set.
        self.assertEqual(rec["min"], 15.0)
        self.assertEqual(rec["max"], 15.0)


class IntervalsTest(unittest.TestCase):
    def test_compresses_contiguous_true_hours_into_stop_exclusive_runs(self) -> None:
        state = {h: (8 <= h < 11 or 14 <= h < 16) for h in range(24)}
        runs = yr_forecast.intervals(state, None)
        self.assertEqual(runs, [(8, 11), (14, 16)])

    def test_run_touching_hour_23_extends_to_stop_24(self) -> None:
        state = {h: h >= 22 for h in range(24)}
        runs = yr_forecast.intervals(state, None)
        self.assertEqual(runs, [(22, 24)])

    def test_mask_further_restricts_which_hours_count_as_on(self) -> None:
        state = {h: True for h in range(24)}
        runs = yr_forecast.intervals(state, lambda h: 10 <= h < 12)
        self.assertEqual(runs, [(10, 12)])


class IvStrTest(unittest.TestCase):
    def test_formats_runs_as_bracketed_zero_padded_ranges(self) -> None:
        self.assertEqual(yr_forecast.iv_str([(8, 11), (22, 24)]), "[08-11] [22-24]")

    def test_empty_runs_formats_as_empty_string(self) -> None:
        self.assertEqual(yr_forecast.iv_str([]), "")


class RoundHalfUpTest(unittest.TestCase):
    def test_rounds_half_up_not_bankers_rounding(self) -> None:
        self.assertEqual(common.round_half_up(12.5), 13)
        self.assertEqual(common.round_half_up(12.4), 12)

    def test_negative_half_rounds_away_from_zero_toward_negative(self) -> None:
        self.assertEqual(common.round_half_up(-2.5), -3)


def _assert_near_zero_mod_360(case: unittest.TestCase, value: float) -> None:
    # circular_mean's %360.0 wrap can land the near-zero result at exactly
    # 360.0 (float precision) instead of 0.0 -- both mean "due north".
    case.assertAlmostEqual(min(value, 360.0 - value), 0.0, places=6)


class CircularMeanTest(unittest.TestCase):
    def test_wraps_correctly_across_zero_degrees(self) -> None:
        _assert_near_zero_mod_360(self, yr_forecast.circular_mean([350, 10]))

    def test_naive_mean_would_be_wrong_for_the_same_input(self) -> None:
        # Sanity check the fixture actually demonstrates the wrap-around case
        # circular_mean exists for: a naive arithmetic mean gives 180, not 0.
        self.assertAlmostEqual(sum([350, 10]) / 2, 180.0)
        _assert_near_zero_mod_360(self, yr_forecast.circular_mean([350, 10]))


class WindArrowTest(unittest.TestCase):
    def test_wind_from_north_blows_toward_south(self) -> None:
        self.assertEqual(common.wind_arrow(0.0), "↓")

    def test_wind_from_south_blows_toward_north(self) -> None:
        self.assertEqual(common.wind_arrow(180.0), "↑")


class WeatherTest(unittest.TestCase):
    def _rec(self, **overrides: object) -> dict:
        rec = {"syms": [], "day_syms": []}
        rec.update(overrides)
        return rec

    def test_heavy_rain_threshold_wins_over_symbol_data(self) -> None:
        rec = self._rec(day_syms=["clearsky_day"])
        self.assertEqual(yr_forecast.weather(rec, rain_total=8.0), yr_forecast.SYMBOLS["heavyrain"])

    def test_moderate_rain_threshold(self) -> None:
        rec = self._rec()
        self.assertEqual(yr_forecast.weather(rec, rain_total=2.0), yr_forecast.SYMBOLS["rain"])

    def test_light_rain_below_moderate_threshold(self) -> None:
        rec = self._rec()
        self.assertEqual(yr_forecast.weather(rec, rain_total=0.5), yr_forecast.SYMBOLS["lightrain"])

    def test_dry_day_tie_break_prefers_clearer_sky_via_dry_rank(self) -> None:
        # clearsky_day and cloudy tied 1-1; _DRY_RANK ranks clearsky_day higher.
        rec = self._rec(day_syms=["clearsky_day", "cloudy"])
        self.assertEqual(yr_forecast.weather(rec, rain_total=0.0), yr_forecast.SYMBOLS["clearsky_day"])

    def test_dry_day_falls_back_to_cloudy_when_no_symbols_present(self) -> None:
        rec = self._rec()
        self.assertEqual(yr_forecast.weather(rec, rain_total=0.0), yr_forecast.SYMBOLS["cloudy"])


if __name__ == "__main__":
    unittest.main()
