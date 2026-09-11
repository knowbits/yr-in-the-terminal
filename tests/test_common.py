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

    def test_network_failure_returns_none(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("unreachable")):
            result = common.geocode("Hundeidvik", cache_dir=self.cache_dir)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
