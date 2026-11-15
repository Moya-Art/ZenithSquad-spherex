"""Command line for the pipeline: `python -m pipeline.cli timeline --all`.

Exit codes: 0 every request answered, 2 the archive never answered, 3 bad input.
"""

from __future__ import annotations

import argparse
import json
import sys

from pipeline.catalog import (
    EPOCH_GAP_DAYS,
    ArchiveUnknown,
    load_targets,
    search_epochs,
)

COLLECTIONS = {
    "dr1": ("spherex_dr1",),
    "qr3": ("spherex_qr3",),
    "both": ("spherex_dr1", "spherex_qr3"),
}

EXIT_UNKNOWN = 2
EXIT_USAGE = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="What dates does this patch of sky have?")
    subparsers = parser.add_subparsers(dest="command", required=True)

    timeline = subparsers.add_parser("timeline", help="frames, obs, dates, epochs and gaps")
    timeline.add_argument(
        "--target", action="append", metavar="SLUG", help="repeatable; default every target"
    )
    timeline.add_argument("--all", action="store_true", help="every target in targets.json")
    timeline.add_argument("--collection", choices=sorted(COLLECTIONS), default="both")
    timeline.add_argument("--epoch-gap-days", type=int, default=EPOCH_GAP_DAYS)
    timeline.add_argument(
        "--radius",
        type=float,
        default=0.001,
        help="SIA search radius in degrees (default 0.001; wider finds more frames)",
    )
    timeline.add_argument("--targets", default="data/targets.json")
    timeline.add_argument("--json", action="store_true", help="machine-readable output")

    return parser.parse_args(argv)


def format_table(rows: list[tuple], headers: tuple[str, ...]) -> str:
    widths = [max(len(str(row[index])) for row in (headers, *rows)) for index in range(len(headers))]
    lines = ["  ".join(str(cell).ljust(width) for cell, width in zip(headers, widths))]
    for row in rows:
        lines.append("  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))
    return "\n".join(line.rstrip() for line in lines)


def span_text(summary) -> str:
    if summary.first is None:
        return "no rows"
    return f"{summary.first.isoformat()} → {summary.last.isoformat()}"


def gaps_text(summary) -> str:
    return str(max(summary.gaps)) if summary.gaps else "—"


def wide_gaps_text(summary, threshold: int = 7) -> str:
    wide = [gap for gap in summary.gaps if gap > threshold]
    if not wide:
        return f"none over {threshold} d"
    shown = ", ".join(str(gap) for gap in wide[:8])
    if len(wide) > 8:
        shown += f", … ({len(wide) - 8} more)"
    return shown


def run_timeline(args: argparse.Namespace) -> int:
    targets = load_targets(args.targets)
    if args.target:
        wanted = set(args.target)
        targets = [target for target in targets if target["slug"] in wanted]
        missing = wanted - {target["slug"] for target in targets}
        if missing:
            print(f"unknown target slug(s): {sorted(missing)}", file=sys.stderr)
            return EXIT_USAGE

    collected: dict[str, dict] = {}
    unknown: list[tuple[str, str]] = []

    for target in targets:
        for collection in COLLECTIONS[args.collection]:
            print(f"{target['slug']} / {collection}: querying", file=sys.stderr, flush=True)
            try:
                summary = search_epochs(
                    target["ra"],
                    target["dec"],
                    collection,
                    gap_days=args.epoch_gap_days,
                    radii=(args.radius,),
                )
            except ArchiveUnknown as error:
                print(f"{target['slug']} / {collection}: UNKNOWN — {error}", file=sys.stderr)
                unknown.append((target["slug"], collection))
                continue
            collected.setdefault(target["slug"], {})[collection] = summary

    if args.json:
        print(
            json.dumps(
                {
                    slug: {collection: summary.to_dict() for collection, summary in per.items()}
                    for slug, per in collected.items()
                },
                indent=2,
            )
        )
    else:
        rows = []
        for slug, per in collected.items():
            for collection, summary in per.items():
                rows.append(
                    (
                        slug,
                        collection,
                        summary.n_frames,
                        summary.n_obs,
                        summary.n_dates,
                        span_text(summary),
                        summary.radius_deg,
                        len(summary.epochs),
                        gaps_text(summary),
                    )
                )
        print(
            format_table(
                rows,
                (
                    "target",
                    "collection",
                    "frames",
                    "obs",
                    "dates",
                    "span",
                    "radius",
                    "epochs",
                    "max gap (d)",
                ),
            )
        )

        detail = []
        for slug, per in collected.items():
            for collection, summary in per.items():
                if not summary.epochs:
                    continue
                detail.append(
                    f"\n{slug} / {collection} — {len(summary.epochs)} epoch(s), "
                    f"gap window {args.epoch_gap_days}d"
                )
                for index, epoch in enumerate(summary.epochs, start=1):
                    detail.append(
                        f"  {index}  {epoch.start.isoformat()} → {epoch.end.isoformat()}"
                        f"   {epoch.n_dates:>3} dates  {epoch.n_frames:>4} frames"
                    )
                detail.append(f"  gaps over 7 d: {wide_gaps_text(summary)}")
        if detail:
            print("\n".join(detail))

    return EXIT_UNKNOWN if unknown else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "timeline":
        return run_timeline(args)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
