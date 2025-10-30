#!/usr/bin/env python3

import argparse
import re
import shutil
import sys
from pathlib import Path

CENT_EVENT_PATTERN = re.compile(r"^cent_(\d+_\d+)_event_(\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy JetData.h5 files from a flat centrality/event directory layout "
            "into an existing hydro_files directory tree."
        )
    )
    parser.add_argument(
        "source_root",
        type=Path,
        help=(
            "Path that contains directories named like "
            "cent_<low>_<high>_event_<number> with JetData.h5 inside."
        ),
    )
    parser.add_argument(
        "destination_root",
        type=Path,
        help=(
            "Destination hydro_files directory (e.g. hydro_files_OO) that contains "
            "sub-directories cent_<low>_<high>/event-<number>."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.expanduser().resolve()
    destination_root = args.destination_root.expanduser().resolve()

    if not source_root.is_dir():
        print(f"[error] Source directory does not exist: {source_root}", file=sys.stderr)
        return 1
    if not destination_root.is_dir():
        print(
            f"[error] Destination directory does not exist: {destination_root}",
            file=sys.stderr,
        )
        return 1

    copied = 0
    skipped_missing_source = []
    skipped_missing_destination = []
    skipped_unmatched = []

    for entry in sorted(source_root.iterdir()):
        if not entry.is_dir():
            continue

        match = CENT_EVENT_PATTERN.match(entry.name)
        if not match:
            skipped_unmatched.append(entry.name)
            continue

        centrality_part, event_number_str = match.groups()
        event_number = int(event_number_str)

        source_file = entry / "JetData.h5"
        if not source_file.is_file():
            skipped_missing_source.append(str(source_file))
            continue

        destination_dir = (
            destination_root / f"cent_{centrality_part}" / f"event-{event_number}"
        )
        if not destination_dir.is_dir():
            skipped_missing_destination.append(str(destination_dir))
            continue

        destination_file = destination_dir / "JetData.h5"
        shutil.copy2(source_file, destination_file)
        copied += 1

    print(f"[info] Copied {copied} JetData.h5 file(s).")

    if skipped_missing_source:
        print("[warn] Source JetData.h5 missing for:")
        for path in skipped_missing_source:
            print(f"  - {path}")

    if skipped_missing_destination:
        print("[warn] Destination event directory missing for:")
        for path in skipped_missing_destination:
            print(f"  - {path}")

    if skipped_unmatched:
        print("[warn] Skipped entries with unexpected names:")
        for name in skipped_unmatched:
            print(f"  - {name}")

    return 0 if not (skipped_missing_source or skipped_missing_destination) else 1


if __name__ == "__main__":
    sys.exit(main())
