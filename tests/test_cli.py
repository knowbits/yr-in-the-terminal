from __future__ import annotations

import argparse
import unittest
from unittest import mock

from rich.text import Text

from yr_in_the_terminal import cli


def _args(
    lat=None, lon=None, place=None, location=None, set_location=None, here=False, command="today"
) -> argparse.Namespace:
    return argparse.Namespace(
        lat=lat, lon=lon, place=place, location=location, set_location=set_location, here=here, command=command
    )


class ResolveLocationTest(unittest.TestCase):
    def test_no_location_anywhere_is_a_hard_error_with_no_ip_geolocation_guess(self) -> None:
        args = _args()
        with mock.patch("yr_in_the_terminal.common.resolve_default_location") as resolve_default:
            error = cli.resolve_location(args, {})
        self.assertEqual(error, cli.NO_LOCATION_ERROR)
        # No silent IP-geolocation fallback -- only --here opts into that.
        resolve_default.assert_not_called()

    def test_explicit_lat_lon_wins_over_everything(self) -> None:
        args = _args(lat=1.0, lon=2.0, location="Oslo", here=True)
        error = cli.resolve_location(args, {"location": {"place": "Nowhere"}})
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon), (1.0, 2.0))

    def test_explicit_lat_lon_without_place_gets_a_coordinate_label(self) -> None:
        args = _args(lat=1.0, lon=2.0)
        error = cli.resolve_location(args, {})
        self.assertIsNone(error)
        self.assertEqual(args.place, "1.0, 2.0")

    def test_location_flag_geocodes(self) -> None:
        args = _args(location="Sykkylven")
        with mock.patch("yr_in_the_terminal.common.geocode_candidates", return_value=[(1.0, 2.0, "Sykkylven, Norge")]):
            error = cli.resolve_location(args, {})
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon, args.place), (1.0, 2.0, "Sykkylven, Norge"))

    def test_location_flag_ambiguous_lists_all_candidates(self) -> None:
        args = _args(location="Toreplassen")
        candidates = [
            (62.5874, 9.4879, "Toreplassen, Oppdal"),
            (62.3863, 6.4117, "Toreplassen, Kurset"),
        ]
        with mock.patch("yr_in_the_terminal.common.geocode_candidates", return_value=candidates):
            error = cli.resolve_location(args, {})
        self.assertIsNotNone(error)
        self.assertIn("ambiguous", error)
        self.assertIn("Toreplassen, Oppdal", error)
        self.assertIn("Toreplassen, Kurset", error)
        # Doesn't guess one -- lat/lon stay unset.
        self.assertIsNone(args.lat)

    def test_location_flag_failure_does_not_consult_config(self) -> None:
        args = _args(location="Nonexistentplacexyz123")
        config = {"location": {"place": "Configured Place"}}
        # --location failing is a hard error -- it doesn't fall through to
        # the config's [location] or guess via IP geolocation.
        with mock.patch("yr_in_the_terminal.common.geocode_candidates", return_value=[]):
            error = cli.resolve_location(args, config)
        self.assertIsNotNone(error)

    def test_config_location_used_when_nothing_else_given(self) -> None:
        args = _args()
        config = {"location": {"place": "Springfield"}}
        with mock.patch("yr_in_the_terminal.common.geocode", return_value=(3.0, 4.0, "Springfield, Illinois")) as geo:
            error = cli.resolve_location(args, config)
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon, args.place), (3.0, 4.0, "Springfield, Illinois"))
        geo.assert_called_once_with("Springfield", config=config)

    def test_config_location_failure_is_a_hard_error(self) -> None:
        args = _args()
        config = {"location": {"place": "Nonexistentplacexyz123"}}
        with mock.patch("yr_in_the_terminal.common.geocode", return_value=None):
            error = cli.resolve_location(args, config)
        self.assertIsNotNone(error)
        self.assertIn("no location given", error)

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

    def test_here_flag_never_persists_the_guessed_location(self) -> None:
        args = _args(here=True)
        with (
            mock.patch("yr_in_the_terminal.common.resolve_default_location", return_value=(5.0, 6.0, "Somewhere")),
            mock.patch("yr_in_the_terminal.common.set_config_location") as set_location,
        ):
            cli.resolve_location(args, {})
        set_location.assert_not_called()

    def test_set_location_flag_geocodes_and_persists(self) -> None:
        args = _args(set_location="Sykkylven")
        with (
            mock.patch("yr_in_the_terminal.common.geocode_candidates", return_value=[(1.0, 2.0, "Sykkylven, Norge")]),
            mock.patch("yr_in_the_terminal.common.set_config_location") as set_location,
        ):
            error = cli.resolve_location(args, {})
        self.assertIsNone(error)
        self.assertEqual((args.lat, args.lon, args.place), (1.0, 2.0, "Sykkylven, Norge"))
        set_location.assert_called_once_with("Sykkylven, Norge")

    def test_set_location_flag_ambiguous_does_not_persist(self) -> None:
        args = _args(set_location="Toreplassen")
        candidates = [
            (62.5874, 9.4879, "Toreplassen, Oppdal"),
            (62.3863, 6.4117, "Toreplassen, Kurset"),
        ]
        with (
            mock.patch("yr_in_the_terminal.common.geocode_candidates", return_value=candidates),
            mock.patch("yr_in_the_terminal.common.set_config_location") as set_location,
        ):
            error = cli.resolve_location(args, {})
        self.assertIsNotNone(error)
        self.assertIn("--set-location", error)
        set_location.assert_not_called()

    def test_set_location_flag_failure_does_not_persist(self) -> None:
        args = _args(set_location="Nonexistentplacexyz123")
        with (
            mock.patch("yr_in_the_terminal.common.geocode_candidates", return_value=[]),
            mock.patch("yr_in_the_terminal.common.set_config_location") as set_location,
        ):
            cli.resolve_location(args, {})
        set_location.assert_not_called()


class AddBorderTest(unittest.TestCase):
    def test_frames_a_single_line_with_rounded_corners(self) -> None:
        framed = cli.add_border("hi", padding=1, color="yellow")
        lines = framed.splitlines()
        self.assertEqual(lines[0], "[yellow]╭────╮[/yellow]")
        self.assertEqual(lines[1], "[yellow]│[/yellow] hi [yellow]│[/yellow]")
        self.assertEqual(lines[2], "[yellow]╰────╯[/yellow]")

    def test_pads_shorter_lines_to_the_widest_line(self) -> None:
        framed = cli.add_border("a\nbbb", padding=1)
        lines = framed.splitlines()
        # Every rendered row -- including the shorter "a" line -- lines up
        # under the same top/bottom border width (rendered, not raw, width:
        # the markup tags themselves add differing raw lengths per line).
        widths = [Text.from_markup(line).cell_len for line in lines]
        self.assertEqual(widths, [widths[0]] * len(widths))

    def test_trailing_whitespace_does_not_widen_the_frame(self) -> None:
        # "a  \t " has trailing whitespace well past "bbb" -- it must not
        # make the frame any wider than "bbb" (+ padding) demands.
        framed = cli.add_border("a  \t \nbbb", padding=1)
        top, a_line, bbb_line, _bottom = framed.splitlines()
        self.assertEqual(Text.from_markup(top).cell_len, Text.from_markup(bbb_line).cell_len)
        self.assertEqual(a_line, "[yellow]│[/yellow] a   [yellow]│[/yellow]")

    def test_markup_tags_dont_widen_the_frame(self) -> None:
        # "[bold green]hi[/bold green]" renders as just "hi" (cell_len 2) --
        # the frame must be sized off that, not the raw markup-tagged string.
        plain = cli.add_border("hi", padding=1)
        markup = cli.add_border("[bold green]hi[/bold green]", padding=1)
        plain_top, markup_top = plain.splitlines()[0], markup.splitlines()[0]
        self.assertEqual(plain_top, markup_top)


if __name__ == "__main__":
    unittest.main()
