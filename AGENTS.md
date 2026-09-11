# CLAUDE.md

## CRITICAL — Mandatory Common Rules (always in force)

@docs-AI/AGENTS_COMMON.md

**Every rule and guideline in `docs-AI/AGENTS_COMMON.md` is MANDATORY in this repo** — the Router
(first move for every lookup/read/run), the behavioral core, Git safety, plan/STATUS protocol,
token-compression, and the context-checkpoint discipline. The `@` line above imports it into
Claude Code's context at session start (Claude Code never follows markdown links); any other
CLI/agent must read that file in full before doing any work here. This file only adds
project-specific constraints and never overrides the common ones.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A `src/yr_in_the_terminal/` package fetching weather data from yr.no (MET
Norway) and rendering it as coloured tables/charts in the terminal via Rich,
exposed as one installed CLI: `yr <command>` (`project.scripts` in
`pyproject.toml`).

- `cli.py` — argparse entry point (`yr = "yr_in_the_terminal.cli:main"`);
  dispatches to the two subcommands, both sharing `--lat`/`--lon`/`--place`/
  `--here`/`--location`/`--no-cache`/`--json` on a common parent parser (each
  subcommand adds its own flags — `--hours` for `today`, `--days`/
  `--exclude-night` for `forecast`).
- `today.py` — `yr today`: rest-of-today detail — hour-by-hour table + a
  radar-based Nowcast rain chart for the next ~2h, blended with hourly data
  beyond that (Locationforecast 2.0 complete + Nowcast 2.0 + Sunrise 3.0 +
  MET alerts).
- `forecast.py` — `yr forecast`: 7-day forecast, one row per day
  (Locationforecast 2.0 compact + Sunrise 3.0).
- `common.py` — shared, stateless helpers (fetch/cache, tz, sun, rounding,
  wind-arrow) used by both subcommands.

No built-in default location -- `--lat`/`--lon`, `--location <name>`,
`--here`, or a `[location]` section in the settings file (see README) sets
it; if none do, `cli.resolve_location()` returns an error and `main()`
prints only the error panel (exit code 1, no forecast) -- there is no
silent IP-geolocation fallback for an unconfigured location. `--here`
still explicitly opts into IP geolocation for that one run.

## Commands

Requires [uv](https://docs.astral.sh/uv/) (manages the Python version, venv,
and deps — just `rich`). [just](https://just.systems/) runs the recipes
below; [mise](https://mise.jdx.dev/) (see `.mise.toml`) pins `uv`/`just`/`bats`.

```console
just sync            # create the uv-managed .venv
just lint             # ruff check
just fmt-check         # ruff format --check
just fmt               # ruff format (auto-fix)
just test              # pytest (tests/)
just test-bats         # bats behavioural tests (tests/)
just qa                 # lint + fmt-check + test + test-bats — run this before considering work done
just today -- --hours 12
just forecast -- --days 3
```

Run a single Python test: `uv run pytest tests/test_yr_today.py::RadarRainRangesTest::test_headline_separates_strong_shower_from_lingering_light_rain`

Run a single bats test: `bats tests/yr-today.bats -f "headline distinguishes"`

Test files mirror the package: `tests/test_common.py`, `tests/test_yr_today.py`,
`tests/test_yr_forecast.py`. `tests/yr-today.bats` doesn't unit-test anything
new — each `@test` just shells out to run one `unittest` method from
`tests/test_yr_today.py` and checks the exit code, so a bats test failure
means look at the Python test of the same name. CI (`.github/workflows/ci.yml`)
runs `just qa` via `jdx/mise-action` on push/PR to `master`.

## Architecture

`today.py`/`forecast.py` both follow the same shape: fetch → build (pure
data transform) → render (Rich output), each in its own function(s), so the
data logic is testable independently of terminal output — see how
`compute_radar_rain_ranges`/`rain_headline` in `today.py` are unit-tested by
constructing a `combined` dict directly rather than going through
`build_combined_rain`/network calls. Each also exposes a
`build_json_payload()` for `--json`, called from `run()` right before
`render()`, reusing the same already-fetched data (no extra network calls).

Key points specific to `today.py` (the more involved of the two):

- **Nowcast vs. Locationforecast resolution.** Nowcast 2.0 is MET's only
  sub-hourly product (radar-derived, ~2h horizon, 5-min steps, Nordic-only —
  422 outside coverage). Locationforecast never goes below hourly steps.
  `build_combined_rain` stitches the two into one series: real radar samples
  for `radar_n` points, then `build_blend` extends it using flat
  hourly-forecast plateaus (never interpolated/smoothed between hours — see
  the docstring for why extrapolating radar motion further out is
  deliberately not done). Code and comments are emphatic about not
  fabricating precision beyond what each data source actually supports —
  preserve that distinction when touching this logic.
- **The rain chart** (`build_rain_chart`) renders sub-character-cell
  precision using Unicode block elements: `_BLOCKS` (eighths, for blend's
  filled area) and `_LINE_EIGHTHS` (Symbols for Legacy Computing eighth-row
  glyphs, for radar's point markers). Column widths are apportioned between
  the radar and blend zones by real elapsed minutes, then fit to available
  terminal width (`fit_to_chars`, expand-or-merge depending on whether there
  are more or fewer characters than data points). Heavily commented inline —
  read those comments before changing row/column math, they explain
  intentional off-by-one choices (e.g. the reserved zero row).
- **Radar/hourly row merging**: `compute_radar_rain_ranges` maps 5-min radar
  samples onto the hourly table's rows, unioning with the hourly range for
  any uncovered tail when the radar horizon ends mid-row. This is the main
  thing covered by `tests/test_yr_today.py`.

Shared conventions across both subcommands:

- Module-level `TZ` (a `ZoneInfo`) is resolved per-location at runtime via
  `common.resolve_tz()` (timeapi.io, with a longitude-based fallback) and
  reassigned through `global TZ` in each of `today.py`/`forecast.py` — not
  passed as a parameter.
- `SYMBOLS`/`_SYMBOL_ORDER` map yr.no `symbol_code` strings to
  (emoji, label); `today.py`'s `get_symbol` does substring matching in a
  specific order so compound codes (e.g. `heavyrainshowersandthunder_day`)
  resolve to the most specific entry.
- All network calls go through `common.fetch_json()` (required yr.no
  fair-use `User-Agent` header); `forecast.py` lets `URLError` propagate to
  `main`, `today.py`'s `build_nowcast` additionally treats HTTP 422 as
  "outside Nordic radar coverage" (returns `None`) rather than an error.
- `fetch_json(url, params, *, ttl=0, cache_dir=None)` caches responses as
  JSON files under `$XDG_CACHE_HOME/yr-in-the-terminal/` (keyed by a hash of
  `url` + sorted `params`); each call site picks its own TTL (e.g. `today.py`'s
  `FORECAST_TTL`/`NOWCAST_TTL`/`ALERTS_TTL`). `--no-cache` forces `ttl=0`
  everywhere via `common.set_cache_enabled(False)`, called once in
  `cli.main()`. A missing/corrupt cache file or a write failure always falls
  back to a live fetch — never raises.
- `cli.resolve_location()` fills `--lat`/`--lon`/`--place` from
  `--location`/`--here`/the settings file's `[location]`, in that order,
  skipped entirely if `--lat`/`--lon` were given explicitly (those always
  win). `--location` calls `common.geocode()` (OpenStreetMap Nominatim,
  cached `GEOCODE_TTL` = 30 days); on no match it warns and returns an
  error (no config fallback within the same call). `--here` calls
  `common.resolve_default_location()` (one short-timeout IP-geolocation
  call, ipapi.co), falling back to `[location]`'s lat/lon if IP resolution
  fails, or `None` if there's no fallback either — and even on success, IP
  geolocation can land far from the real location on mobile/rural ISPs (the
  IP's registered block, not the device); `--location` is the reliable
  choice. If nothing resolves a location at all, `main()` prints an error
  and returns exit code 1.
