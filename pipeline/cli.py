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

    build = subparsers.add_parser("build", help="build one target's blink sequence")
    build.add_argument("--target", required=True, metavar="SLUG")
    build.add_argument("--band", help="override the band chosen by the date count")
    build.add_argument("--size", type=float, default=0.3, help="cutout size in degrees")
    build.add_argument("--collection", choices=("dr1", "qr3"), default="dr1")
    build.add_argument("--workers", type=int, default=8)
    build.add_argument("--out", default="data/fallback")
    build.add_argument("--cache", default="data/cache")
    build.add_argument("--targets", default="data/targets.json")
    build.add_argument("--refresh", action="store_true", help="ignore cached FITS")

    cube = subparsers.add_parser("cube", help="build one target's 102-plane spectrum cube")
    cube.add_argument("--target", metavar="SLUG", help="a slug from targets.json")
    cube.add_argument("--ra", type=float, help="right ascension in degrees, instead of --target")
    cube.add_argument("--dec", type=float, help="declination in degrees, instead of --target")
    cube.add_argument("--size", type=float, default=0.3, help="field in degrees (min window 160 px)")
    cube.add_argument("--out", default="data/fallback")
    cube.add_argument("--cache", default="data/cache")
    cube.add_argument("--tiles", default="data/cache/cube_tiles", help="where cube tiles are kept")
    cube.add_argument("--version", help="pin a HiPS release instead of discovering the newest")
    cube.add_argument("--targets", default="data/targets.json")
    cube.add_argument("--refresh", action="store_true", help="re-download the tile")

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


def run_build(args: argparse.Namespace) -> int:
    from pathlib import Path

    from pipeline.sequence import DownloadFailed, SequenceRequest, build_sequence

    request = SequenceRequest(
        slug=args.target,
        collection=COLLECTIONS[args.collection][0],
        band=args.band,
        size_deg=args.size,
        out_root=Path(args.out),
        cache_dir=Path(args.cache),
        workers=args.workers,
        refresh=args.refresh,
        targets_path=args.targets,
    )

    def progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        manifest = build_sequence(request, progress=progress)
    except KeyError as error:
        print(f"unknown target slug: {error}", file=sys.stderr)
        return EXIT_USAGE
    except (ArchiveUnknown, DownloadFailed) as error:
        print(f"archive did not answer: {error}", file=sys.stderr)
        return EXIT_UNKNOWN
    except ValueError as error:
        print(f"cannot build: {error}", file=sys.stderr)
        return EXIT_USAGE

    print_manifest(manifest)
    return 0


def print_manifest(manifest: dict) -> None:
    rows = []
    for frame in manifest["frames"]:
        measure = frame.get("measure")
        rows.append(
            (
                frame["date"],
                "—" if measure is None else measure.get("frames_available", "—"),
                "—" if measure is None else f"{measure['flux']:.4f}",
                "—" if measure is None or measure["snr"] is None else f"{measure['snr']:.1f}",
                f"{frame['bad_fraction']:.4f}",
                "yes" if frame["saturated"] else "no",
                f"{frame['bytes'] / 1024:.1f}",
            )
        )
    print(
        format_table(
            rows,
            ("date", "frames", "flux (mJy)", "snr", "bad_frac", "saturated", "webp KB"),
        )
    )

    motion = manifest.get("motion")
    print(
        f"\n{manifest['target']} {manifest['band']} — {manifest['n_frames']} dates, "
        f"one stretch vmin={manifest['vmin']:.3f} vmax={manifest['vmax']:.3f}"
    )
    if motion is None:
        print(
            "no motion: fewer than two frames could be measured "
            "(the target fell outside clipped cutouts)"
        )
    else:
        print(
            f"first-to-last {motion['total_arcsec']:.2f} arcsec over {motion['dt_years']:.2f} yr; "
            f"fitted rate {motion['slope_arcsec_per_year'][0]:+.2f}, "
            f"{motion['slope_arcsec_per_year'][1]:+.2f} arcsec/yr "
            f"(scatter {motion['rms_scatter_arcsec'][0]:.2f}, "
            f"{motion['rms_scatter_arcsec'][1]:.2f})"
        )
        print(f"significant: {'yes' if motion['significant'] else 'no'}; "
              f"reliable: {'yes' if motion.get('reliable', True) else 'no'}")

    if manifest.get("saturated_any"):
        print(
            "note: the target core is saturated, so measure is null — flux is not measurable, "
            "only a lower bound"
        )
    if not motion.get("reliable", True):
        print(
            "note: a saturated core's centroid drifts with the roll angle of each visit; the "
            "first-to-last number is not motion"
        )
    oversized = [
        frame["date"] for frame in manifest["frames"] if frame["bytes"] > 60_000
    ]
    if oversized:
        print(f"warning: over 60 KB: {oversized}")


def run_cube(args: argparse.Namespace) -> int:
    from pathlib import Path

    from pipeline.catalog import SchemaError
    from pipeline.cube import CubeRequest, TileUnavailable, build_cube
    from pipeline.sequence import PositionSpec

    if args.target:
        record = next(
            (item for item in load_targets(args.targets) if item["slug"] == args.target), None
        )
        if record is None:
            print(f"unknown target slug: {args.target!r}", file=sys.stderr)
            return EXIT_USAGE
        position = PositionSpec(
            ra=record["ra"],
            dec=record["dec"],
            label=record["slug"],
            name=record.get("name", record["slug"]),
            pm_ra_cosdec=record.get("pm_ra_cosdec"),
            pm_dec=record.get("pm_dec"),
        )
    elif args.ra is not None and args.dec is not None:
        position = PositionSpec(
            ra=args.ra,
            dec=args.dec,
            label=f"ra{args.ra:.4f}_dec{args.dec:.4f}",
            name=f"RA {args.ra:.4f}, Dec {args.dec:+.4f}",
        )
    else:
        print("give --target, or both --ra and --dec", file=sys.stderr)
        return EXIT_USAGE

    request = CubeRequest(
        position=position,
        size_deg=args.size,
        out_root=Path(args.out),
        cache_dir=Path(args.cache),
        tile_cache_dir=Path(args.tiles),
        version=args.version,
        refresh=args.refresh,
    )

    def progress(update: dict) -> None:
        done = update.get("planes_done")
        total = update.get("planes_total")
        message = update.get("message") or update.get("stage", "")
        if done and total:
            print(f"{done:3d}/{total}  {message}", file=sys.stderr, flush=True)
        else:
            print(message, file=sys.stderr, flush=True)

    try:
        manifest = build_cube(request, progress=progress)
    except (ArchiveUnknown, SchemaError, TileUnavailable) as error:
        print(f"archive did not answer: {error}", file=sys.stderr)
        return EXIT_UNKNOWN
    except (KeyError, ValueError) as error:
        print(f"cannot build: {error}", file=sys.stderr)
        return EXIT_USAGE

    print_cube(manifest)
    return 0


def print_cube(manifest: dict) -> None:
    points = {point["index"]: point for point in manifest["spectrum"]["points"]}
    rows = []
    for plane in manifest["planes"]:
        point = points.get(plane["index"], {})
        flux = point.get("flux_mjy")
        rows.append(
            (
                plane["index"],
                plane["band"],
                plane["channel"],
                f"{plane['wavelength_um']:.3f}",
                f"{plane['bandwidth_um']:.3f}",
                "blank" if plane["blank"] else f"{plane['coverage']:.2f}",
                plane["nan_pixels"],
                "—" if flux is None else f"{flux:.4f}",
                f"{plane['bytes'] / 1024:.1f}",
            )
        )
    print(
        format_table(
            rows,
            ("idx", "band", "ch", "um", "width", "cover", "nan", "flux (mJy)", "webp KB"),
        )
    )

    composite = manifest["composite"]
    named = ", ".join(
        f"{channel['channel']} {channel['wavelength_um']:.2f} um ({channel['band']})"
        for channel in composite["channels"]
    )
    spectrum = manifest["spectrum"]
    peak = spectrum.get("peak_index")
    peak_flux = "—" if peak is None else f"{points[peak]['flux_mjy']:.4f}"
    print(
        f"\n{manifest['target']} — {manifest['depth']} planes, "
        f"{manifest['crop_px']}x{manifest['crop_px']} px "
        f"({manifest['crop_arcmin']:.1f} arcmin) at {manifest['pixscale_arcsec']:.2f} arcsec/px"
    )
    print(
        f"one asinh stretch for all planes: vmin={manifest['stretch']['vmin']:.4f} "
        f"vmax={manifest['stretch']['vmax']:.4f} MJy/sr"
    )
    print(f"tile {manifest['tile']['version']} Npix{manifest['tile']['ipix']} "
          f"({manifest['tile']['bytes']:,} B), mosaic epoch "
          f"{manifest['tile']['mosaic_epoch']:.2f}")
    print(f"composite: {named} ({composite['bytes'] / 1024:.1f} KB)")
    print(f"spectrum peak: {peak_flux} mJy at plane {peak}")
    if manifest["blank_planes"]:
        print(f"blank planes: {manifest['blank_planes']} (dichroic channels, no data by design)")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "timeline":
        return run_timeline(args)
    if args.command == "build":
        return run_build(args)
    if args.command == "cube":
        return run_cube(args)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
