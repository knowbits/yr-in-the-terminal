# yr-in-the-terminal

![CI](https://github.com/knowbits/yr-in-the-terminal/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)

Weather forecasts from [yr.no](https://www.yr.no) (MET Norway) as coloured
tables and charts, straight in your terminal — no browser, no app.

- **`yr today`** — a detailed view of the rest of today: an hour-by-hour
  table plus a high-resolution, radar-based rain chart for the next ~2 hours
  (5-minute Nowcast samples), blended into the hourly forecast beyond that.
- **`yr forecast`** — a 7-day forecast table (one row per day).

Both default to Hundeidvik, Sykkylven, Norway, and accept `--lat`/`--lon`/
`--place` for anywhere else, `--location <name>` to resolve coordinates from
a place name (via [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/)),
or `--here` to resolve the location from your IP (both fall back to the
default on any failure — offline, no match, rate-limited, etc.; note IP
geolocation can be wildly inaccurate on mobile/rural connections — prefer
`--location`/`--lat`+`--lon` when you know where you are). Both also accept
`--no-cache` (bypass the local response cache) and `--json` (print
machine-readable JSON instead of a table/chart).

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

### Manual install (for development)

```console
$ git clone https://github.com/knowbits/yr-in-the-terminal.git
$ cd yr-in-the-terminal
$ uv sync
$ just deploy-local   # symlinks yr onto PATH
```

`uv sync` alone is enough to run the tool from the clone without installing
it anywhere — see [Usage](#usage) below. [mise](https://mise.jdx.dev/) (pins
`uv`/`just`/`bats` via `.mise.toml`) and [just](https://just.systems/) (runs
the recipes in this README) are optional conveniences, mainly useful here.

## Usage

```console
$ yr today
$ yr today --hours 12
$ yr forecast
$ yr forecast --days 3
```

```console
$ yr forecast --lat 60.10 --lon 9.58 --place "Veggli"
$ yr today --location "Sykkylven"
$ yr today --here
$ yr today --json | jq .
```

Running from a clone without installing: prefix any command with `uv run`
(e.g. `uv run yr today --hours 12`), or use `just today -- --hours 12` /
`just forecast -- --days 3`.

## Development

```console
$ just sync       # create the UV-managed .venv
$ just qa         # lint + format check + pytest + bats
$ just fmt        # auto-format with ruff
```

## License

[MIT](LICENSE)
