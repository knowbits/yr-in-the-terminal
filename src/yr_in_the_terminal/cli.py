"""Unified `yr` CLI entry point: dispatches to the `today`/`forecast` subcommands."""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from yr_in_the_terminal import common, forecast, today


class _HelpFormatter(argparse.HelpFormatter):
    """Like the default formatter, except help text containing an explicit
    "\\n" keeps those as separate paragraphs instead of being re-flowed into
    one wrapped blob -- lets a compound option's help (see --hours) read as
    short, separate facts. Each paragraph is still wrapped to `width` on its
    own, so an overlong one wraps safely instead of overflowing the caller's
    box. Text with no "\\n" auto-wraps normally, unchanged."""

    def _split_lines(self, text: str, width: int) -> list[str]:
        if "\n" in text:
            return [wrapped for line in text.splitlines() for wrapped in (textwrap.wrap(line, width) or [""])]
        return super()._split_lines(text, width)


def _add_shared_options(group: argparse._ArgumentGroup) -> None:
    """Options identical on both `yr today` and `yr forecast` -- added to a
    named argument group (rather than via a parents=[...] parser) purely so
    _print_top_level_help can pull out just this group's option text via
    argparse's own formatter, as the single source of truth for the one
    consolidated `yr --help` screen (there is no separate `yr today --help`/
    `yr forecast --help` display -- see main())."""
    group.add_argument("--lat", type=float, default=None, help="Latitude -- use together with --lon")
    group.add_argument("--lon", type=float, default=None, help="Longitude -- use together with --lat")
    group.add_argument(
        "--place",
        default=None,
        help="Location label shown in the title; optional, goes with --lat/--lon",
    )
    group.add_argument("--no-cache", action="store_true", help="Bypass the local response cache")
    group.add_argument(
        "--here",
        action="store_true",
        help=(
            "Use IP geolocation for the location.\n"
            "UNRELIABLE -- depends on your ISP/mobile provider.\n"
            "Prefer --location or --lat/--lon instead."
        ),
    )
    group.add_argument(
        "--location",
        default=None,
        help=(
            "Resolve lat/lon/place from a place name\n"
            "via OpenStreetMap Nominatim.\n"
            'Example: --location "Springfield, Illinois"\n'
            "Ambiguous names list all matches, ask for a region."
        ),
    )
    group.add_argument(
        "--set-location",
        metavar="PLACE",
        default=None,
        help=(
            "Like --location, but also saves the resolved place\n"
            "as the settings file's \\[location] default.\n"
            'Example: --set-location "Bergen, Norway"\n'
            "Never persists --here's IP-guessed location."
        ),
    )
    group.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of a table")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="yr.no (MET Norway) weather forecasts in the terminal.")
    sub = ap.add_subparsers(dest="command", required=True)

    today_p = sub.add_parser(
        "today",
        description="Detailed today-only yr.no forecast: hourly table + radar rain nowcast.",
        formatter_class=_HelpFormatter,
    )
    _add_shared_options(today_p.add_argument_group("shared"))
    today_only = today_p.add_argument_group("today-only")
    today_only.add_argument(
        "--hours",
        type=int,
        default=None,
        help=(
            "Number of hourly rows to show.\n"
            "Default: rest of today, min 12 hours.\n"
            r"Configurable via \[today].min_hours in the settings file."
        ),
    )
    today_p.set_defaults(func=today.run)

    forecast_p = sub.add_parser("forecast", description="7-day yr.no forecast table.", formatter_class=_HelpFormatter)
    _add_shared_options(forecast_p.add_argument_group("shared"))
    forecast_only = forecast_p.add_argument_group("forecast-only")
    forecast_only.add_argument("--days", type=int, default=7, help="Number of forecast days to show")
    forecast_only.add_argument(
        "--exclude-night", action="store_true", help="Only use hours 06:00-24:00 for temps/rain/sun"
    )
    forecast_p.set_defaults(func=forecast.run)

    return ap


def add_border(text: str, *, padding: int = 1, color: str = "yellow") -> str:
    """Wrap `text` in a rounded-corner Unicode frame, sized to the block's
    own widest line -- not a fixed console width -- so the caller stays in
    control of wrapping and the frame always lines up around it. `text` may
    itself contain Rich markup (e.g. "[bold green]...[/bold green]"); width
    is measured via Rich's own cell_len on the *rendered* text, so those
    tags don't throw off the frame's alignment. `padding` is the number of
    blank columns added inside the frame on each side; `color` is a Rich
    style name applied only to the frame characters, not the content.
    Returns a Rich-markup string, meant to be printed with markup enabled
    (Rich's default), not raw text.

    `text` must be free of raw ANSI escape codes -- only Rich's own "[tag]"
    markup is measured by cell_len below; a stray "\\x1b[...m" sequence is
    counted as literal characters (or dropped in ways cell_len can't
    predict), which silently corrupts the width math and the right border
    comes out ragged. This bit Python 3.13+'s argparse.HelpFormatter: it
    injects its own ANSI colour codes into formatted option text when
    connected to a real terminal (see `_format_group`'s `color=False`) --
    invisible when piped/redirected, since that's the one condition where
    argparse's colourizer stays off, which is exactly why it only ever
    showed up live in an interactive terminal and never in a captured run.
    """
    # rstrip each line first: trailing whitespace (a stray space/tab left by
    # the caller) shouldn't inflate the frame -- only real content width
    # should decide it.
    lines = [line.rstrip() for line in text.splitlines()] or [""]
    visible_widths = [Text.from_markup(line).cell_len for line in lines]
    inner_width = max(visible_widths, default=0)
    pad = " " * padding

    # Phase 1: pad every line to one identical, rectangular width with plain
    # SPACE characters -- a square block where every row has the exact same
    # rendered length. This has to happen before any border character is
    # added: only once every row is the same width is it safe to put a
    # vertical line at the same index position on each of them and have it
    # come out straight.
    padded_lines = [line + " " * (inner_width - width) for line, width in zip(lines, visible_widths)]

    # Phase 2: the block is now square -- wrap each already-uniform row with
    # the coloured vertical border.
    horizontal = "─" * (inner_width + padding * 2)
    top = f"[{color}]╭{horizontal}╮[/{color}]"
    bottom = f"[{color}]╰{horizontal}╯[/{color}]"
    body = "\n".join(f"[{color}]│[/{color}]{pad}{line}{pad}[{color}]│[/{color}]" for line in padded_lines)
    return f"{top}\n{body}\n{bottom}"


# Column width for the two command labels in _print_top_level_help's listing
# ("yr forecast" is the longer of the two, plus 2 trailing spaces).
_CMD_COL = len("yr forecast") + 2


def _settings_file_display() -> str:
    """Settings file path, home-relative (~/...) when it's under $HOME."""
    path = common.default_config_path()
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _format_group(parser: argparse.ArgumentParser, title: str, width: int) -> str:
    """Render just one named argument group's option lines via argparse's own
    formatter -- so the option text/wrapping stays defined once, in
    build_parser's add_argument calls, not retyped by hand here. `width` must
    match the Panel's actual inner width the caller wraps this in, or Rich
    re-wraps these already-wrapped lines a second time and mangles them."""
    group = next(g for g in parser._action_groups if g.title == title)
    # color=False: Python 3.13+'s HelpFormatter can inject its own raw ANSI
    # escape codes into the formatted text (bolding flags/metavars) when
    # connected to a real terminal -- independent of, and invisible to, the
    # Rich markup we wrap this in. `add_border`'s width measurement only
    # understands Rich's own "[tag]" markup, not raw ANSI codes, so those
    # extra bytes silently corrupt its padding math and the right border
    # comes out ragged (only ever visible on a real tty, never when piped).
    # We already colour everything ourselves via Rich markup, so argparse's
    # own colourizer must stay off. Older Pythons predate the `color` kwarg
    # entirely and never had this problem, hence the fallback.
    try:
        formatter = parser.formatter_class(prog=parser.prog, width=width, color=False)
    except TypeError:
        formatter = parser.formatter_class(prog=parser.prog, width=width)
    formatter.start_section(None)
    formatter.add_arguments(group._group_actions)
    formatter.end_section()
    return formatter.format_help().rstrip("\n")


def _print_top_level_help(ap: argparse.ArgumentParser) -> None:
    """The one and only `yr --help` screen. There is no separate `yr today
    --help` / `yr forecast --help` page -- main() routes -h/--help here no
    matter where it appears -- so every option is documented in exactly one
    place instead of two near-identical, mostly-duplicate subcommand pages."""
    today_p = ap._subparsers._group_actions[0].choices["today"]
    forecast_p = ap._subparsers._group_actions[0].choices["forecast"]
    # Pinned, not auto-detected: some environments report a console width
    # here that the real terminal doesn't honor, wrapping option text wider
    # than the terminal actually accommodates. 76 is safe virtually anywhere.
    inner_width = 76

    def cmd_line(label: str, desc: str) -> str:
        return f"  [bold green]{label}[/bold green]{' ' * (_CMD_COL - len(label))}{desc}"

    def example_line(desc: str) -> str:
        return f"  {' ' * _CMD_COL}{desc}"

    body = (
        "[blue_violet]DESCRIPTION: yr.no (MET Norway) weather forecasts in the terminal.[/blue_violet]\n\n"
        "USAGE: [bold green]yr today[/bold green] [OPTIONS]\n"
        "       [bold green]yr forecast[/bold green] [OPTIONS]\n\n"
        "Two commands:\n\n"
        f"{cmd_line('yr today', 'Hour-by-hour forecast for the rest of today + a rain chart')}\n"
        f"{example_line('Example: yr today --location "Bergen, Norway"')}\n\n"
        f"{cmd_line('yr forecast', '7-day forecast, one row per day')}\n"
        f"{example_line('Example: yr forecast --days 5 --exclude-night')}\n\n"
        "[bold blue_violet]OPTIONS (shared by both commands):[/bold blue_violet]\n"
        f"{_format_group(today_p, 'shared', inner_width)}\n\n"
        "[bold blue_violet]TODAY-ONLY OPTIONS:[/bold blue_violet]\n"
        f"{_format_group(today_p, 'today-only', inner_width)}\n\n"
        "[bold blue_violet]FORECAST-ONLY OPTIONS:[/bold blue_violet]\n"
        f"{_format_group(forecast_p, 'forecast-only', inner_width)}\n\n"
        f"Settings file:\n   [green]{_settings_file_display()}[/green]"
    )
    # highlight=False: otherwise Rich's default auto-highlighter colors quoted
    # strings (e.g. "Bergen, Norway" above) green on its own, on top of the
    # explicit [color] markup used here. soft_wrap=True: add_border already
    # built an exact rectangle -- without this, Rich re-wraps/re-justifies
    # those already-fixed-width lines against its own detected console
    # width, breaking the right border into a ragged line.
    Console().print(add_border(body, color="yellow"), highlight=False, soft_wrap=True)


# Sentinel returned by resolve_location when nothing at all was given (no
# --lat/--lon, --location, --here, or [location] config) -- main() shows a
# dedicated "set a default" panel for this instead of the generic error one.
NO_LOCATION_ERROR = "__no_location_configured__"


def resolve_location(args: argparse.Namespace, config: dict) -> str | None:
    """Fill in args.lat/lon/place from --location/--set-location, --here, or
    the settings file's [location] section, in that order, skipped if
    --lat/--lon were given explicitly. Returns an error message if none of
    those resolve a location (or the one that was tried fails), else None --
    there is no silent IP-geolocation fallback for an unconfigured location;
    only --here opts into that explicitly. If nothing at all was given,
    returns the NO_LOCATION_ERROR sentinel instead of a plain message.

    --set-location resolves exactly like --location, but additionally
    persists the resolved place to the settings file on success (an
    ambiguous or failed lookup persists nothing). --here's IP-guessed
    location is never persisted, by design -- there's no code path from it
    to set_config_location."""
    loc_cfg = config.get("location", {})
    explicit = args.lat is not None or args.lon is not None
    location_query = args.set_location or args.location
    flag = "--set-location" if args.set_location else "--location"

    if not explicit and location_query:
        candidates = common.geocode_candidates(location_query, limit=5, config=config)
        if not candidates:
            print(f"warning: could not resolve {flag} {location_query!r}", file=sys.stderr)
        elif len(candidates) == 1:
            args.lat, args.lon, args.place = candidates[0]
            if args.set_location:
                common.set_config_location(args.place)
                print(f"note: saved {args.place!r} as your default location", file=sys.stderr)
        else:
            listing = "\n".join(f"  {lat:.4f}, {lon:.4f}  {label}" for lat, lon, label in candidates)
            example = candidates[0][2]
            return (
                f"The {location_query!r} location is ambiguous, found {len(candidates)} matches:\n\n"
                f"{listing}\n\n"
                f"Add a region to {flag} to disambiguate\n"
                "Use one of the matched locations above instead, e.g.:\n"
                f'  [green]yr {args.command} {flag} "{example}"[/green]'
            )
    elif not explicit and args.here:
        resolved = common.resolve_default_location(None, None, None)
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
    elif not explicit and loc_cfg.get("place"):
        resolved = common.geocode(loc_cfg["place"], config=config)
        if resolved is None:
            print(f"warning: could not resolve configured location {loc_cfg['place']!r}", file=sys.stderr)
        else:
            args.lat, args.lon, args.place = resolved

    if args.lat is None or args.lon is None:
        if not explicit and not location_query and not args.here and not loc_cfg.get("place"):
            return NO_LOCATION_ERROR
        return (
            "no location given -- pass --lat/--lon, --location <name>, or --here, "
            r"or set \[location] place in the settings file (see README)"
        )

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

    # -h/--help anywhere (bare "yr --help", or after "today"/"forecast") goes
    # to the one consolidated help screen -- there is no separate per-command
    # --help page; see _print_top_level_help's docstring for why.
    if any(a in ("-h", "--help") for a in argv):
        _print_top_level_help(ap)
        return 0

    args = ap.parse_args(argv)
    common.set_cache_enabled(not args.no_cache)

    config = common.load_config(default_toml=common.DEFAULT_CONFIG_TOML)
    error = resolve_location(args, config)
    if error == NO_LOCATION_ERROR:
        Console(stderr=True).print(
            Panel(
                "No DEFAULT location has been set yet!\n\n"
                "Set a real default so you don't need this guess every time:\n"
                '  [green]yr today --set-location "Your City"[/green]\n\n'
                r"or add \[location] place to the settings file (see README).",
                title="⚠ No default location set",
                border_style="red",
                expand=False,
            )
        )
        return 1
    if error:
        Console(stderr=True).print(Panel(error, title="✖ Error", title_align="left", border_style="red", expand=False))
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
