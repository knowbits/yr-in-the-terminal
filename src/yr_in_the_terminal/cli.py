"""Unified `yr` CLI entry point: dispatches to the `today`/`forecast` subcommands."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel

from yr_in_the_terminal import common, forecast, today


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--lat", type=float, default=None, help="latitude")
    parent.add_argument("--lon", type=float, default=None, help="longitude")
    parent.add_argument("--place", default=None, help="location label shown in the title")
    parent.add_argument("--no-cache", action="store_true", help="bypass the local response cache")
    parent.add_argument(
        "--here",
        action="store_true",
        help="use IP geolocation for the location; "
        "UNRELIABLE -- accuracy depends heavily on your ISP/mobile broadband provider, "
        "prefer --location or --lat/--lon when you know where you are",
    )
    parent.add_argument(
        "--location",
        default=None,
        help="resolve lat/lon/place from a place name via OpenStreetMap Nominatim; "
        "if the name is ambiguous, lists all matches and asks you to be more specific",
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


def _warn_no_location_configured() -> None:
    Console(stderr=True).print(
        Panel(
            "No location configured -- guessed it from your IP address instead "
            "(unreliable, especially on mobile/rural connections).\n\n"
            "Set a real default so you don't need this guess every time:\n"
            '  yr today --location "Your City"\n'
            r"or add \[location] lat/lon to the settings file (see README).",
            title="⚠ No default location set",
            border_style="red",
            expand=False,
        )
    )


def resolve_location(args: argparse.Namespace, config: dict) -> str | None:
    """Fill in args.lat/lon/place from --location, --here, or the settings
    file's [location] section, in that order, skipped if --lat/--lon were
    given explicitly. If none of those give a location either, falls back to
    IP geolocation (with a loud warning to configure a real default) before
    giving up. Returns an error message if that also fails, else None."""
    loc_cfg = config.get("location", {})
    explicit = args.lat is not None or args.lon is not None

    if not explicit and args.location:
        candidates = common.geocode_candidates(args.location, limit=5)
        if not candidates:
            print(f"warning: could not resolve --location {args.location!r}", file=sys.stderr)
        elif len(candidates) == 1:
            args.lat, args.lon, args.place = candidates[0]
        else:
            listing = "\n".join(f"  {lat:.4f}, {lon:.4f}  {label}" for lat, lon, label in candidates)
            return (
                f"error: --location {args.location!r} is ambiguous, {len(candidates)} matches:\n"
                f"{listing}\n"
                "Be more specific (e.g. add a region: --location "
                f'"{args.location}, <region>"), or pass --lat/--lon directly.'
            )
    elif not explicit and args.here:
        resolved = common.resolve_default_location(loc_cfg.get("lat"), loc_cfg.get("lon"), loc_cfg.get("place"))
        if resolved is None:
            print("warning: --here could not determine your location", file=sys.stderr)
        else:
            args.lat, args.lon, args.place = resolved
            print(
                "note: --here uses IP-based geolocation, which can be inaccurate "
                "depending on your ISP/mobile broadband provider -- use --location or "
                "--lat/--lon instead if this doesn't look right",
                file=sys.stderr,
            )
    elif not explicit:
        args.lat = loc_cfg.get("lat")
        args.lon = loc_cfg.get("lon")
        args.place = args.place or loc_cfg.get("place")

    if args.lat is None or args.lon is None:
        resolved = common.resolve_default_location(None, None, None)
        if resolved is None:
            return (
                "error: no location given -- pass --lat/--lon, --location <name>, or --here, "
                "or set [location] lat/lon in the settings file (see README)"
            )
        args.lat, args.lon, args.place = resolved
        _warn_no_location_configured()

    if not args.place:
        args.place = f"{args.lat}, {args.lon}"
    return None


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

    config = common.load_config(default_toml=common.DEFAULT_CONFIG_TOML)
    error = resolve_location(args, config)
    if error:
        print(error, file=sys.stderr)
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
