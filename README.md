# yr-in-the-terminal

![CI](https://github.com/knowbits/yr-in-the-terminal/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)

Weather forecasts from [yr.no](https://www.yr.no) (MET Norway) as coloured
tables and charts, straight in your terminal — no browser, no app.

## Commands

- **`yr today`** — hour-by-hour table for the rest of today, plus a
  short-range rain chart (see [Nowcast radar](#nowcast-radar) below)
- **`yr forecast`** — 7-day table, one row per day

## Options

### Location

Shared by both commands. No built-in default — pick one:

| Option | Sets | Notes |
|---|---|---|
| `--lat`/`--lon` (`--place` optional) | exact coordinates | works offline; always wins over the others |
| `--location "<name>"` | geocoded coordinates, for this run only | via [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/); needs network; ambiguous names (e.g. multiple "Toreplassen" in Norway) list every match instead of guessing -- add a region to disambiguate, e.g. `--location "Toreplassen, Sykkylven"` |
| `--set-location "<name>"` | geocoded coordinates, and saves it | like `--location`, but also writes the resolved place to the [Settings](#settings) file's `[location]` default -- an ambiguous or failed lookup saves nothing |
| `--here` | IP-geolocated coordinates | ⚠️ unreliable, esp. mobile/rural connections; never saved -- `--set-location` is the way to set a persistent default |
| [Settings](#settings) file, `[location]` | your saved default | set once via `--set-location`, no flags needed afterward |

Nothing set → `yr` fails hard with an error (no forecast is shown) — there's
no silent IP-geolocation guess; pass `--here` explicitly to opt into that.

### Shared by both commands

| Option | Effect |
|---|---|
| `--no-cache` | bypass the local response cache for this run -- always fetch live (see [Settings](#settings) to tune per-source caching instead of disabling it outright) |
| `--json` | machine-readable output instead of a table/chart |

### `yr today` only

| Option | Effect |
|---|---|
| `--hours N` | number of hourly rows to show (default: rest of today, min 12 — configurable via `[today].min_hours` in [Settings](#settings)) |

### `yr forecast` only

| Option | Effect |
|---|---|
| `--days N` | number of forecast days to show (default: 7) |
| `--exclude-night` | only use hours 06:00–24:00 for temps/rain/sun |

## Install

Linux only for now.

### 1. Install uv

`yr`'s only real dependency — it manages the Python version, the
virtualenv, and the one runtime package ([rich](https://github.com/Textualize/rich)).
The standard installer script (official, from [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)):

```console
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

Skip this step if `uv` is already on your PATH.

### 2. Install (or just run) yr

Pick one:

```console
# Install directly from the repo, no git clone needed
$ uv tool install git+https://github.com/knowbits/yr-in-the-terminal.git
$ yr today

# Try it with no install at all -- zero-install ephemeral run (like `npx`),
# cached by uv so the next run is fast
$ uvx --from git+https://github.com/knowbits/yr-in-the-terminal.git yr today
```

`uv tool install` builds an isolated venv and puts `yr` on your PATH (in
uv's tool bin dir, typically `~/.local/bin`) — one command, no separate
build/symlink step. Re-running it later updates to the latest `master`.

## Usage

```console
$ yr today --location "Oslo"
$ yr forecast --location "Bergen"
```

```console
$ yr today --hours 12
$ yr forecast --days 3 --exclude-night
$ yr today --json | jq .
```

Set a `[location]` default in [Settings](#settings) once, and plain
`yr today` / `yr forecast` work with no flags.

## Nowcast radar

`yr today`'s rain chart uses MET Norway's
[Nowcast](https://api.met.no/weatherapi/nowcast/2.0/documentation) radar
product for its first ~2 hours, blending into the regular hourly forecast
beyond that:

- **Resolution:** 5-minute samples (vs. hourly for the regular forecast)
- **Horizon:** ~2 hours ahead only
- **Coverage:** Nordic region only — outside it, `yr today` silently falls
  back to hourly-only data

## Settings

- **File:** `$XDG_CONFIG_HOME/yr-in-the-terminal/config.toml`
- **Typically:** `~/.config/yr-in-the-terminal/config.toml` — the standard
  [XDG Base Directory](https://specifications.freedesktop.org/basedir-spec/latest/)
  location for a Linux app's config
- Auto-created, pre-filled, the first time `yr` doesn't find one
- Plain [TOML](https://toml.io/) — edit values, re-run `yr`
- Unreadable/invalid file → silently ignored, built-in defaults used, file
  left untouched — no way to break `yr` by editing this wrong

```toml
[location]
# place = "Oslo"

[today]
min_hours = 12

[cache]
forecast_ttl = 2700
nowcast_ttl = 300
alerts_ttl = 1200
geocode_ttl = 2592000
```

- `[location]` — default place (geocoded the same way `--location` resolves
  one) when no `--lat`/`--lon`/`--location`/`--here` flag is given (see
  [Location](#location)); commented out by default since there's no
  built-in default. Set it with `yr <command> --set-location "<name>"`
  rather than by hand
- `[today].min_hours` — floor for `yr today`'s default row count (`--hours`
  on the command line always overrides it)
- `[cache]` — see [Caching](#caching) below

### Caching

`yr` caches each API response to disk for a TTL (seconds), so repeated runs
don't re-fetch data that hasn't changed yet. This exists because
[yr.no's fair-use terms](https://developer.yr.no/doc/TermsOfService/) ask API
consumers to cache responses rather than hit the API on every run.

| `[cache]` key | Default | Used by | What it caches |
|---|---|---|---|
| `forecast_ttl` | 2700 (45 min) | `yr today` + `yr forecast` | Locationforecast — the hourly model, which itself only updates roughly hourly |
| `nowcast_ttl` | 300 (5 min) | `yr today` | Nowcast radar — MET issues a new 5-minute radar frame at that same cadence, so this doesn't add staleness beyond the data's own resolution |
| `alerts_ttl` | 1200 (20 min) | `yr today` | MET weather alerts |
| `geocode_ttl` | 2592000 (30 days) | `--location` (both commands) | Place-name → coordinates lookups; a place's coordinates don't change |

Set any of them to `0` to always fetch that source live. `--no-cache` on the
command line disables all caching for one run without editing the file.

## Development

### Manual install

```console
$ git clone https://github.com/knowbits/yr-in-the-terminal.git
$ cd yr-in-the-terminal
$ uv sync
$ just yr-deploy-local   # symlinks yr onto PATH
```

`uv sync` alone is enough to run the tool from the clone without installing
it anywhere — see [Usage](#usage) above. [mise](https://mise.jdx.dev/) (pins
`uv`/`just`/`bats` via `.mise.toml`) and [just](https://just.systems/) (runs
the recipes below) are optional conveniences, mainly useful here.

Note: `yr-deploy-local` and `uv tool install`/`uvx --from` ([Install](#install))
share the same `~/.local/bin/yr` target — whichever runs last wins. If you
use both (e.g. testing the end-user install path from a dev checkout),
re-run `just yr-deploy-local` afterward to point `yr` back at this checkout.

### Recipes

```console
$ just uv-sync    # create the UV-managed .venv
$ just qa         # lint + format check + pytest + bats
$ just code-fmt   # auto-format with ruff
```

Running from the clone without installing: prefix any command with `uv run`
(e.g. `uv run yr today --hours 12`), or use `just yr-today -- --hours 12` /
`just yr-forecast -- --days 3`.

## License

[MIT](LICENSE)
