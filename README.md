# yr-in-the-terminal

![CI](https://github.com/knowbits/yr-in-the-terminal/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)

Weather forecasts from [yr.no](https://www.yr.no) (MET Norway) as coloured
tables and charts, straight in your terminal — no browser, no app.

- **`yr today`** — a detailed view of the rest of today: an hour-by-hour
  table plus a rain chart for the next ~2 hours at 5-minute resolution, using
  MET Norway's [Nowcast](https://api.met.no/weatherapi/nowcast/2.0/documentation)
  radar data (Nordic coverage only) for far more detail than the regular
  hourly forecast gives; it blends into that hourly forecast beyond the ~2h
  radar horizon.
- **`yr forecast`** — a 7-day forecast table (one row per day).

Both default to Hundeidvik, Sykkylven, Norway, and accept `--lat`/`--lon`/
`--place` for anywhere else, or `--location <name>` to resolve coordinates
from a place name (via [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/);
falls back to the default on no match/failure). Both also accept `--no-cache`
(bypass the local response cache) and `--json` (print machine-readable JSON
instead of a table/chart). There's also a `--here` flag (IP geolocation) —
see `yr today --help` — but it's unreliable on mobile/rural connections;
`--location`/`--lat`+`--lon` are the ones to reach for.

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

Note: `deploy-local` and `uv tool install`/`uvx --from` (above) share the
same `~/.local/bin/yr` target — whichever runs last wins. If you use both
(e.g. testing the end-user install path from a dev checkout), re-run `just
deploy-local` afterward to point `yr` back at this checkout.

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
$ yr today --json | jq .
```

## Settings

`yr today` shows the rest of today by default, but never fewer than 12
hours ahead — even late in the day, when "rest of today" alone would be
just an hour or two. That minimum is configurable via a settings file at
`$XDG_CONFIG_HOME/yr-in-the-terminal/config.toml` (typically
`~/.config/yr-in-the-terminal/config.toml` — the standard
[XDG Base Directory](https://specifications.freedesktop.org/basedir-spec/latest/)
location for a Linux app's own config), which `yr` creates for you,
pre-filled with the defaults, the first time it doesn't find one:

```toml
[today]
min_hours = 12
```

Edit the value and re-run `yr` to change it. It's plain [TOML](https://toml.io/);
an unreadable or invalid file is silently ignored (`yr` just uses the
built-in default without touching or overwriting it), so
there's no way to break the tool by editing this wrong. `--hours` on the
command line always overrides it for that one run.

## Development

```console
$ just sync       # create the UV-managed .venv
$ just qa         # lint + format check + pytest + bats
$ just fmt        # auto-format with ruff
```

Running from the clone without installing: prefix any command with `uv run`
(e.g. `uv run yr today --hours 12`), or use `just today -- --hours 12` /
`just forecast -- --days 3`.

## License

[MIT](LICENSE)
