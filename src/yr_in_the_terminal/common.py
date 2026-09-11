"""Shared, stateless helpers used by both the `today` and `forecast` subcommands.

Unlike the two standalone scripts this package was extracted from, nothing
here reads a module-level `TZ` global -- every function that needs a
timezone takes it as an explicit `tz` argument, so importing this module
never risks silently defaulting to Oslo.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import tomllib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# yr.no fair-use terms require an identifying User-Agent header.
USER_AGENT = "yr-in-the-terminal/0.1 (personal use)"
SUNRISE_URL = "https://api.met.no/weatherapi/sunrise/3.0/sun"
TZ_URL = "https://timeapi.io/api/timezone/coordinate"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Cloud-cover fraction (%) below which the sun is considered to break through.
SUN_CLOUD_PCT = 75

# TTLs (seconds) for fetch_json's response cache, per endpoint. yr.no's
# fair-use policy asks API consumers to cache responses rather than re-fetch
# on every run -- these are the defaults. forecast/nowcast/alerts/geocode
# are overridable per-installation via the settings file's [cache] section
# (see cache_ttl()); sunrise/timezone resolution barely ever change and
# aren't exposed there.
SUNRISE_TTL = 12 * 3600
TZ_TTL = 3 * 24 * 3600
GEOCODE_TTL = 30 * 24 * 3600
FORECAST_TTL = 45 * 60
NOWCAST_TTL = 5 * 60
ALERTS_TTL = 20 * 60

# Compass arrows, index 0=N, 1=NE, ..., 7=NW.
WIND_ARROWS = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"]

# Set False by --no-cache to force every fetch_json call to bypass its cache
# for this invocation, regardless of the ttl each call site requests.
_CACHE_ENABLED = True


def set_cache_enabled(enabled: bool) -> None:
    global _CACHE_ENABLED
    _CACHE_ENABLED = enabled


def cache_ttl(config: dict, key: str, default: int) -> int:
    """TTL (seconds) for one [cache] setting from the settings file, falling
    back to `default` if unset. 0 disables caching for that key entirely
    (still subject to --no-cache/_CACHE_ENABLED, which forces 0 for all)."""
    return config.get("cache", {}).get(key, default)


def _default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "yr-in-the-terminal"


def _cache_path(cache_dir: Path, url: str, params: dict[str, str]) -> Path:
    key = hashlib.sha256(json.dumps([url, sorted(params.items())]).encode()).hexdigest()
    return cache_dir / f"{key}.json"


def fetch_json(url: str, params: dict[str, str], *, ttl: int = 0, cache_dir: Path | None = None) -> dict:
    ttl = ttl if _CACHE_ENABLED else 0
    cache_file = None
    if ttl > 0:
        cache_file = _cache_path(cache_dir or _default_cache_dir(), url, params)
        try:
            cached = json.loads(cache_file.read_text())
            if time.time() - cached["fetched_at"] < ttl:
                return cached["body"]
        except (OSError, ValueError, KeyError):
            pass

    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.load(resp)

    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"fetched_at": time.time(), "body": body}))
        except OSError:
            pass

    return body


DEFAULT_MIN_HOURS_AHEAD = 12

DEFAULT_CONFIG_TOML = f"""\
# yr-in-the-terminal settings. Edit values below, then re-run yr.

[location]
# Default place used when --lat/--lon, --location, and --here are all
# omitted on the command line. yr ships with no built-in location -- one of
# these (a flag, or this section) is required. Same format as --location: a
# place name resolved via OpenStreetMap Nominatim (cached, see geocode_ttl
# below) -- not saved by hand, `yr <command> --set-location "<name>"` writes
# it here for you.
# place = "Oslo"

[today]
# Minimum hours-ahead `yr today` shows when --hours is not given (rest of
# today, but never less than this).
min_hours = {DEFAULT_MIN_HOURS_AHEAD}

[cache]
# How long (seconds) a fetched response is reused before yr asks yr.no for
# fresh data again. yr.no's fair-use policy asks API consumers to cache
# responses rather than re-fetch on every run -- these are that policy's
# defaults. Set any of them to 0 to always fetch live for that source, or
# pass --no-cache on the command line to disable all caching for one run
# without editing this file.
forecast_ttl = {FORECAST_TTL} # Locationforecast (yr today + yr forecast); the model updates roughly hourly
nowcast_ttl = {NOWCAST_TTL} # Nowcast radar (yr today only); MET issues a new radar frame every 5 minutes
alerts_ttl = {ALERTS_TTL} # MET weather alerts (yr today only)
geocode_ttl = {GEOCODE_TTL} # --location place-name lookups; a place's coordinates don't change
"""


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "yr-in-the-terminal" / "config.toml"


def load_config(path: Path | None = None, *, default_toml: str = "") -> dict:
    """Load the user settings file, creating it from `default_toml` on first run
    if it doesn't exist yet. {} if unreadable/invalid, or missing with no
    `default_toml` given -- never raises."""
    config_path = path or default_config_path()
    if not config_path.exists() and default_toml:
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(default_toml)
        except OSError:
            pass
    try:
        with config_path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


_LOCATION_KEY_RE = re.compile(r"#?\s*(lat|lon|place)\s*=")


def set_config_location(place: str, path: Path | None = None) -> None:
    """Persist `place` (a plain name, resolved the same way --location
    resolves one) as the settings file's [location] default, so a later run
    with no --lat/--lon/--location/--here picks it up automatically.

    Rewrites only the [location] section's lat/lon/place lines (dropping the
    legacy lat/lon-based format if present, commented or not) with a single
    `place = "..."` line; every other section, comment, and the rest of the
    file's formatting is left untouched. Creates the file from
    DEFAULT_CONFIG_TOML first if it doesn't exist yet. Never raises --
    silently does nothing if the file can't be read or written.
    """
    config_path = path or default_config_path()
    if not config_path.exists():
        load_config(config_path, default_toml=DEFAULT_CONFIG_TOML)
    try:
        lines = config_path.read_text().splitlines(keepends=True)
    except OSError:
        return

    place_line = f'place = "{place}"\n'
    out: list[str] = []
    in_location = False
    found_section = inserted = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_location and not inserted:
                out.append(place_line)
                inserted = True
            in_location = stripped == "[location]"
            found_section = found_section or in_location
            out.append(line)
            continue
        if in_location and _LOCATION_KEY_RE.match(stripped):
            continue
        out.append(line)
    if in_location and not inserted:
        out.append(place_line)
    if not found_section:
        out.append(f"\n[location]\n{place_line}")

    try:
        config_path.write_text("".join(out))
    except OSError:
        pass


def local_dt(iso: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)


def utc_offset_str(d: datetime, tz: ZoneInfo) -> str:
    off = int(tz.utcoffset(d).total_seconds())
    sign = "+" if off >= 0 else "-"
    off = abs(off)
    return f"{sign}{off // 3600:02d}:{(off % 3600) // 60:02d}"


def resolve_default_location(
    lat: float | None, lon: float | None, place: str | None
) -> tuple[float, float, str] | None:
    """Best-effort IP geolocation for `--here`; falls back to the given
    lat/lon/place on failure, or None if there's no fallback to give either."""
    try:
        req = urllib.request.Request("https://ipapi.co/json/", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.load(resp)
        here_lat, here_lon = data["latitude"], data["longitude"]
        city, country = data.get("city"), data.get("country_name")
        here_place = ", ".join(p for p in (city, country) if p) or place or f"{here_lat}, {here_lon}"
        return float(here_lat), float(here_lon), here_place
    except Exception:
        if lat is not None and lon is not None:
            return lat, lon, place or f"{lat}, {lon}"
        return None


# Candidates within this many degrees (lat and lon both) of an already-kept
# one are treated as the same place, not a genuine ambiguity -- e.g. a
# municipality's boundary centroid and its village node routinely land a
# few km apart for the same Nominatim query. ~0.3 deg (~30km) comfortably
# covers that while still separating genuinely different, same-named places
# (there can be several "Toreplassen" in Norway, hundreds of km apart).
_SAME_PLACE_DEGREES = 0.3


def geocode_candidates(
    place: str, *, limit: int = 5, cache_dir: Path | None = None, config: dict | None = None
) -> list[tuple[float, float, str]]:
    """Resolve a place name to up to `limit` (lat, lon, display_name) matches
    via OpenStreetMap Nominatim, most-relevant first. [] on no match/failure.

    Candidates within _SAME_PLACE_DEGREES of an already-kept one are dropped
    as the same real-world place under a different OSM entry.
    """
    ttl = cache_ttl(config or {}, "geocode_ttl", GEOCODE_TTL)
    try:
        results = fetch_json(
            NOMINATIM_URL, {"q": place, "format": "json", "limit": str(limit)}, ttl=ttl, cache_dir=cache_dir
        )
        candidates: list[tuple[float, float, str]] = []
        for r in results:
            lat, lon = float(r["lat"]), float(r["lon"])
            if any(
                abs(lat - c_lat) < _SAME_PLACE_DEGREES and abs(lon - c_lon) < _SAME_PLACE_DEGREES
                for c_lat, c_lon, _ in candidates
            ):
                continue
            # display_name is verbose (e.g. "Voss, Vestland, Norge") -- the
            # first two comma-separated parts read like a concise
            # "<place>, <region>" label.
            label = ", ".join(r["display_name"].split(", ")[:2])
            candidates.append((lat, lon, label))
        return candidates
    except (OSError, ValueError, KeyError, IndexError):
        return []


def geocode(
    place: str, *, cache_dir: Path | None = None, config: dict | None = None
) -> tuple[float, float, str] | None:
    """Resolve a place name to its single best (lat, lon, display_name) match.

    Returns None on no match or any failure -- the caller decides the fallback
    (unlike resolve_default_location, this has no single "default" to fall
    back to on its own, since the place name was explicitly requested).
    """
    candidates = geocode_candidates(place, limit=1, cache_dir=cache_dir, config=config)
    return candidates[0] if candidates else None


def resolve_tz(lat: float, lon: float) -> ZoneInfo:
    """Resolve the IANA timezone for a location (timeapi.io); longitude fallback."""
    try:
        name = fetch_json(TZ_URL, {"latitude": str(lat), "longitude": str(lon)}, ttl=TZ_TTL).get("timeZone")
        if name:
            return ZoneInfo(name)
    except (OSError, ValueError):
        pass
    return timezone(timedelta(hours=round(lon / 15.0)))


def sunrise_sunset(d: datetime, lat: float, lon: float, tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    try:
        data = fetch_json(
            SUNRISE_URL,
            {
                "lat": str(lat),
                "lon": str(lon),
                "date": d.strftime("%Y-%m-%d"),
                "offset": utc_offset_str(d, tz),
            },
            ttl=SUNRISE_TTL,
        )
        props = data["properties"]
        rise = datetime.fromisoformat(props["sunrise"]["time"]).astimezone(tz)
        set_ = datetime.fromisoformat(props["sunset"]["time"]).astimezone(tz)
        return rise, set_
    except (OSError, KeyError, ValueError):
        return None


def round_half_up(x: float) -> int:
    """Round to nearest int; .5 and above rounds up (12.4 -> 12, 12.5 -> 13)."""
    return int(x + (0.5 if x >= 0 else -0.5))


def wind_arrow(from_deg: float) -> str:
    """Compass arrow pointing in the direction the wind blows TOWARD."""
    to_deg = (from_deg + 180.0) % 360.0
    return WIND_ARROWS[round(to_deg / 45.0) % 8]
