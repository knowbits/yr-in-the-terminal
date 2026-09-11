from __future__ import annotations

import io
import unittest
from datetime import datetime, timedelta

from rich.console import Console

from yr_in_the_terminal import today as yr_today


class RadarRainRangesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 7, 13, 12, tzinfo=yr_today.TZ)
        hour = self.now.replace(minute=0, second=0, microsecond=0)
        self.rows = [
            {
                "time": hour + timedelta(hours=i),
                "symbol": "rain",
                "temp": 14.0,
                "rain": 0.7,
                "rain_max": 2.2,
                "pop": 80.0,
                "wind_speed": 2.0,
                "wind_gust": 6.0,
                "wind_dir": 90.0,
                "cloud": 100.0,
            }
            for i in range(3)
        ]

    def test_all_radar_touched_rows_use_their_overlapping_samples(self) -> None:
        hour = self.rows[0]["time"]
        entries = [
            (hour + timedelta(minutes=5), 9.0),  # ends before now
            (hour + timedelta(minutes=10), 0.9),  # overlaps now
            (hour + timedelta(minutes=30), 0.2),
            (hour + timedelta(minutes=55), 1.3),
            (hour + timedelta(hours=1), 0.7),
            (hour + timedelta(hours=1, minutes=55), 2.2),
            (hour + timedelta(hours=2), 8.0),
        ]
        combined = {
            "times": [t for t, _ in entries],
            "rates": [rate for _, rate in entries],
            "rates_hi": [rate for _, rate in entries],
            "radar_n": len(entries),
        }

        result = yr_today.compute_radar_rain_ranges(self.rows, combined, self.now)

        # The third row has one radar slot, then falls back to its 0.7–2.2
        # hourly range for the remainder of that hour.
        self.assertEqual(result, {0: (0.2, 1.3), 1: (0.7, 2.2), 2: (0.7, 8.0)})

    def test_third_row_combines_radar_with_hourly_uncovered_tail(self) -> None:
        now = self.rows[0]["time"] + timedelta(minutes=55)
        entries = [
            (now, 4.0),
            (self.rows[1]["time"], 0.9),
            (self.rows[1]["time"] + timedelta(minutes=55), 0.0),
            (self.rows[2]["time"], 0.2),
            (self.rows[2]["time"] + timedelta(minutes=50), 1.5),
        ]
        combined = {
            "times": [t for t, _ in entries],
            "rates": [rate for _, rate in entries],
            "rates_hi": [rate for _, rate in entries],
            "radar_n": len(entries),
        }

        result = yr_today.compute_radar_rain_ranges(self.rows, combined, now)

        self.assertEqual(result[0], (4.0, 4.0))
        self.assertEqual(result[1], (0.0, 0.9))
        self.assertEqual(result[2], (0.2, 2.2))

    def test_table_uses_hourly_forecast_for_rows_without_radar(self) -> None:
        output = Console(file=io.StringIO(), record=True, width=100)

        yr_today.render_hourly_table(
            output,
            self.rows,
            showers={},
            sun=None,
            radar_rain_ranges={0: (0.2, 1.3), 1: (0.4, 1.8)},
        )

        text = output.export_text()
        self.assertIn("0.2–1.3", text)
        self.assertIn("0.4–1.8", text)
        self.assertIn("0.7–2.2", text)

    def test_headline_separates_strong_shower_from_lingering_light_rain(self) -> None:
        times = [
            self.now - timedelta(minutes=2),
            self.now + timedelta(minutes=3),
            self.now + timedelta(minutes=8),
            self.now + timedelta(minutes=53),
        ]
        rates = [4.0, 0.9, 0.2, 0.0]
        combined = {
            "times": times,
            "rates": rates,
            "rates_hi": rates,
            "radar_n": len(rates),
        }

        headline = yr_today.rain_headline(combined, self.rows, self.now).plain

        self.assertIn("Strong shower now (4.0 mm/h)", headline)
        self.assertIn("easing by 13:15 (~3 min)", headline)
        self.assertIn("Lighter rain continues until 14:05 (~53 min)", headline)


if __name__ == "__main__":
    unittest.main()
