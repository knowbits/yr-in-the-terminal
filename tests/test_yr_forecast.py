from __future__ import annotations

import unittest
from datetime import timedelta

from yr_in_the_terminal import common
from yr_in_the_terminal import forecast as yr_forecast


def _point(iso_time: str, temp: float, **extra: object) -> dict:
    """Build one Locationforecast timeseries entry."""
    details: dict = {"air_temperature": temp}
    if "wind_speed" in extra:
        details["wind_speed"] = extra["wind_speed"]
    if "wind_from_direction" in extra:
        details["wind_from_direction"] = extra["wind_from_direction"]
    if "wind_speed_of_gust" in extra:
        details["wind_speed_of_gust"] = extra["wind_speed_of_gust"]
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


class DayGustTest(unittest.TestCase):
    def _rec(self, timeseries: list[dict], **kwargs: bool) -> dict:
        _precip, _cloud, meta = yr_forecast.build_hourly(timeseries, yr_forecast.TZ, **kwargs)
        return meta[common.local_dt(timeseries[0]["time"], yr_forecast.TZ).date()]

    def test_reports_the_strongest_gust_of_a_fully_covered_day(self) -> None:
        rec = self._rec(
            [
                _point("2026-09-07T04:00:00Z", 5.0, wind_speed_of_gust=4.2),  # local 06:00
                _point("2026-09-07T12:00:00Z", 9.0, wind_speed_of_gust=11.6),  # local 14:00
                _point("2026-09-07T17:00:00Z", 7.0, wind_speed_of_gust=6.0),  # local 19:00
            ]
        )
        self.assertEqual(yr_forecast.day_gust(rec), 12)

    def test_blank_when_gust_coverage_ends_before_the_evening(self) -> None:
        # Gust data stops at local 10:00 but the day's forecast runs on to
        # 20:00 -- a morning-only maximum would understate the day.
        rec = self._rec(
            [
                _point("2026-09-07T08:00:00Z", 5.0, wind_speed_of_gust=8.0),  # local 10:00
                _point("2026-09-07T18:00:00Z", 5.0),  # local 20:00, no gust value
            ]
        )
        self.assertIsNone(yr_forecast.day_gust(rec))

    def test_blank_when_the_day_has_no_gust_values_at_all(self) -> None:
        rec = self._rec([_point("2026-09-07T12:00:00Z", 5.0)])
        self.assertIsNone(yr_forecast.day_gust(rec))

    def test_reported_when_gusts_cover_a_day_through_its_own_last_step(self) -> None:
        # The forecast run itself ends at local 14:00; gusts cover all of it.
        rec = self._rec([_point("2026-09-07T12:00:00Z", 5.0, wind_speed_of_gust=8.0)])
        self.assertEqual(yr_forecast.day_gust(rec), 8)

    def test_exclude_night_ignores_pre_6am_gusts(self) -> None:
        timeseries = [
            _point("2026-09-07T01:00:00Z", 5.0, wind_speed_of_gust=20.0),  # local 03:00
            _point("2026-09-07T17:00:00Z", 5.0, wind_speed_of_gust=6.0),  # local 19:00
        ]
        self.assertEqual(yr_forecast.day_gust(self._rec(timeseries, exclude_night=True)), 6)
        self.assertEqual(yr_forecast.day_gust(self._rec(timeseries)), 20)


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


class FormatTempCellsTest(unittest.TestCase):
    @staticmethod
    def _row(low: float, high: float, avg: int | None) -> dict:
        return {"low": low, "high": high, "avg": avg}

    def test_positive_values_get_a_sign_slot_space_so_the_comma_aligns(self) -> None:
        cells = yr_forecast.format_temp_cells([self._row(-1, 1, 1), self._row(-5, -1, -1)])
        self.assertEqual(cells, ["-1, 1 °C [ 1]", "-5,-1 °C [-1]"])

    def test_mixed_widths_are_right_aligned_per_position(self) -> None:
        cells = yr_forecast.format_temp_cells([self._row(-12, 0, -3), self._row(4, 11, 9), self._row(0, 2, None)])
        self.assertEqual(cells, ["-12,  0 °C [-3]", "  4, 11 °C [ 9]", "  0,  2 °C"])
        self.assertEqual(len({c.index(",") for c in cells}), 1)

    def test_zero_is_padded_like_a_signed_value_even_when_every_row_is_zero(self) -> None:
        cells = yr_forecast.format_temp_cells([self._row(0, 0, 0), self._row(0.2, -0.3, 0)])
        self.assertEqual(cells, [" 0, 0 °C [ 0]", " 0, 0 °C [ 0]"])

    def test_no_rows(self) -> None:
        self.assertEqual(yr_forecast.format_temp_cells([]), [])


if __name__ == "__main__":
    unittest.main()
