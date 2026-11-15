#!/usr/bin/env python3
"""Reproduce BUILD_PLAN §1 and diff it against the committed baseline.

Every row is one target in one collection. `PASS` means the archive returned exactly the
baseline numbers, `DRIFT` means it moved (the archive ingests every week), `UNKNOWN` means the
archive never answered — which is not the same as a patch of sky with no data.

Exit codes: 0 all rows pass, 1 at least one row drifted, 2 at least one row is UNKNOWN.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.catalog import ArchiveUnknown, SchemaError, load_targets, search_epochs  # noqa: E402

COLLECTIONS = ("spherex_dr1", "spherex_qr3")
COMPARED = ("frames", "obs", "dates", "first", "last")

DEFAULT_BASELINE = REPO_ROOT / "data" / "baseline" / "counts.json"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_UNKNOWN = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", default="data/targets.json")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument(
        "--radius",
        type=float,
        default=0.001,
        help="SIA search radius in degrees; changing it changes the counts",
    )
    parser.add_argument(
        "--update", action="store_true", help="rewrite the baseline from this measurement"
    )
    return parser.parse_args(argv)


def measure(targets: list[dict], radius: float = 0.001) -> tuple[dict, dict]:
    measured: dict[str, dict] = {}
    errors: dict[tuple[str, str], str] = {}

    for target in targets:
        slug = target["slug"]
        measured[slug] = {}
        for collection in COLLECTIONS:
            try:
                summary = search_epochs(
                    target["ra"], target["dec"], collection, radii=(radius,)
                )
            except (ArchiveUnknown, SchemaError) as error:
                measured[slug][collection] = None
                errors[(slug, collection)] = str(error)
                continue
            measured[slug][collection] = {
                **summary.counts(),
                "radius_deg": summary.radius_deg,
                "bands": summary.bands,
            }

    return measured, errors


def load_baseline(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def describe_drift(current: dict, expected: dict | None) -> str:
    if expected is None:
        return "no baseline row"

    notes = []
    for field in COMPARED:
        now, before = current.get(field), expected.get(field)
        if now == before:
            continue
        if isinstance(now, int) and isinstance(before, int):
            notes.append(f"{field} {now}/{before} ({now - before:+d})")
        else:
            notes.append(f"{field} {now} vs {before}")

    radius_now, radius_before = current.get("radius_deg"), expected.get("radius_deg")
    if "radius_deg" in expected and radius_now != radius_before:
        notes.append(f"radius {radius_now} vs {radius_before}")

    bands_before = expected.get("bands")
    if bands_before is not None:
        bands_now = current.get("bands") or {}
        for band in sorted(set(bands_now) | set(bands_before)):
            now_band = bands_now.get(band, {})
            before_band = bands_before.get(band, {})
            for field in ("frames", "dates"):
                if now_band.get(field) != before_band.get(field):
                    notes.append(f"{band} {field} {now_band.get(field)}/{before_band.get(field)}")

    if len(notes) > 6:
        return ", ".join(notes[:6]) + f", … ({len(notes) - 6} more)"

    return ", ".join(notes)


def pair(value, expected) -> str:
    return f"{value}" if expected is None else f"{value}/{expected}"


def format_table(rows: list[tuple], headers: tuple[str, ...]) -> str:
    widths = [max(len(str(row[index])) for row in (headers, *rows)) for index in range(len(headers))]
    lines = ["  ".join(str(cell).ljust(width) for cell, width in zip(headers, widths))]
    for row in rows:
        lines.append("  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))
    return "\n".join(line.rstrip() for line in lines)


def write_baseline(path: Path, measured: dict, existing: dict) -> None:
    merged: dict[str, dict] = {}
    for slug, per_collection in measured.items():
        merged[slug] = {}
        for collection, counts in per_collection.items():
            if counts is not None:
                merged[slug][collection] = counts
            elif existing.get("targets", {}).get(slug, {}).get(collection):
                merged[slug][collection] = existing["targets"][slug][collection]

    payload = {
        "measured": date.today().isoformat(),
        "source": "python3 scripts/verify_counts.py --update",
        "targets": merged,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    baseline_path = Path(args.baseline)
    baseline = load_baseline(baseline_path)
    baseline_targets = baseline.get("targets", {})

    targets = load_targets(args.targets)
    measured, errors = measure(targets, radius=args.radius)

    rows: list[tuple] = []
    drifted = 0
    unknown = 0

    for target in targets:
        slug = target["slug"]
        for collection in COLLECTIONS:
            counts = measured[slug][collection]
            if counts is None:
                unknown += 1
                rows.append((slug, collection, "—", "—", "—", f"UNKNOWN  {errors[(slug, collection)]}"))
                continue

            expected = baseline_targets.get(slug, {}).get(collection)
            drift = describe_drift(counts, expected)
            if drift:
                drifted += 1

            rows.append(
                (
                    slug,
                    collection,
                    pair(counts["frames"], (expected or {}).get("frames")),
                    pair(counts["obs"], (expected or {}).get("obs")),
                    pair(counts["dates"], (expected or {}).get("dates")),
                    f"DRIFT ({drift})" if drift else "PASS",
                )
            )

    print(format_table(rows, ("target", "collection", "frames", "obs", "dates", "status")))
    print(
        f"\n{len(rows)} rows: {len(rows) - drifted - unknown} PASS, {drifted} DRIFT, {unknown} UNKNOWN"
    )

    if args.update:
        write_baseline(baseline_path, measured, baseline)
        print(f"baseline written to {baseline_path}")
        return EXIT_UNKNOWN if unknown else EXIT_OK

    if unknown:
        return EXIT_UNKNOWN
    if drifted:
        return EXIT_DRIFT
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
