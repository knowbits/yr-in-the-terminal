# yr-in-the-terminal

Weather forecasts from [yr.no](https://www.yr.no) (MET Norway) as coloured
tables and charts, straight in your terminal — no browser, no app.

- **`yr-forecast.py`** — a 7-day forecast table (one row per day).
- **`yr-today.py`** — a detailed view of the rest of today: an hour-by-hour
  table plus a high-resolution, radar-based rain chart for the next ~2 hours
  (5-minute Nowcast samples), blended into the hourly forecast beyond that.

Both default to Hundeidvik, Sykkylven, Norway, and accept `--lat`/`--lon`/
`--place` for anywhere else.

## Requirements

- [uv](https://docs.astral.sh/uv/) — manages the Python version, virtualenv,
  and dependencies (just [rich](https://github.com/Textualize/rich)).
- Optionally [mise](https://mise.jdx.dev/) to install pinned `uv`/`just`/`bats`
  (see `.mise.toml`), and [just](https://just.systems/) to run the recipes
  below.

## Usage

```console
$ ./yr-forecast.py
$ ./yr-today.py --hours 12
$ ./yr-forecast.py --lat 60.10 --lon 9.58 --place "Veggli"
```

`uv run` picks up the project's virtualenv automatically, so the scripts also
work as `uv run ./yr-today.py` from a fresh clone with no setup step.

Or via `just`:

```console
$ just today
$ just forecast -- --days 3
```

## Development

```console
$ just sync       # create the UV-managed .venv
$ just qa         # lint + format check + pytest + bats
$ just fmt        # auto-format with ruff
```

## License

[MIT](LICENSE)
