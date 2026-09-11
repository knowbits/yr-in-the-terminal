from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from yr_in_the_terminal import common


class FetchJsonCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = Path(self._tmp.name)
        common.set_cache_enabled(True)

    def test_second_call_within_ttl_hits_cache(self) -> None:
        calls = []

        def fake_urlopen(req, timeout=20):
            calls.append(1)
            cm = mock.MagicMock()
            cm.__enter__.return_value = mock.MagicMock()
            cm.__exit__.return_value = False
            return cm

        with (
            mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
            mock.patch("json.load", return_value={"ok": True}),
        ):
            first = common.fetch_json("https://x/test", {"a": "1"}, ttl=300, cache_dir=self.cache_dir)
            second = common.fetch_json("https://x/test", {"a": "1"}, ttl=300, cache_dir=self.cache_dir)

        self.assertEqual(first, {"ok": True})
        self.assertEqual(second, {"ok": True})
        self.assertEqual(len(calls), 1)

    def test_ttl_expiry_triggers_refetch(self) -> None:
        calls = []

        def fake_urlopen(req, timeout=20):
            calls.append(1)
            cm = mock.MagicMock()
            cm.__enter__.return_value = mock.MagicMock()
            cm.__exit__.return_value = False
            return cm

        times = iter([1000.0, 2000.0, 2000.0])
        with (
            mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
            mock.patch("json.load", return_value={"ok": True}),
            mock.patch("time.time", side_effect=lambda: next(times)),
        ):
            common.fetch_json("https://x/test", {"a": "1"}, ttl=300, cache_dir=self.cache_dir)
            common.fetch_json("https://x/test", {"a": "1"}, ttl=300, cache_dir=self.cache_dir)

        self.assertEqual(len(calls), 2)

    def test_corrupt_cache_file_falls_back_to_live_fetch(self) -> None:
        cache_file = common._cache_path(self.cache_dir, "https://x/test", {"a": "1"})
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not json{{{")

        def fake_urlopen(req, timeout=20):
            cm = mock.MagicMock()
            cm.__enter__.return_value = mock.MagicMock()
            cm.__exit__.return_value = False
            return cm

        with (
            mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
            mock.patch("json.load", return_value={"ok": True}),
        ):
            result = common.fetch_json("https://x/test", {"a": "1"}, ttl=300, cache_dir=self.cache_dir)

        self.assertEqual(result, {"ok": True})


class GeocodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = Path(self._tmp.name)
        common.set_cache_enabled(True)

    def test_resolves_first_match(self) -> None:
        results = [{"lat": "62.37", "lon": "6.42", "display_name": "Hundeidvik, Sykkylven, Norge"}]
        with mock.patch("urllib.request.urlopen"), mock.patch("json.load", return_value=results):
            result = common.geocode("Hundeidvik", cache_dir=self.cache_dir)
        self.assertEqual(result, (62.37, 6.42, "Hundeidvik, Sykkylven"))

    def test_no_match_returns_none(self) -> None:
        with mock.patch("urllib.request.urlopen"), mock.patch("json.load", return_value=[]):
            result = common.geocode("Nonexistentplacexyz123", cache_dir=self.cache_dir)
        self.assertIsNone(result)

    def test_candidates_deduplicates_near_identical_coordinates(self) -> None:
        # Two OSM entries for the same real-world Oppdal farm (a node and its
        # farmyard polygon, ~30m apart) plus a genuinely different Sykkylven
        # place sharing the name -- expect 2 candidates, not 3.
        results = [
            {"lat": "62.5874222", "lon": "9.4878556", "display_name": "Toreplassen, Oppdal, Trøndelag, Norge"},
            {"lat": "62.5874476", "lon": "9.4875781", "display_name": "Toreplassen, Oppdal, Trøndelag, Norge"},
            {"lat": "62.3863472", "lon": "6.4116530", "display_name": "Toreplassen, Kurset, Hundeidvik, Norge"},
        ]
        with mock.patch("urllib.request.urlopen"), mock.patch("json.load", return_value=results):
            candidates = common.geocode_candidates("Toreplassen", limit=5, cache_dir=self.cache_dir)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0], (62.5874222, 9.4878556, "Toreplassen, Oppdal"))
        self.assertEqual(candidates[1], (62.3863472, 6.411653, "Toreplassen, Kurset"))

    def test_candidates_merges_a_municipality_boundary_with_its_village_node(self) -> None:
        # A common Nominatim pattern: a municipality's administrative boundary
        # centroid and its village/town node land several km apart for the
        # same query -- not a genuine ambiguity, must not be reported as one.
        results = [
            {"lat": "62.3431", "lon": "6.6090", "display_name": "Sykkylven, Møre og Romsdal, Norge"},
            {"lat": "62.3929", "lon": "6.5807", "display_name": "Sykkylven, Møre og Romsdal, 6230, Norge"},
        ]
        with mock.patch("urllib.request.urlopen"), mock.patch("json.load", return_value=results):
            candidates = common.geocode_candidates("Sykkylven", limit=5, cache_dir=self.cache_dir)
        self.assertEqual(len(candidates), 1)

    def test_candidates_empty_on_no_match(self) -> None:
        with mock.patch("urllib.request.urlopen"), mock.patch("json.load", return_value=[]):
            candidates = common.geocode_candidates("Nonexistentplacexyz123", cache_dir=self.cache_dir)
        self.assertEqual(candidates, [])

    def test_network_failure_returns_none(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("unreachable")):
            result = common.geocode("Hundeidvik", cache_dir=self.cache_dir)
        self.assertIsNone(result)


class LoadConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "config.toml"

    def test_missing_file_with_no_default_returns_empty_dict(self) -> None:
        self.assertEqual(common.load_config(self.config_path), {})
        self.assertFalse(self.config_path.exists())

    def test_missing_file_is_created_from_default_toml(self) -> None:
        result = common.load_config(self.config_path, default_toml="[today]\nmin_hours = 12\n")
        self.assertEqual(result, {"today": {"min_hours": 12}})
        self.assertEqual(self.config_path.read_text(), "[today]\nmin_hours = 12\n")

    def test_existing_file_is_not_overwritten_by_default_toml(self) -> None:
        self.config_path.write_text("[today]\nmin_hours = 5\n")
        result = common.load_config(self.config_path, default_toml="[today]\nmin_hours = 12\n")
        self.assertEqual(result, {"today": {"min_hours": 5}})

    def test_valid_toml_parses(self) -> None:
        self.config_path.write_text("[today]\nmin_hours = 24\n")
        self.assertEqual(common.load_config(self.config_path), {"today": {"min_hours": 24}})

    def test_corrupt_toml_returns_empty_dict(self) -> None:
        self.config_path.write_text("not valid toml {{{")
        self.assertEqual(common.load_config(self.config_path), {})


class SetConfigLocationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "config.toml"

    def test_creates_file_from_default_template_if_missing(self) -> None:
        common.set_config_location("Oslo", self.config_path)
        config = common.load_config(self.config_path)
        self.assertEqual(config["location"]["place"], "Oslo")
        # The rest of the default template (other sections) still got created.
        self.assertIn("today", config)

    def test_replaces_commented_out_default(self) -> None:
        self.config_path.write_text('[location]\n# place = "Oslo"\n\n[today]\nmin_hours = 12\n')
        common.set_config_location("Bergen, Norway", self.config_path)
        config = common.load_config(self.config_path)
        self.assertEqual(config["location"]["place"], "Bergen, Norway")
        self.assertEqual(config["today"]["min_hours"], 12)

    def test_replaces_legacy_lat_lon_place_trio(self) -> None:
        self.config_path.write_text('[location]\nlat = 59.9139\nlon = 10.7522\nplace = "Oslo"\n\n[today]\n')
        common.set_config_location("Bergen, Norway", self.config_path)
        config = common.load_config(self.config_path)
        self.assertEqual(config["location"], {"place": "Bergen, Norway"})

    def test_updates_existing_place_in_place(self) -> None:
        self.config_path.write_text('[location]\nplace = "Oslo"\n')
        common.set_config_location("Bergen, Norway", self.config_path)
        self.assertEqual(common.load_config(self.config_path), {"location": {"place": "Bergen, Norway"}})

    def test_other_sections_and_comments_are_untouched(self) -> None:
        original = '[location]\nplace = "Oslo"\n\n[today]\n# a comment\nmin_hours = 12\n'
        self.config_path.write_text(original)
        common.set_config_location("Bergen, Norway", self.config_path)
        text = self.config_path.read_text()
        self.assertIn("# a comment", text)
        self.assertIn("min_hours = 12", text)

    def test_appends_section_if_missing_entirely(self) -> None:
        self.config_path.write_text("[today]\nmin_hours = 12\n")
        common.set_config_location("Oslo", self.config_path)
        config = common.load_config(self.config_path)
        self.assertEqual(config["location"], {"place": "Oslo"})
        self.assertEqual(config["today"]["min_hours"], 12)


if __name__ == "__main__":
    unittest.main()
