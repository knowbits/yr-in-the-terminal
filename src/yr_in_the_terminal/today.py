"""Detailed TODAY weather forecast from yr.no (MET Norway).

Companion to `forecast.py`, focused on today instead of the week ahead:

  * An hour-by-hour table covering the rest of today, styled like
    forecast.py's daily table. Rain ranges use the 5-minute Nowcast radar
    samples throughout its ~2-hour horizon, including the third clock-hour
    row when appropriate; rows or row portions beyond it use Locationforecast
    2.0 /complete's one-value-per-hour forecast.
  * A high-resolution, radar-based rain chart for the next ~2 hours
    (Nowcast 2.0 /complete): 5-minute precipitation bars, y = mm/h, x = time,
    extended a further ~2h by smoothly blending toward the hourly model data
    (dimmer bars, clearly divided from the radar zone) so the chart doesn't
    jump abruptly at the 2h seam.

yr.no resolution note: Nowcast 2.0 is the only sub-hourly product MET Norway
publishes, and it only exists because it is built from weather radar imagery
(the "map/radar functionality" the forecast pages show) rather than the
hourly numerical model used everywhere else. It covers ~2 hours ahead at
5-minute steps, Nordic countries only (422 error elsewhere). Locationforecast
itself never goes below hourly steps, even in its "complete" variant, so
beyond the radar window there is no real minute-level product, and no way to
derive one: a single point's rain time series plus a wind reading cannot
yield a rain-area's movement vector, because velocity of a spatial pattern
requires spatial (multi-point/gridded) data, which these APIs don't expose.
The "blend" zone therefore smooths the *presentation* of the existing hourly
forecast -- itself already MET's physics-based model of how precipitation
systems move and evolve -- rather than inventing new precision. It is styled
and marked distinctly (dim bars, a divider, "~" on approximate times) so
that's visible rather than implied.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from rich import box
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from yr_in_the_terminal import common

FORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
NOWCAST_URL = "https://api.met.no/weatherapi/nowcast/2.0/complete"
ALERTS_URL = "https://api.met.no/weatherapi/metalerts/2.0/current.json"

FORECAST_TTL = 45 * 60
NOWCAST_TTL = 5 * 60
ALERTS_TTL = 20 * 60

TZ = ZoneInfo("Europe/Oslo")

# Precipitation rate (mm/h) at/above which a 5-min nowcast slot counts as "raining".
RAIN_RATE_MM_H = 0.1
# Presentation threshold for calling the current radar signal a strong shower.
# This matches the chart's 2–6 mm/h intensity band rather than claiming an
# official MET Norway warning category.
STRONG_SHOWER_RATE_MM_H = 2.0
# Number of near-term hours highlighted in the hourly table as "high confidence".
NEAR_TERM_HOURS = 4

# MET alert riskMatrixColor -> Rich style.
ALERT_COLORS = {
    "green": "green",
    "yellow": "yellow",
    "orange": "dark_orange",
    "red": "bold red",
}

# symbol_code -> (day emoji, night emoji, label). Looked up by substring, so it
# also matches the many compound codes (heavyrainshowersandthunder_day, etc.)
# that Locationforecast/Nowcast return beyond the handful of exact codes.
SYMBOLS = {
    "clearsky": ("☀️", "🌙", "Clear"),
    "fair": ("🌤️", "🌙", "Fair"),
    "partlycloudy": ("⛅", "☁️", "Partly cloudy"),
    "cloudy": ("☁️", "☁️", "Cloudy"),
    "fog": ("🌫️", "🌫️", "Fog"),
    "thunder": ("⛈️", "⛈️", "Thunder"),
    "sleet": ("🌨️", "🌨️", "Sleet"),
    "snow": ("❄️", "❄️", "Snow"),
    "heavyrain": ("🌧️", "🌧️", "Heavy rain"),
    "lightrain": ("🌦️", "🌧️", "Light rain"),
    "drizzle": ("🌦️", "🌧️", "Drizzle"),
    "rainshower": ("🌦️", "🌧️", "Showers"),
    "showers": ("🌦️", "🌧️", "Showers"),
    "rain": ("🌧️", "🌧️", "Rain"),
}
# Ordered so a compound code like "heavyrainshowers" matches "heavyrain"
# before the more generic "rain" / "showers" entries.
_SYMBOL_ORDER = [
    "thunder",
    "sleet",
    "snow",
    "heavyrain",
    "lightrain",
    "drizzle",
    "rainshower",
    "showers",
    "rain",
    "fog",
    "clearsky",
    "fair",
    "partlycloudy",
    "cloudy",
]


def get_symbol(code: str | None) -> tuple[str, str]:
    """Return (emoji, label) for a symbol_code, tolerant of unseen variants."""
    if not code:
        return ("❔", "Unknown")
    c = code.lower()
    is_night = c.endswith("_night")
    for key in _SYMBOL_ORDER:
        if key in c:
            day_e, night_e, label = SYMBOLS[key]
            return (night_e if is_night else day_e, label)
    return ("❔", code)


def format_latlon(lat: float, lon: float) -> str:
    """Compact degrees + minutes, e.g. (59.9139, 10.7522) -> '59°55'N, 10°45'E'."""

    def dm(value: float, pos: str, neg: str) -> str:
        hemi = pos if value >= 0 else neg
        value = abs(value)
        deg = int(value)
        minutes = round((value - deg) * 60)
        if minutes == 60:  # rounding carry, e.g. 61.999' -> 62deg 0'
            deg += 1
            minutes = 0
        return f"{deg}°{minutes:02d}'{hemi}"

    return f"{dm(lat, 'N', 'S')}, {dm(lon, 'E', 'W')}"


# ---------------------------------------------------------------------------
# Hour-by-hour table (Locationforecast /complete)
# ---------------------------------------------------------------------------


def build_hourly_rows(lat: float, lon: float, n_hours: int, now: datetime) -> list[dict]:
    fc = common.fetch_json(FORECAST_URL, {"lat": str(lat), "lon": str(lon)}, ttl=FORECAST_TTL)
    ts = fc["properties"]["timeseries"]
    cutoff = now.replace(minute=0, second=0, microsecond=0)

    rows: list[dict] = []
    prev_t: datetime | None = None
    for p in ts:
        t = common.local_dt(p["time"], TZ)
        if t < cutoff:
            continue
        # Locationforecast steps from hourly to 3-/6-hourly resolution further
        # out; stop once we leave true hour-by-hour data.
        if prev_t is not None and (t - prev_t) != timedelta(hours=1):
            break
        if len(rows) >= n_hours:
            break

        data = p["data"]
        details = data["instant"]["details"]
        n1 = data.get("next_1_hours", {})
        n1d = n1.get("details", {})
        rows.append(
            {
                "time": t,
                "symbol": n1.get("summary", {}).get("symbol_code"),
                "temp": details.get("air_temperature"),
                "feels": details.get("apparent_air_temperature"),
                "rain": n1d.get("precipitation_amount"),
                "rain_max": n1d.get("precipitation_amount_max"),
                "pop": n1d.get("probability_of_precipitation"),
                "wind_speed": details.get("wind_speed"),
                "wind_gust": details.get("wind_speed_of_gust"),
                "wind_dir": details.get("wind_from_direction"),
                "cloud": details.get("cloud_area_fraction"),
                "pressure": details.get("air_pressure_at_sea_level"),
            }
        )
        prev_t = t
    return rows


def _pop_style(pop: float | None) -> str | None:
    if pop is None:
        return None
    if pop >= 50:
        return "bold yellow"
    if pop >= 20:
        return "yellow"
    return None


def is_sunny_hour(r: dict, sun: tuple[datetime, datetime] | None) -> bool:
    if not sun:
        return False
    rise, set_ = sun
    return rise <= r["time"] < set_ and r.get("cloud") is not None and r["cloud"] < common.SUN_CLOUD_PCT


def render_hourly_table(
    console: Console,
    rows: list[dict],
    showers: dict[int, str],
    sun: tuple[datetime, datetime] | None,
    radar_rain_ranges: dict[int, tuple[float, float]] | None = None,
) -> None:
    table = Table(box=box.ROUNDED, border_style="bright_black", pad_edge=False)
    table.add_column("Hour", style="bold")
    table.add_column("Weather", no_wrap=True)
    table.add_column("Temp", justify="right", no_wrap=True)
    table.add_column("Sun", justify="center")
    table.add_column("Rain (mm)", justify="right")
    table.add_column("Rain %", justify="right")
    table.add_column("Wind (m/s)", no_wrap=True)

    for i, r in enumerate(rows):
        emoji, label = get_symbol(r["symbol"])
        near = i < NEAR_TERM_HOURS
        row_style = "bold" if near else None
        hour_cell = f"{r['time']:%H:%M}"

        temp = f"{common.round_half_up(r['temp']):>3d}°" if r["temp"] is not None else ""

        radar_range = radar_rain_ranges.get(i) if radar_rain_ranges else None
        if radar_range is not None:
            # Use the much finer 5-minute radar nowcast wherever its moving
            # ~2-hour horizon overlaps a row.  The final, partially covered
            # row also includes the hourly range for its uncovered tail.
            rain_min, rain_max = radar_range
            rain_val = rain_min
            rain = f"{rain_min:.1f}"
            if rain_max > rain_min:
                rain += f"–{rain_max:.1f}"
        else:
            rain_val = r["rain"] or 0.0
            rain = f"{r['rain']:.1f}" if r["rain"] and r["rain"] > 0 else ""
            if r["rain_max"] is not None and r["rain_max"] > rain_val:
                rain += f"–{r['rain_max']:.1f}" if rain else f"0.0–{r['rain_max']:.1f}"
        # One line, always -- the lead-time marker (if any) prefixes the mm
        # range rather than wrapping onto its own row.
        rain_cell = Text(justify="right")
        if i in showers:
            rain_cell.append(showers[i] + (" " if rain else ""), style="bold cyan")
        if rain:
            rain_cell.append(rain, style=_bar_color(rain_val))

        pop = f"{common.round_half_up(r['pop'])}%" if r["pop"] is not None else ""
        pop_cell = Text(pop, style=_pop_style(r["pop"]), justify="right")

        sun_cell = "☀️" if is_sunny_hour(r, sun) else ""

        wind = ""
        if r["wind_speed"] is not None:
            wind = f"{r['wind_speed']:.0f}"
            if r["wind_gust"] is not None and r["wind_gust"] > r["wind_speed"] + 1:
                wind += f" ({r['wind_gust']:.0f})"
            if r["wind_dir"] is not None:
                wind += f" {common.wind_arrow(r['wind_dir'])}"

        table.add_row(
            hour_cell,
            f"{emoji} {label}",
            temp,
            sun_cell,
            rain_cell,
            pop_cell,
            wind,
            style=row_style,
        )

    console.print(table)
    console.print(
        Text(
            "Rain % = chance of any rain that hour",
            style="bright_black",
        )
    )


# ---------------------------------------------------------------------------
# Radar-based rain nowcast chart (Nowcast 2.0, ~2h at 5-min resolution)
# ---------------------------------------------------------------------------


def build_nowcast(lat: float, lon: float) -> dict | None:
    try:
        data = common.fetch_json(NOWCAST_URL, {"lat": str(lat), "lon": str(lon)}, ttl=NOWCAST_TTL)
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            return None  # outside Nordic radar coverage
        raise

    props = data["properties"]
    ts = props["timeseries"]
    entries: list[tuple[datetime, float]] = []
    for p in ts:
        t = common.local_dt(p["time"], TZ)
        rate = p["data"]["instant"]["details"].get("precipitation_rate")
        if rate is not None:
            entries.append((t, rate))

    first_data = ts[0]["data"] if ts else {}
    snapshot = first_data.get("instant", {}).get("details", {})
    next1 = first_data.get("next_1_hours", {})

    return {
        "coverage": props.get("meta", {}).get("radar_coverage"),
        "updated_at": props.get("meta", {}).get("updated_at"),
        "entries": entries,
        "snapshot": snapshot,
        "next1_symbol": next1.get("summary", {}).get("symbol_code"),
        "next1_amount": next1.get("details", {}).get("precipitation_amount"),
    }


def bool_runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Compress a bool list into [(start_idx, stop_idx)] runs, stop-exclusive."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


BAR_COL_WIDTH = 2
CHART_GUTTER = 9  # "12.0mm/h " width -- left margin up to the chart's y-axis
CHART_ROWS_PER_NOTCH = 4  # character rows between one labelled gridline and the next
_BLOCKS = " ▁▂▃▄▅▆▇█"  # 0..8 eighths, filled from the row's own floor -- for blend's area fill
# A radar reading is a point, not a filled area: it needs a thin one-eighth-row
# *line* sitting at its own precise height, not a block filled up to it. Block
# Elements alone only has the top and bottom of these 8 (U+2594 "UPPER ONE
# EIGHTH BLOCK", U+2581 "LOWER ONE EIGHTH BLOCK") -- the middle six rows come
# from the newer Symbols for Legacy Computing block (U+1FB76-U+1FB7B,
# "HORIZONTAL ONE EIGHTH BLOCK-2".."-7"), which fill in every eighth-row
# position in between. Ordered index 0..7 = bottom-most eighth .. top-most
# eighth, i.e. index = level - 1 where level is a row-relative offset (see
# radar_marker below).
_LINE_EIGHTHS = "▁🭻🭺🭹🭸🭷🭶▔"
_NICE_SCALES = [0.2, 0.5, 1, 2, 4, 8, 16, 32, 64]

# How far past the radar-based nowcast window to extend the chart using a
# smoothed blend toward the hourly model data, and at what step.
BLEND_HOURS_AHEAD = 2.0
BLEND_STEP_MIN = 15


def _bar_color(rate: float) -> str:
    if rate < 0.5:
        return "steel_blue"
    if rate < 2:
        return "dodger_blue2"
    if rate < 6:
        return "blue1"
    return "bold bright_blue"


def build_blend(
    last_anchor: tuple[datetime, float],
    hourly_rows: list[dict],
    hours_ahead: float = BLEND_HOURS_AHEAD,
    step_min: int = BLEND_STEP_MIN,
) -> list[tuple[datetime, float, float]]:
    """Extend the radar nowcast's last point with the plain hourly forecast.

    Not radar extrapolation -- pure translation-extrapolation of a radar echo
    loses skill fast beyond ~1-3h and Locationforecast's hourly figures
    already come from the full NWP model, which accounts for growth/decay of
    the rain system rather than just its current motion. There is no real
    data here beyond that hourly forecast: each forecast hour is drawn as a
    single flat plateau at that hour's own rain rate -- not ramped/smoothed
    toward its neighbours, since real rain is usually steady for a stretch
    rather than rising and falling in a straight line -- and shown as its
    actual min-max range (the same precipitation_amount/_max range the hourly
    table shows for that hour), rather than collapsing it into one number.
    step_min only sets the column granularity the plateau is drawn at; it
    adds no precision beyond what the hourly figure itself represents.
    """
    start_t, start_rate = last_anchor
    end_t = start_t + timedelta(hours=hours_ahead)

    points: list[tuple[datetime, float, float]] = []
    t = start_t + timedelta(minutes=step_min)
    while t <= end_t + timedelta(seconds=1):
        # Flat plateau at whichever forecast hour this sub-point falls in --
        # never interpolated toward a neighbouring hour.
        row = next((r for r in hourly_rows if r["time"] <= t < r["time"] + timedelta(hours=1)), None)
        lo = row.get("rain") if row else None
        if lo is None:
            # No forecast hour covers this point -- hold flat at the radar's
            # last real reading rather than fabricate a trend.
            lo = hi = start_rate
        else:
            hi = row.get("rain_max")
            hi = hi if hi is not None and hi > lo else lo
        points.append((t, lo, hi))
        t += timedelta(minutes=step_min)
    return points


def build_rain_chart(
    nowcast: dict, combined: dict, headline: Text, now: datetime, max_width: int | None = None
) -> Group | None:
    """Build the rain chart's body.

    Always shows the timeline -- a flat, single green line when dry rather
    than vanishing, so the chart stays a constant landmark in the output.
    Returns None only when the nowcast itself returned no data at all.
    """
    times = combined["times"]
    rates = combined["rates"]
    rates_hi = combined["rates_hi"]
    radar_n = combined["radar_n"]
    if not times:
        return None

    max_rate = max(rates_hi)

    gutter = CHART_GUTTER

    # A terminal character is the finest resolution there is -- it can't be
    # subdivided, so once there isn't one character per real data point left,
    # several consecutive points have to share a single character. Bar
    # widths still must be time-proportional between the two zones (a radar
    # point is 5 real minutes, a blend point is 15), so the available
    # character budget is split between them by real minutes first, then
    # each zone is independently fitted to its share: one proportional run
    # of characters per point while there's room (unchanged from before), or
    # several points merged into one character once there isn't.
    n_blend = len(rates) - radar_n
    radar_minutes = 5 * radar_n
    blend_minutes = 15 * n_blend
    total_minutes = radar_minutes + blend_minutes
    if max_width is not None:
        # -2 for the "┤"/"└" axis glyph itself; -2 more for the " t" axis
        # title trailing the baseline -- both live outside the bar area but
        # still have to fit within max_width, or the line wraps.
        avail_chars = max(1, max_width - gutter - 2 - 2)
    else:
        avail_chars = BAR_COL_WIDTH * (radar_n + 3 * n_blend)  # unconstrained: no squeeze needed
    # The x-axis always draws 8 fixed 30-min intervals (see target_mins
    # below). Independent per-tick rounding can only ever get every gap to
    # within +-1 character of each other -- never exactly equal, unless the
    # drawable width itself is a multiple of 8. So round it down to one:
    # every interval then gets the exact same integer width, zero jitter,
    # at the cost of at most 7 unused trailing columns. (Only when the
    # window is the nominal 240 min, i.e. radar/blend coverage wasn't cut
    # short -- otherwise 8 intervals don't map onto whole-number minutes
    # anyway, and this would just waste width for no gain.)
    if total_minutes == 240:
        avail_chars -= avail_chars % 8
    if total_minutes > 0:
        radar_chars = round(avail_chars * radar_minutes / total_minutes)
        if n_blend > 0:
            radar_chars = min(max(radar_chars, 1), max(avail_chars - 1, 1))
        blend_chars = max(0, avail_chars - radar_chars)
    else:
        radar_chars, blend_chars = avail_chars, 0

    def fit_to_chars(n: int, chars: int) -> list[tuple[int, int]]:
        """Partition n points across `chars` characters, whichever way there's
        more of: chars>=n -> each point's own (start, end) run of characters
        (possibly several); chars<n -> each character's own (start, end)
        run of points to merge into that one character."""
        if n == 0 or chars <= 0:
            return []
        bounds = [round(i * chars / n) for i in range(n + 1)] if chars >= n else None
        if bounds is not None:
            return [(bounds[i], bounds[i + 1]) for i in range(n)]
        bounds = [round(c * n / chars) for c in range(chars + 1)]
        return [(bounds[c], max(bounds[c + 1], bounds[c] + 1)) for c in range(chars)]

    # Radar columns: expand (chars>=n) -> point i's own run, unmerged, its
    # real reading unchanged. Squeeze (chars<n) -> a run of points merged by
    # taking the mean of their real 5-min readings, since that's genuinely
    # the same deterministic quantity read several times -- a real average
    # of real values, not a fabricated one.
    radar_cols: list[tuple[int, float, float]] = []  # (width, lo=0, rate)
    if radar_chars >= radar_n:
        for i, (start, end) in enumerate(fit_to_chars(radar_n, radar_chars)):
            if end > start:
                radar_cols.append((end - start, 0.0, rates[i]))
    else:
        for start, end in fit_to_chars(radar_n, radar_chars):
            group = rates[start:end]
            radar_cols.append((1, 0.0, sum(group) / len(group)))

    # Blend columns: expand -> each hour's own plateau, unmerged. Squeeze ->
    # merging two different hours' ranges is not an average (that would just
    # reintroduce the fabricated smoothing already ruled out) -- it's the
    # union of what's known: the lowest of their floors and the highest of
    # their ceilings, still real numbers from the forecast, just spanning a
    # wider stretch of it in one character.
    # An hour only floats (fills from its min up to its max, not from the
    # ground) when it actually has a real min-max spread; an hour with no
    # spread (hi == lo, e.g. a confident dry hour) is just as much "a single
    # known value" as a radar point, so it renders the same way -- solid
    # from the ground -- rather than as a misleading sliver hovering with an
    # empty gap beneath it.
    blend_lo = [lo if hi > lo else 0.0 for lo, hi in zip(rates[radar_n:], rates_hi[radar_n:])]
    blend_cols: list[tuple[int, float, float]] = []  # (width, lo, hi)
    if blend_chars >= n_blend:
        for j, (start, end) in enumerate(fit_to_chars(n_blend, blend_chars)):
            if end > start:
                blend_cols.append((end - start, blend_lo[j], rates_hi[radar_n + j]))
    else:
        for start, end in fit_to_chars(n_blend, blend_chars):
            blend_cols.append((1, min(blend_lo[start:end]), max(rates_hi[radar_n + start : radar_n + end])))

    columns = radar_cols + blend_cols
    col_is_blend = [False] * len(radar_cols) + [True] * len(blend_cols)
    total_width = sum(w for w, _, _ in columns)

    lines: list[Text] = []

    # Never zero the scale, even when dry -- that just leaves every bar at
    # height 0, which draws as a plain empty grid: exactly the "simple x/y
    # axis" wanted, no separate flat-line special case needed.
    scale = next((n for n in _NICE_SCALES if n >= max_rate), max_rate) if max_rate > 0 else _NICE_SCALES[0]
    # Notches (labelled gridlines) match the scale -- scale=4.0 gets 4 of
    # them, at 0/1/2/3/4 -- but each notch-to-notch gap is several character
    # rows tall, not one, so the curve still has real room to move between
    # whole-mm/h lines instead of jumping a full row at a time.
    notches = max(1, round(scale))
    data_rows = notches * CHART_ROWS_PER_NOTCH  # rows actually spanning (0, scale] of real value
    notch_step = scale / notches
    max_units = data_rows * 8

    # One extra row is reserved below all of those, purely so "0.0" gets a
    # notch of its own spaced the same CHART_ROWS_PER_NOTCH apart from "1.0"
    # as every later pair of notches -- print_rows = data_rows + 1. Every
    # printed row's *value* is therefore offset by one row from its data:
    # print-row 1 = value 0 (no data range of its own, just the "0.0"
    # boundary + wherever a radar reading rounds down to zero); print-row R
    # (R >= 2) = the same (R-1)-th data band as before the shift.
    print_rows = data_rows + 1

    def to_units(r: float) -> int:
        return max(0, min(max_units, round(r / scale * max_units)))

    def row_label(row: int) -> str:
        # A notch sits at this row's *top* edge -- print-row R's top edge is
        # (R-1)/CHART_ROWS_PER_NOTCH notches up from 0 (the -1 for the
        # reserved zero row), so only rows where (R-1) is an exact multiple
        # of CHART_ROWS_PER_NOTCH land on one -- row 1 included, giving
        # "0.0" the same notch-to-notch spacing as every later pair. No
        # "mm/h" on each line -- the unit is stated once, at the top axis.
        if (row - 1) % CHART_ROWS_PER_NOTCH == 0:
            return f"{((row - 1) // CHART_ROWS_PER_NOTCH) * notch_step:>4.1f}".rjust(gutter)
        return " " * gutter

    # A radar reading is a point, not an area -- it draws as a single
    # one-eighth-row-tall *line* (_LINE_EIGHTHS), not a block filled up
    # from the row's floor like blend's area does: nothing above or below
    # it. That gives it the same 8-level-per-row precision as blend's
    # fill, without implying a filled range that isn't there. (row, level)
    # mirrors the blend fill's own row_floor split: row_floor = (row - 2)
    # * 8 for row >= 2, so the row containing su_hi is
    # row = (su_hi - 1) // 8 + 2, and level -- su_hi's offset above that
    # row's own floor, 1..8, never 0 -- picks which of the 8 line glyphs
    # within that row. A confirmed-dry reading (su_hi == 0) gets no marker
    # at all: an empty column reads as "no rain here", vs. merging into
    # the "0.0" gridline (row 1, which a real reading -- su_hi >= 1 --
    # never reaches; the lowest it can land is the bottom-most line in
    # row 2, immediately above that gridline) if it drew there too.
    # Columns are independent, single points -- no interpolation or
    # diagonal/tilted glyph is drawn between one column's marker and the
    # next, even when they land on different rows or sub-row levels.
    radar_marker: dict[int, tuple[int, int]] = {}  # column index -> (row, level 1..8)
    for i, (is_blend, (w, lo, hi)) in enumerate(zip(col_is_blend, columns)):
        if is_blend:
            continue
        su_hi = to_units(hi)
        if su_hi > 0:
            row = (su_hi - 1) // 8 + 2
            level = su_hi - (row - 2) * 8
            radar_marker[i] = (min(print_rows, row), level)

    # Unit stated once, above the axis -- not repeated on every notch below.
    lines.append(Text("mm/h".rjust(gutter + 1), style="bright_black"))
    for row in range(print_rows, 0, -1):
        line = Text(row_label(row), style="bright_black")
        line.append("┤", style="bright_black")
        for i, (is_blend, (w, lo, hi)) in enumerate(zip(col_is_blend, columns)):
            if is_blend:
                # Blend never reaches row 1 -- that row is reserved for the
                # "0.0" notch and radar's own zero marker; a blend area
                # starting at zero already bottoms out correctly at row 2
                # (the true (0, one-row-worth] band), same as before the
                # shift. Floating fill: the segment's bottom edge is snapped
                # down to the nearest row boundary (block glyphs only fill
                # from a row's own floor), so a row entirely below it stays
                # blank rather than filled -- the one deliberate rounding
                # this rendering makes.
                if row == 1:
                    level = 0
                else:
                    row_floor = (row - 2) * 8
                    su_lo, su_hi = to_units(lo), to_units(hi)
                    lo_row_floor = (su_lo // 8) * 8
                    level = 0 if row_floor < lo_row_floor else max(0, min(8, su_hi - row_floor))
                ch = (_BLOCKS[level] if level else " ") * w
                if level == 0:
                    line.append(ch)
                else:
                    line.append(ch, style=f"dim {_bar_color(hi)}")
            else:
                marker = radar_marker.get(i)
                if marker is not None and marker[0] == row:
                    line.append(_LINE_EIGHTHS[marker[1] - 1] * w, style=_bar_color(hi))
                else:
                    line.append(" " * w)
        lines.append(line)

    # X-axis: one tick every 30 real minutes across the whole nominal 4h
    # window (0, 30, ..., 240) -- a single uniform interval, so with bars
    # now genuinely time-proportional, notch-to-notch spacing is identical
    # everywhere. The window's actual last data point can fall a few
    # minutes short of the nominal 240 (radar/blend rounding); the "4h"
    # target still snaps to whatever the closest real point is, exactly
    # like every other target, so the final notch is never dropped.
    ref_t = times[0]

    def rel_label(rel_min: int) -> str:
        if rel_min <= 0:
            return f"{ref_t:%H:%M}"
        return f"{rel_min / 60:g}h"

    target_mins = list(range(0, 241, 30))
    #
    # The final tick (240 = the right edge of the very last bar) lands
    # exactly at column `total_width` -- one past the last valid bar index,
    # since it marks a boundary, not a bar. Reserve that one extra column
    # so it isn't clamped short, which would make just the last gap smaller
    # than the rest.
    axis_width = total_width + 1
    # "now" (t=0) sits at column 0, immediately right of "└", with no gap of
    # its own to compensate for -- so every tick, "now" included, uses the
    # exact same formula. (An earlier version shifted every non-"now" tick
    # left by one column to compensate for "└" -- that was only needed back
    # when "now" itself had no tick; now that it does, the same shift just
    # pushed every later tick, including the final one, one column short.)
    #
    # Columns are distributed across the 8 fixed intervals by cumulative
    # rounding (the same technique fit_to_chars uses above for bar columns),
    # not by rounding each tick's real-elapsed-time column independently.
    # Independent rounding drifts unevenly -- worse, whenever the window's
    # actual total_minutes falls short of the nominal 240 (radar/blend
    # coverage cut short), the last tick's naive column overshoots the
    # drawable width and gets clamped, shrinking just the final gap. Cumulative
    # rounding instead spreads any unevenness at most 1 character across all
    # gaps, and is exactly even whenever axis_width - 1 divides evenly by 8.
    n_ticks = len(target_mins) - 1
    tick_col = {t: round(i * (axis_width - 1) / n_ticks) for i, t in enumerate(target_mins)}

    # Every interval gets a notch on the baseline, including "now" (t=0):
    # the "└" corner is the y-axis's own un-plottable cell (the buffer, not
    # data), so the notch marking where the drawable x-range actually
    # starts belongs one column to its right, same as every later notch.
    base_chars = ["─"] * axis_width
    for t, col in tick_col.items():
        base_chars[col] = "┬"
    # The final tick (4h) is a real notch too, with its own label below it
    # just like every other target -- so it keeps the same downward-pointing
    # "┬" rather than a closing corner, which would draw no notch at all.
    baseline = Text(" " * gutter, style="bright_black")
    baseline.append("└" + "".join(base_chars), style="bright_black")
    baseline.append(" t", style="bright_black")  # axis title, mirroring "mm/h" atop the y-axis
    lines.append(baseline)

    # Labels are centered on their notch's absolute column in the full
    # printed line -- including "now", which centers on its own notch (the
    # first drawable column) rather than on the y-axis's own un-plottable
    # corner, same as every other label.
    full_len = gutter + 1 + axis_width
    axis_full = [" "] * full_len
    last_end = -2  # so a label starting at column 0 isn't skipped
    for target in target_mins:
        label = rel_label(target)
        center = gutter + 1 + tick_col[target]
        start = max(0, center - len(label) // 2)
        if start + len(label) > full_len:
            start = full_len - len(label)
        if start < 0 or start <= last_end + 1:
            continue  # too close to the previous label, or would run off the edge
        for j, ch in enumerate(label):
            axis_full[start + j] = ch
        last_end = start + len(label) - 1
    lines.append(Text("".join(axis_full), style="bright_black"))
    lines.append(Text(""))

    # Footnote below the chart, indented so
    # "First"/"Last" start right under the chart's y-axis ("┤"/"└"), with
    # each row's own two fields -- (label, zone description) then (its
    # precipitation estimate) -- column-aligned to the other row's.
    indent = " " * gutter
    row1_label, row1_desc = "First 2h: ", "Nowcast radar (5 minute resolution)."
    row2_label, row2_desc = "Last  2h: ", "Yr's standard hourly forecast."
    est_col = max(len(row1_label) + len(row1_desc), len(row2_label) + len(row2_desc)) + 1
    lines.append(
        Text(
            f"{indent}{row1_label}{row1_desc}".ljust(len(indent) + est_col)
            + "Estimate for precipitation: an exact value.",
            style="bright_black",
        )
    )
    lines.append(
        Text(
            f"{indent}{row2_label}{row2_desc}".ljust(len(indent) + est_col)
            + "Estimate for precipitation: a min-max range.",
            style="bright_black",
        )
    )

    lines.append(Text(""))
    lines.append(headline)
    lines.append(Text(""))

    # This same "when does it start/stop" info is already in the hour-by-hour
    # table's "↦" arrows -- no separate zone-by-zone summary duplicating it
    # here.
    if nowcast.get("coverage") and nowcast["coverage"] != "ok":
        lines.append(Text(f"(radar coverage: {nowcast['coverage']} — reduced confidence)", style="yellow"))

    return Group(*lines)


def span_min_str(times: list[datetime]) -> str:
    mins = round((times[-1] - times[0]).total_seconds() / 60) + 5
    return f"{mins}min" if mins < 60 else f"{mins / 60:.1f}h"


def build_combined_rain(nowcast: dict | None, hourly_rows: list[dict]) -> dict | None:
    """Radar entries + hourly-plateau blend as one series, for the headline and chart.

    "rates" is the representative rate at each point (radar: its exact
    reading; blend: the hourly forecast's own precipitation_amount, i.e. the
    same number the hourly table shows). "rates_hi" is only the top of the
    range for blend points (precipitation_amount_max) -- equal to "rates"
    for radar points, which have no range at all.
    """
    if not nowcast or not nowcast.get("entries"):
        return None
    entries = nowcast["entries"]
    radar_times = [t for t, _ in entries]
    radar_rates = [r for _, r in entries]
    radar_n = len(entries)
    blend = build_blend(entries[-1], hourly_rows)
    return {
        "times": radar_times + [t for t, _, _ in blend],
        "rates": radar_rates + [lo for _, lo, _ in blend],
        "rates_hi": radar_rates + [hi for _, _, hi in blend],
        "radar_n": radar_n,
    }


def match_showers_to_hours(hourly_rows: list[dict], combined: dict | None, now: datetime) -> dict[int, str]:
    """Map radar/blend-detected rain runs onto the hourly rows they fall in.

    Surfaces a compact lead-time marker, e.g. "(🕐 2h00m)", alongside the
    "Rain (mm)" figure on the one row where the shower actually starts --
    always shown there, one line, never suppressed by whatever the coarse
    hourly total happens to say. Only the start row gets it (not every row
    a multi-hour run happens to overlap), so a long rain spell doesn't
    stamp the same lead time across several hours.
    """
    if combined is None:
        return {}
    times, rates = combined["times"], combined["rates"]
    wet = [r >= RAIN_RATE_MM_H for r in rates]
    notes: dict[int, str] = {}
    for s, e in bool_runs(wet):
        start_t = times[s]
        lead_min = round((start_t - now).total_seconds() / 60)
        if lead_min <= 2:
            note = "↦ now"
        else:
            h, m = divmod(max(0, lead_min), 60)
            note = f"↦ {h}h{m:02d}m" if h else f"↦ {m}m"
        for i, r in enumerate(hourly_rows[:NEAR_TERM_HOURS]):
            hour_start = r["time"]
            hour_end = hour_start + timedelta(hours=1)
            if hour_start <= start_t < hour_end and i not in notes:
                notes[i] = note
                break  # only the row the shower actually starts in
    return notes


def compute_radar_rain_ranges(
    hourly_rows: list[dict], combined: dict | None, now: datetime
) -> dict[int, tuple[float, float]]:
    """Return radar-enhanced rate ranges for every radar-overlapping row.

    Each Nowcast sample is a precipitation rate for a five-minute slot.  For
    the current row, only slots overlapping the time from ``now`` onward are
    considered.  Because the radar horizon moves with the current time, it
    commonly reaches into a third clock-hour row.  If it ends partway through
    a row, that row's range is the union of its exact radar samples and the
    hourly forecast range used as the best available estimate for the
    uncovered tail.  Rows with no radar overlap receive no override.
    """
    if not combined or not combined["times"] or combined["radar_n"] == 0:
        return {}
    radar_n = combined["radar_n"]
    radar_times = combined["times"][:radar_n]
    radar_rates = combined["rates"][:radar_n]
    radar_end = radar_times[-1] + timedelta(minutes=5)

    ranges: dict[int, tuple[float, float]] = {}
    for i, r in enumerate(hourly_rows):
        hour_start = r["time"]
        hour_end = hour_start + timedelta(hours=1)
        window_start = max(hour_start, now)
        if window_start >= hour_end:
            continue
        samples: list[float] = []
        for t, rate in zip(radar_times, radar_rates, strict=True):
            sample_end = t + timedelta(minutes=5)
            if t < hour_end and sample_end > window_start:
                samples.append(rate)
        if samples:
            # Radar can stop at (for example) 15:55 when the current time is
            # 13:55.  Complement those samples with the coarser hourly range
            # for 15:55–16:00 instead of discarding either source.
            if radar_end < hour_end:
                samples.extend(value for value in (r.get("rain"), r.get("rain_max")) if value is not None)
            ranges[i] = (min(samples), max(samples))
    return ranges


# ---------------------------------------------------------------------------
# MET alerts (official warnings: wind, rain, ice, forest fire, etc.)
# ---------------------------------------------------------------------------


def build_alerts(lat: float, lon: float) -> list[dict]:
    try:
        data = common.fetch_json(ALERTS_URL, {"lat": str(lat), "lon": str(lon), "lang": "en"}, ttl=ALERTS_TTL)
    except (urllib.error.URLError, ValueError, KeyError):
        return []
    return [f["properties"] for f in data.get("features", [])]


def build_alerts_section(alerts: list[dict]) -> tuple[Text, Group] | None:
    """A colored header + body for active alerts, or None when there are
    none -- silence is the right default here, not an "all clear" every run."""
    if not alerts:
        return None
    header_color = "red"
    lines: list[Text] = []
    for i, a in enumerate(alerts):
        color = ALERT_COLORS.get((a.get("riskMatrixColor") or "").lower(), "yellow")
        if i == 0:
            header_color = color.split()[-1]  # e.g. "bold red" -> "red"
        name = a.get("eventAwarenessName") or a.get("event") or "Alert"
        area = a.get("area")
        severity = a.get("severity", "")
        title = f"{severity} — {name}" + (f" ({area})" if area else "")
        if i:
            lines.append(Text(""))
        lines.append(Text(title, style=f"bold {color}"))
        if a.get("description"):
            lines.append(Text(a["description"], style=color))
        if a.get("instruction"):
            lines.append(Text(f"➜ {a['instruction']}", style="bright_black"))
    return Text("⚠ Weather Alert", style=f"bold {header_color}"), Group(*lines)


# ---------------------------------------------------------------------------
# Rain-arrival headline (one-line "so what" summary)
# ---------------------------------------------------------------------------


def rain_headline(combined: dict | None, hourly_rows: list[dict], now: datetime) -> Text:
    if combined is not None:
        times, rates, radar_n = combined["times"], combined["rates"], combined["radar_n"]
        wet = [r >= RAIN_RATE_MM_H for r in rates]
        if not any(wet):
            hrs = (times[-1] - now).total_seconds() / 3600
            return Text(f"✓ No rain expected in the next ~{hrs:.1f}h.", style="bold green")
        if wet[0]:
            stop_idx = wet.index(False) if False in wet else None
            if stop_idx is None:
                first_line = f"🌧️ Raining now, continuing through at least {times[-1]:%H:%M}."
            else:
                stop_t = times[stop_idx]
                approx = "~" if stop_idx >= radar_n else ""
                mins = max(0, round((stop_t - now).total_seconds() / 60))
                first_line = f"🌧️ Raining now — ending by {approx}{stop_t:%H:%M} (~{mins} min)."

            # A wet/dry run alone hides a brief intense leading edge: a
            # 4.0 mm/h sample followed by 0.9 mm/h is continuously "wet", so
            # the stop time says nothing about the strong shower easing.  If
            # the current strong rate drops below the strong-shower band
            # within the real radar window, report that transition as well.
            current_rate = rates[0]
            strong_end_idx = None
            if current_rate >= STRONG_SHOWER_RATE_MM_H:
                strong_end_idx = next(
                    (j for j in range(1, radar_n) if rates[j] < STRONG_SHOWER_RATE_MM_H),
                    None,
                )
            if strong_end_idx is not None:
                strong_end_t = times[strong_end_idx]
                strong_mins = max(0, round((strong_end_t - now).total_seconds() / 60))
                if wet[strong_end_idx]:
                    if stop_idx is None:
                        continuation = f"Rain continues through at least {times[-1]:%H:%M}."
                    else:
                        stop_t = times[stop_idx]
                        approx = "~" if stop_idx >= radar_n else ""
                        stop_mins = max(0, round((stop_t - now).total_seconds() / 60))
                        continuation = f"Lighter rain continues until {approx}{stop_t:%H:%M} (~{stop_mins} min)."
                    first_line = (
                        f"🌧️ Strong shower now ({current_rate:.1f} mm/h) — easing by "
                        f"{strong_end_t:%H:%M} (~{strong_mins} min). {continuation}"
                    )
                else:
                    first_line = (
                        f"🌧️ Strong shower now ({current_rate:.1f} mm/h) — ending by "
                        f"{strong_end_t:%H:%M} (~{strong_mins} min)."
                    )

            radar_rates = [r for r in rates[:radar_n] if r >= RAIN_RATE_MM_H]
            if radar_rates:
                min_r = min(radar_rates)
                max_r = max(radar_rates)
                if f"{min_r:.1f}" != f"{max_r:.1f}":
                    rate_str = f"[{min_r:.1f} - {max_r:.1f}] mm/h"
                else:
                    rate_str = f"[{min_r:.1f}] mm/h"
                hl = Text()
                hl.append(f"{first_line}\n", style="bold blue")
                hl.append("   Radar forecasted precipitation for the next 2h is ", style="white")
                hl.append(rate_str, style="green")
                hl.append(".", style="white")
                return hl
            return Text(first_line, style="bold blue")
        start_idx = wet.index(True)
        start_t = times[start_idx]
        mins = max(0, round((start_t - now).total_seconds() / 60))
        h, m = divmod(mins, 60)
        duration = f"{h}h {m:02d}min" if h else f"{m} min"
        # "Lasting" mirrors the wet[0] branch above: only claimed when this
        # same zone's own data actually shows the shower stopping again
        # before the zone ends -- a run still going at the last point means
        # we don't know when it stops, so no claim is made.
        lasting = ""
        stop_idx = next((j for j in range(start_idx + 1, len(wet)) if not wet[j]), None)
        if stop_idx is not None:
            stop_mins = max(0, round((times[stop_idx] - start_t).total_seconds() / 60))
            lasting = f" [lasting ~{stop_mins} min]"
        if start_idx < radar_n:
            radar_rates = [r for r in rates[start_idx:radar_n] if r >= RAIN_RATE_MM_H]
            if radar_rates:
                min_r = min(radar_rates)
                max_r = max(radar_rates)
                if f"{min_r:.1f}" != f"{max_r:.1f}":
                    rate_str = f"[{min_r:.1f} - {max_r:.1f}] mm/h"
                else:
                    rate_str = f"[{min_r:.1f}] mm/h"
                hl = Text()
                hl.append(f"☔ Rain expected in ~{duration} at around {start_t:%H:%M}{lasting}.\n", style="bold yellow")
                hl.append("   Radar forecasted precipitation for the next 2h is ", style="white")
                hl.append(rate_str, style="green")
                hl.append(".", style="white")
                return hl
        return Text(f"☔ Rain expected in ~{duration} at around {start_t:%H:%M}{lasting}", style="bold yellow")

    # No radar coverage here -- fall back to the coarser hourly figures.
    wet_hours = [(r.get("rain") or 0) >= RAIN_RATE_MM_H for r in hourly_rows]
    if not any(wet_hours):
        return Text("✓ No rain expected in the hourly forecast ahead.", style="bold green")
    if wet_hours[0]:
        return Text("🌧️ Rain likely this hour (hourly forecast; no radar here).", style="bold blue")
    start_t = hourly_rows[wet_hours.index(True)]["time"]
    return Text(f"☔ Rain likely from ~{start_t:%H:%M} (hourly forecast; no radar here).", style="bold yellow")


# ---------------------------------------------------------------------------
# Sun hours today (cloud-cover based, same idea as forecast.py)
# ---------------------------------------------------------------------------


def build_sun_intervals(
    hourly_rows: list[dict], sun: tuple[datetime, datetime] | None, today
) -> list[tuple[datetime, datetime]]:
    if not sun:
        return []
    rise, set_ = sun
    runs: list[tuple[datetime, datetime]] = []
    start: datetime | None = None
    last_t: datetime | None = None
    for r in hourly_rows:
        t = r["time"]
        if t.date() != today:
            break
        cloud = r.get("cloud")
        sunny = rise <= t < set_ and cloud is not None and cloud < common.SUN_CLOUD_PCT
        if sunny and start is None:
            start = t
        elif not sunny and start is not None:
            runs.append((start, t))
            start = None
        last_t = t
    if start is not None and last_t is not None:
        runs.append((start, min(set_, last_t + timedelta(hours=1))))
    return runs


# ---------------------------------------------------------------------------
# Pressure trend (rising/falling/steady over the next few hours)
# ---------------------------------------------------------------------------


def pressure_trend(rows: list[dict], hours: int = 3) -> Text | None:
    vals = [(r["time"], r["pressure"]) for r in rows[: hours + 1] if r.get("pressure") is not None]
    if len(vals) < 2:
        return None
    (_, p0), (_, p1) = vals[0], vals[-1]
    delta = p1 - p0
    arrow = "↓" if delta <= -1 else "↑" if delta >= 1 else "→"
    return Text(f"🎚️ {p0:.0f} hPa [Trend: {arrow}]", style="bright_black")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def current_conditions_line(nowcast: dict | None, hourly_rows: list[dict]) -> Text | None:
    """Icon-led 'right now' readings -- radar snapshot if we have one, else
    the current hourly-forecast row."""
    parts: list[str] = []
    if nowcast and nowcast.get("snapshot"):
        s = nowcast["snapshot"]
        if s.get("air_temperature") is not None:
            parts.append(f"🌡️ {s['air_temperature']:.1f}°C")
        if s.get("precipitation_rate") is not None:
            parts.append(f"💧 {s['precipitation_rate']:.1f} mm/h")
        if s.get("wind_speed") is not None:
            arrow = common.wind_arrow(s["wind_from_direction"]) if s.get("wind_from_direction") is not None else ""
            parts.append(f"💨 {s['wind_speed']:.1f} m/s {arrow}".strip())
        if s.get("relative_humidity") is not None:
            parts.append(f"💦 {s['relative_humidity']:.0f}%")
    elif hourly_rows:
        r = hourly_rows[0]
        if r.get("temp") is not None:
            parts.append(f"🌡️ {common.round_half_up(r['temp'])}°C")
        if r.get("wind_speed") is not None:
            arrow = common.wind_arrow(r["wind_dir"]) if r.get("wind_dir") is not None else ""
            parts.append(f"💨 {r['wind_speed']:.0f} m/s {arrow}".strip())
    return Text(" | ".join(parts), style="bright_black") if parts else None


def render(
    place: str,
    lat: float,
    lon: float,
    now: datetime,
    nowcast: dict | None,
    hourly_rows: list[dict],
    sun: tuple[datetime, datetime] | None,
    alerts: list[dict],
) -> None:
    # Cap the layout width so panels don't stretch into empty space on wide
    # terminals, while still shrinking to fit a genuinely narrow one.
    real_width = Console().size.width
    console = Console(width=min(real_width, 100))

    label_w = len("SUN (DAYTIME):") + 1

    location = Text()
    location.append("LOCATION:".ljust(label_w), style="dim")
    location.append(place, style="bold green")
    location.append(f" ({format_latlon(lat, lon)})", style="dim")
    console.print(location)
    console.print(Text(f"{'DATE/TIME:'.ljust(label_w)}📅 {now:%a %d %b}   🕐 {now:%H:%M}", style="dim"))
    if sun:
        rise, set_ = sun
        daytime_min = round((set_ - rise).total_seconds() / 60)
        dh, dm = divmod(daytime_min, 60)
        daytime = f"{dh}h" if dm == 0 else f"{dh}h{dm:02d}m"
        console.print(
            Text(
                f"{'SUN (DAYTIME):'.ljust(label_w)}🌅 {rise:%H:%M}↑   🌇 {set_:%H:%M}↓   💡  {daytime} of daylight",
                style="dim",
            )
        )
    console.print()

    alerts_section = build_alerts_section(alerts)
    if alerts_section:
        alert_header, alert_body = alerts_section
        console.print(alert_header)
        console.print(alert_body)
        console.print()

    combined = build_combined_rain(nowcast, hourly_rows)
    headline = rain_headline(combined, hourly_rows, now)

    now_lines: list[Text] = []
    cond = current_conditions_line(nowcast, hourly_rows)
    trend = pressure_trend(hourly_rows)
    if cond or trend:
        conditions_line = Text(style="bright_black")
        for i, part in enumerate(p for p in (cond, trend) if p is not None):
            if i:
                conditions_line.append(" | ")
            conditions_line.append_text(part)
        now_lines.append(conditions_line)

    console.print(Text("Right now", style="bold cyan"))
    console.print(Group(*now_lines))
    console.print()

    # Printed right below the "☔ Rain expected ..." headline, wherever that
    # ends up landing -- inside the chart (the usual case), or standing
    # alone in the no-chart branches below.
    sun_lines: list[Text] = []
    sun_runs = build_sun_intervals(hourly_rows, sun, now.date())
    if sun_runs:
        hrs = sum((e - s).total_seconds() / 3600 for s, e in sun_runs)
        sun_lines.append(
            Text(
                f"☀  {hrs:.1f}h of sun expected later today. From now to {sun_runs[-1][1]:%H:%M}",
                style="bright_black",
            )
        )
    elif sun:
        sun_lines.append(Text("☀  No sun expected later today", style="bold yellow"))
    if sun:
        # Indented to line up with the text after the "☀  " symbol on the
        # line above it, not the left margin.
        indent = " " * len("☀  ")
        sun_lines.append(Text(f"{indent}Sunny: when <{common.SUN_CLOUD_PCT}% overcast/clouds.", style="bright_black"))

    if nowcast is not None and combined is not None:
        chart_group = build_rain_chart(nowcast, combined, headline, now, max_width=console.width)
        if chart_group:
            console.print(Text("Rain forecast (4h)", style="bold blue"))
            console.print()
            console.print(chart_group)  # already ends in a blank line, after the headline
            console.print(Group(*sun_lines))
            console.print()
        elif nowcast.get("coverage") and nowcast["coverage"] != "ok":
            console.print(Text("RADAR DATA NOT AVAILABLE RIGHT NOW", style="bold red"))
            console.print()
            console.print(Group(*sun_lines))
            console.print()
    elif nowcast is not None:
        # A response came back (we're within Nordic coverage) but it carried
        # no usable radar samples right now -- e.g. a transient outage on
        # MET's side -- distinct from genuinely being outside radar range.
        console.print(Text("🌧️  RADAR DATA NOT AVAILABLE RIGHT NOW", style="bold red"))
        console.print(Text("See the hourly rain figures below.", style="red"))
        console.print(headline)
        console.print()
        console.print(Group(*sun_lines))
        console.print()
    else:
        console.print(
            Text(
                "🌧️  No radar-based nowcast here (outside MET Norway's Nordic coverage) "
                "— see the hourly rain figures below.",
                style="yellow",
            )
        )
        console.print(headline)
        console.print()
        console.print(Group(*sun_lines))
        console.print()

    console.print(Text("Hour by hour:", style="bold blue"))
    showers = match_showers_to_hours(hourly_rows, combined, now)
    radar_rain_ranges = compute_radar_rain_ranges(hourly_rows, combined, now)
    render_hourly_table(console, hourly_rows, showers, sun, radar_rain_ranges)


def build_json_payload(
    place: str,
    lat: float,
    lon: float,
    now: datetime,
    nowcast: dict | None,
    hourly_rows: list[dict],
    sun: tuple[datetime, datetime] | None,
    alerts: list[dict],
) -> dict:
    combined = build_combined_rain(nowcast, hourly_rows)
    return {
        "place": place,
        "lat": lat,
        "lon": lon,
        "generated_at": now.isoformat(),
        "sun": {"sunrise": sun[0].isoformat(), "sunset": sun[1].isoformat()} if sun else None,
        "alerts": alerts,
        "rain_headline": rain_headline(combined, hourly_rows, now).plain,
        "hourly": [
            {
                "time": r["time"].isoformat(),
                "symbol": r["symbol"],
                "temp_c": r["temp"],
                "rain_mm": r["rain"],
                "rain_mm_max": r["rain_max"],
                "rain_probability_pct": r["pop"],
                "wind_speed_ms": r["wind_speed"],
                "wind_gust_ms": r["wind_gust"],
                "wind_from_deg": r["wind_dir"],
            }
            for r in hourly_rows
        ],
    }


DEFAULT_MIN_HOURS_AHEAD = common.DEFAULT_MIN_HOURS_AHEAD


def resolve_hours_ahead(requested: int | None, now: datetime, config: dict) -> int:
    """Resolve --hours: explicit value wins; otherwise rest-of-today, but never
    less than a minimum (config: [today] min_hours, default DEFAULT_MIN_HOURS_AHEAD)."""
    if requested is not None:
        return requested
    min_hours = config.get("today", {}).get("min_hours", DEFAULT_MIN_HOURS_AHEAD)
    return max(24 - now.hour, min_hours)


def run(args: argparse.Namespace) -> int:
    global TZ
    try:
        TZ = common.resolve_tz(args.lat, args.lon)
        now = datetime.now(TZ)

        n_hours = resolve_hours_ahead(args.hours, now, common.load_config(default_toml=common.DEFAULT_CONFIG_TOML))

        nowcast = build_nowcast(args.lat, args.lon)
        hourly_rows = build_hourly_rows(args.lat, args.lon, n_hours, now)
        sun = common.sunrise_sunset(now, args.lat, args.lon, TZ)
        alerts = build_alerts(args.lat, args.lon)
    except urllib.error.URLError as exc:
        print(f"error: could not reach yr.no: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(build_json_payload(args.place, args.lat, args.lon, now, nowcast, hourly_rows, sun, alerts)))
        return 0

    render(args.place, args.lat, args.lon, now, nowcast, hourly_rows, sun, alerts)
    return 0
