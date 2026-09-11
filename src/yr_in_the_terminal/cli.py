"""Unified `yr` CLI entry point: dispatches to the `today`/`forecast` subcommands."""

from __future__ import annotations

import argparse
import sys

from yr_in_the_terminal import common, forecast, today

DEFAULT_LAT = 62.36675
DEFAULT_LON = 6.42422
DEFAULT_PLACE = "Hundeidvik, Sykkylven"


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--lat", type=float, default=DEFAULT_LAT, help="latitude (default Hundeidvik)")
    parent.add_argument("--lon", type=float, default=DEFAULT_LON, help="longitude (default Hundeidvik)")
    parent.add_argument("--place", default=DEFAULT_PLACE, help="location label shown in the title")
    parent.add_argument("--no-cache", action="store_true", help="bypass the local response cache")
    parent.add_argument(
        "--here",
        action="store_true",
        help="use IP geolocation for the location (falls back to the default); "
        "UNRELIABLE -- accuracy depends heavily on your ISP/mobile broadband provider, "
        "prefer --location or --lat/--lon when you know where you are",
    )
    parent.add_argument(
        "--location", default=None, help="resolve lat/lon/place from a place name via OpenStreetMap Nominatim"
    )

    ap = argparse.ArgumentParser(description="yr.no (MET Norway) weather forecasts in the terminal.")
    sub = ap.add_subparsers(dest="command", required=True)

    today_p = sub.add_parser(
        "today",
        parents=[parent],
        description="Detailed today-only yr.no forecast: hourly table + radar rain nowcast.",
        epilog="Example: yr today --hours 12",
    )
    today_p.add_argument(
        "--hours",
        type=int,
        default=None,
        help="number of hourly rows to show (default: rest of today, min 12 -- "
        "configurable via [today].min_hours in the settings file, see README)",
    )
    today_p.add_argument("--json", action="store_true", help="print machine-readable JSON instead of a table")
    today_p.set_defaults(func=today.run)

    forecast_p = sub.add_parser(
        "forecast",
        parents=[parent],
        description="7-day yr.no forecast table.",
        epilog="Example: yr forecast --days 5 --exclude-night",
    )
    forecast_p.add_argument("--days", type=int, default=7, help="number of forecast days to show")
    forecast_p.add_argument(
        "--exclude-night", action="store_true", help="only use hours 06:00-24:00 for temps/rain/sun"
    )
    forecast_p.add_argument("--json", action="store_true", help="print machine-readable JSON instead of a table")
    forecast_p.set_defaults(func=forecast.run)

    return ap


def main() -> int:
    ap = build_parser()
    # argparse subparsers mishandle a bare "--" (a common `just recipe -- --flag`
    # separator survives into argv): it stops the *subparser* from consuming
    # its own options, so the leftover tokens bubble back up as "unrecognized
    # arguments" at the top-level parser. This CLI has no positional argument
    # that would ever need a literal "--", so it's safe to just drop it.
    argv = [a for a in sys.argv[1:] if a != "--"]
    args = ap.parse_args(argv)
    common.set_cache_enabled(not args.no_cache)
    explicit = (args.lat, args.lon, args.place) != (DEFAULT_LAT, DEFAULT_LON, DEFAULT_PLACE)
    if not explicit and args.location:
        resolved = common.geocode(args.location)
        if resolved is None:
            print(f"warning: could not resolve --location {args.location!r}, using default", file=sys.stderr)
        else:
            args.lat, args.lon, args.place = resolved
    elif not explicit and args.here:
        args.lat, args.lon, args.place = common.resolve_default_location(args.lat, args.lon, args.place)
        print(
            "note: --here uses IP-based geolocation, which can be inaccurate "
            "depending on your ISP/mobile broadband provider -- use --location or "
            "--lat/--lon instead if this doesn't look right",
            file=sys.stderr,
        )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
