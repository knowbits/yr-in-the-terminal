from __future__ import annotations

import argparse
import unittest
from unittest import mock

from yr_in_the_terminal import cli


def _args(lat=None, lon=None, place=None, location=None, here=False) -> argparse.Namespace:
    return argparse.Namespace(lat=lat, lon=lon, place=place, location=location, here=here)


class ResolveLocationTest(unittest.TestCase):
    def test_no_location_anywhere_falls_back_to_ip_geolocation_with_a_warning(self) -> None:
        args = _args()
        with (
            mock.patch("yr_in_the_terminal.common.resolve_default_location", return_value=(1.0, 2.0, "Guessed Place")),
            mock.patch("yr_in_the_terminal.cli._warn_no_location_configured") as warn,
        ):
            error = cli.resolve_location(args, {})
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon, args.place), (1.0, 2.0, "Guessed Place"))
        warn.assert_called_once()

    def test_no_location_anywhere_and_ip_geolocation_also_fails_is_an_error(self) -> None:
        args = _args()
        with mock.patch("yr_in_the_terminal.common.resolve_default_location", return_value=None):
            error = cli.resolve_location(args, {})
        self.assertIsNotNone(error)
        self.assertIn("no location given", error)

    def test_explicit_lat_lon_wins_over_everything(self) -> None:
        args = _args(lat=1.0, lon=2.0, location="Oslo", here=True)
        error = cli.resolve_location(args, {"location": {"lat": 9.0, "lon": 9.0, "place": "Nowhere"}})
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon), (1.0, 2.0))

    def test_explicit_lat_lon_without_place_gets_a_coordinate_label(self) -> None:
        args = _args(lat=1.0, lon=2.0)
        error = cli.resolve_location(args, {})
        self.assertIsNone(error)
        self.assertEqual(args.place, "1.0, 2.0")

    def test_location_flag_geocodes(self) -> None:
        args = _args(location="Sykkylven")
        with mock.patch("yr_in_the_terminal.common.geocode", return_value=(1.0, 2.0, "Sykkylven, Norge")):
            error = cli.resolve_location(args, {})
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon, args.place), (1.0, 2.0, "Sykkylven, Norge"))

    def test_location_flag_failure_does_not_consult_config(self) -> None:
        args = _args(location="Nonexistentplacexyz123")
        config = {"location": {"lat": 3.0, "lon": 4.0, "place": "Configured Place"}}
        # --location failing skips straight to the IP-geolocation last resort
        # (not the config's [location]) -- confirm that by making it fail too.
        with (
            mock.patch("yr_in_the_terminal.common.geocode", return_value=None),
            mock.patch("yr_in_the_terminal.common.resolve_default_location", return_value=None),
        ):
            error = cli.resolve_location(args, config)
        self.assertIsNotNone(error)

    def test_config_location_used_when_nothing_else_given(self) -> None:
        args = _args()
        config = {"location": {"lat": 3.0, "lon": 4.0, "place": "Configured Place"}}
        error = cli.resolve_location(args, config)
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon, args.place), (3.0, 4.0, "Configured Place"))

    def test_here_flag_uses_ip_geolocation(self) -> None:
        args = _args(here=True)
        with mock.patch("yr_in_the_terminal.common.resolve_default_location", return_value=(5.0, 6.0, "Somewhere")):
            error = cli.resolve_location(args, {})
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon, args.place), (5.0, 6.0, "Somewhere"))

    def test_here_flag_failure_with_no_config_fallback_is_an_error(self) -> None:
        args = _args(here=True)
        with mock.patch("yr_in_the_terminal.common.resolve_default_location", return_value=None):
            error = cli.resolve_location(args, {})
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
