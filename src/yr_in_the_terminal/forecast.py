"""7-day weather forecast table from yr.no (MET Norway).

Fetches Locationforecast 2.0 (compact) and Sunrise 3.0, aggregates to one row
per day, and renders a coloured table via Rich.

Default location: Hundeidvik, Sykkylven, Norway.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.table import Table
from rich.text import Text

from yr_in_the_terminal import common

FORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
FORECAST_TTL = 45 * 60

TZ = ZoneInfo("Europe/Oslo")

# Rain threshold (mm) above which an hour counts as "raining".
RAIN_MM = 0.05

# symbol_code -> (emoji, label). Prefix match on the base (day/night) is used.
SYMBOLS = {
    "clearsky_day": ("☀️", "Sunny"),
    "clearsky_night": ("🌙", "Clear"),
    "fair_day": ("🌤️", "Fair"),
    "fair_night": ("🌙", "Fair"),
    "partlycloudy_day": ("⛅", "Partly cloudy"),
    "partlycloudy_night": ("☁️", "Partly cloudy"),
    "cloudy": ("☁️", "Cloudy"),
    "fog": ("🌫️", "Fog"),
    "lightrain": ("🌦️", "Light rain"),
    "drizzle": ("🌦️", "Drizzle"),
    "rain": ("🌧️", "Rain"),
    "heavyrain": ("⛈️", "Heavy rain"),
    "rainshowers_day": ("🌦️", "Showers"),
    "rainshowers_night": ("🌧️", "Showers"),
    "sleet": ("🌨️", "Sleet"),
    "snow": ("❄️", "Snow"),
}


def build_hourly(timeseries: list[dict], tz: ZoneInfo, exclude_night: bool = False) -> tuple[dict, dict, dict]:
    """Return (precip per local hour, cloud per (day, hour), daily meta)."""
    precip = defaultdict(float)  # datetime -> mm
    cloud = defaultdict(dict)  # date -> {hour: cloud_pct}
    meta: dict = {}  # date -> {min,max,syms,day_syms,first,last}

    for p in timeseries:
        t = common.local_dt(p["time"], tz)
        data = p["data"]
        d = t.date()

        rec = meta.setdefault(
            d,
            {
                "min": None,
                "max": None,
                "syms": [],
                "day_syms": [],
                "day_temps": [],
                "wind_min": None,
                "wind_max": None,
                "day_winds": [],
                "day_wind_dirs": [],
                "first": 23,
                "last": 0,
            },
        )
        rec["first"] = min(rec["first"], t.hour)
        rec["last"] = max(rec["last"], t.hour)

        details = data["instant"]["details"]
        tmp = details["air_temperature"]
        if not exclude_night or t.hour >= 6:
            rec["min"] = tmp if rec["min"] is None else min(rec["min"], tmp)
            rec["max"] = tmp if rec["max"] is None else max(rec["max"], tmp)
        if 10 <= t.hour < 18:
            rec["day_temps"].append(tmp)

        ws = details.get("wind_speed")
        wd = details.get("wind_from_direction")
        if ws is not None and (not exclude_night or t.hour >= 6):
            rec["wind_min"] = ws if rec["wind_min"] is None else min(rec["wind_min"], ws)
            rec["wind_max"] = ws if rec["wind_max"] is None else max(rec["wind_max"], ws)
        if 10 <= t.hour < 18:
            if ws is not None:
                rec["day_winds"].append(ws)
            if wd is not None:
                rec["day_wind_dirs"].append(wd)

        cf = details.get("cloud_area_fraction")
        n1 = data.get("next_1_hours")

        # Hourly precipitation: next_1_hours where available, else spread
        # next_6_hours evenly over its 6-hour window.
        if n1 is not None:
            amt = n1.get("details", {}).get("precipitation_amount")
            if amt is not None:
                precip[t] += amt
            sym = n1.get("summary", {}).get("symbol_code")
            dur = 1
        else:
            n6 = data.get("next_6_hours", {})
            amt = n6.get("details", {}).get("precipitation_amount")
            if amt is not None:
                for h in range(6):
                    precip[t + timedelta(hours=h)] += amt / 6.0
            sym = n6.get("summary", {}).get("symbol_code")
            dur = 6

        if sym:
            rec["syms"].append(sym)
            if 6 <= t.hour < 20:
                rec["day_syms"].append(sym)

        if cf is not None:
            for h in range(dur):
                cloud[d][(t.hour + h) % 24] = cf

    return precip, cloud, meta


def intervals(state: dict, mask) -> list[tuple[int, int]]:
    """Compress hour->bool into [(start, stop), ...] using stop-exclusive hours."""
    runs, start = [], None
    for h in range(24):
        on = bool(state.get(h)) and (mask(h) if mask else True)
        if on and start is None:
            start = h
        elif not on and start is not None:
            runs.append((start, h))
            start = None
    if start is not None:
        runs.append((start, 24))
    return runs


def iv_str(runs: list[tuple[int, int]]) -> str:
    def t(h: int) -> str:
        return "24" if h == 24 else f"{h:02d}"

    return " ".join(f"[{t(s)}-{t(e)}]" for s, e in runs)


def circular_mean(angles: list[float]) -> float:
    """Mean of angles (degrees), wrapping correctly across 0/360."""
    x = sum(math.cos(math.radians(a)) for a in angles)
    y = sum(math.sin(math.radians(a)) for a in angles)
    return math.degrees(math.atan2(y, x)) % 360.0


# Ranking for resolving dry-day symbol ties: clearer sky wins.
_DRY_RANK = {
    "clearsky_day": 5,
    "fair_day": 4,
    "partlycloudy_day": 3,
    "clearsky_night": 2,
    "fair_night": 1,
    "partlycloudy_night": 0,
    "cloudy": -1,
    "fog": -2,
}


def weather(rec: dict, rain_total: float) -> tuple[str, str]:
    """Pick a representative (emoji, label) for the day."""
    if rain_total >= 8:
        return SYMBOLS["heavyrain"]
    if rain_total >= 2:
        return SYMBOLS["rain"]
    if rain_total > 0:
        return SYMBOLS["lightrain"]
    # Dry day: dominant daytime symbol, clearer sky breaks ties.
    pool = rec["day_syms"] or rec["syms"]
    if pool:
        counts = Counter(pool)
        top = counts.most_common(1)[0][1]
        best = max(
            (s for s, c in counts.items() if c == top),
            key=lambda s: _DRY_RANK.get(s, -99),
        )
        return SYMBOLS.get(best, SYMBOLS["cloudy"])
    return SYMBOLS["cloudy"]


def build_rows(lat: float, lon: float, n_days: int, exclude_night: bool = False) -> list[dict]:
    global TZ
    TZ = common.resolve_tz(lat, lon)
    fc = common.fetch_json(FORECAST_URL, {"lat": str(lat), "lon": str(lon)}, ttl=FORECAST_TTL)
    precip, cloud, meta = build_hourly(fc["properties"]["timeseries"], TZ, exclude_night)

    def in_window(h: int) -> bool:
        return not exclude_night or h >= 6

    rows = []
    for d in sorted(meta)[:n_days]:
        rec = meta[d]
        rain_total = sum(v for t, v in precip.items() if t.date() == d and in_window(t.hour))

        sun = common.sunrise_sunset(datetime(d.year, d.month, d.day, tzinfo=TZ), lat, lon, TZ)

        # Rainy hours: reconstructed precip above threshold.
        rain_state = {}
        for t, v in precip.items():
            if t.date() == d and v >= RAIN_MM and in_window(t.hour):
                rain_state[t.hour] = True
        rain_iv = intervals(rain_state, None)

        # Sunny hours: daylight hours with cloud cover below threshold. A
        # sunrise/sunset lookup failure degrades to an empty sun column
        # rather than crashing the whole 7-day table.
        if sun is not None:
            rise, set_ = sun
            rise_h = rise.hour + rise.minute / 60.0
            set_h = set_.hour + set_.minute / 60.0
            sun_state = {h: (cloud[d].get(h, 100) < common.SUN_CLOUD_PCT) for h in range(24)}
            sun_iv = intervals(
                sun_state,
                lambda h: rise_h <= h and (h + 1) <= set_h and in_window(h),
            )
        else:
            sun_iv = []

        partial = rec["first"] > 6 or rec["last"] < 18
        emoji, label = weather(rec, rain_total)
        day_temps = rec["day_temps"]
        avg = common.round_half_up(sum(day_temps) / len(day_temps)) if day_temps else None
        wind_min = common.round_half_up(rec["wind_min"]) if rec["wind_min"] is not None else None
        wind_max = common.round_half_up(rec["wind_max"]) if rec["wind_max"] is not None else None
        wind_avg = common.round_half_up(sum(rec["day_winds"]) / len(rec["day_winds"])) if rec["day_winds"] else None
        wind_dir = common.wind_arrow(circular_mean(rec["day_wind_dirs"])) if rec["day_wind_dirs"] else ""

        rows.append(
            {
                "date": d,
                "partial": partial,
                "emoji": emoji,
                "label": label,
                "low": rec["min"],
                "high": rec["max"],
                "avg": avg,
                "rain": rain_total,
                "rain_iv": rain_iv,
                "sun_iv": sun_iv,
                "wind_min": wind_min,
                "wind_max": wind_max,
                "wind_avg": wind_avg,
                "wind_dir": wind_dir,
            }
        )
    return rows


def render(rows: list[dict], place: str, exclude_night: bool = False) -> None:
    console = Console()
    table = Table()
    table.add_column("Day", style="bold")
    table.add_column("Weather")
    table.add_column(Text("Temp [avg] (°C)"), justify="left")
    table.add_column("Rain (mm)", justify="right")
    table.add_column("☔ Rain", justify="left")
    table.add_column("☀️ Sun", justify="left")
    table.add_column(Text("Wind [avg] (m/s)"), justify="left")

    def time_cell(runs: list[tuple[int, int]]) -> Text:
        if not runs:
            return Text("")
        hours = sum(e - s for s, e in runs)
        txt = Text()
        txt.append(f"{hours:>2d}h ")
        txt.append(iv_str(runs), style="bright_black")
        return txt

    def wind_cell(r: dict) -> Text:
        if r["wind_min"] is None or r["wind_max"] is None:
            return Text("")
        txt = Text(f"{r['wind_min']} – {r['wind_max']}")
        if r["wind_avg"] is not None:
            txt.append(f" [{r['wind_avg']} {r['wind_dir']}]")
        return txt

    partial_days = []
    for r in rows:
        day = f"{r['date']:%a} {r['date'].day:>2}"
        if r["partial"]:
            partial_days.append(day)
        low = common.round_half_up(r["low"])
        high = common.round_half_up(r["high"])
        temp = f"{low:>2d}°–{high:>2d}°"
        if r["avg"] is not None:
            temp += f" [{r['avg']:>2d}°]"
        table.add_row(
            day + ("*" if r["partial"] else ""),
            f"{r['emoji']} {r['label']}",
            temp,
            f"{r['rain']:.1f}mm" if r["rain"] > 0 else "",
            time_cell(r["rain_iv"]),
            time_cell(r["sun_iv"]),
            wind_cell(r),
        )

    header = Text(f"{place} — 7-day forecast (yr.no)", style="bold")
    if exclude_night:
        header.append(" [NIGHT EXCLUDED, 00.00-06.00]", style="bold red")
    console.print(header)
    console.print(table)
    console.print(Text("[avg]: the average day temperature between 10.00 to 18.00", style="bright_black"))
    if partial_days:
        console.print(
            f"[bright_black]* {', '.join(partial_days)}: partial day — forecast run "
            "does not cover the full 24 h.[/bright_black]"
        )
    console.print(
        "[bright_black]Rain/Sun time: contiguous hours; "
        "Sun = daylight hours with cloud cover < "
        f"{common.SUN_CLOUD_PCT}%.[/bright_black]"
    )


def build_json_payload(rows: list[dict], place: str, lat: float, lon: float) -> dict:
    return {
        "place": place,
        "lat": lat,
        "lon": lon,
        "days": [
            {
                "date": r["date"].isoformat(),
                "partial": r["partial"],
                "symbol": f"{r['emoji']} {r['label']}",
                "temp_low_c": r["low"],
                "temp_high_c": r["high"],
                "temp_avg_c": r["avg"],
                "rain_mm": r["rain"],
                "rain_hours": r["rain_iv"],
                "sun_hours": r["sun_iv"],
                "wind_min_ms": r["wind_min"],
                "wind_max_ms": r["wind_max"],
                "wind_avg_ms": r["wind_avg"],
                "wind_dir": r["wind_dir"],
            }
            for r in rows
        ],
    }


def run(args: argparse.Namespace) -> int:
    try:
        rows = build_rows(args.lat, args.lon, args.days, args.exclude_night)
    except urllib.error.URLError as exc:
        print(f"error: could not reach yr.no: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(build_json_payload(rows, args.place, args.lat, args.lon)))
        return 0

    render(rows, args.place, args.exclude_night)
    return 0
