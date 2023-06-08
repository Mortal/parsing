#!/usr/bin/env python3
import argparse
import os
import subprocess
import tempfile
from typing import Callable

SIZE_THRESHOLD = 1024 * 1024 * 40


def default_merge(
    ancestor: str,
    ancestor_name: str,
    current: str,
    current_name: str,
    other: str,
    other_name: str,
    conflict_marker_size: int,
) -> bool:
    """Merge files using git merge-file"""
    code = subprocess.call(
        [
            "git",
            "merge-file",
            "-L",
            current_name,
            "-L",
            ancestor_name,
            "-L",
            other_name,
            current,
            ancestor,
            other,
        ]
    )
    return code == 0


def merge(
    ancestor: str,
    current: str,
    other: str,
    name: str,
    conflict_marker_size: int,
    smart_merge: Callable[[str, str, str], tuple[str, str, str]],
) -> bool:
    """Merge other and current into current"""

    # Check if files are too lange
    if (
        os.path.getsize(ancestor) > SIZE_THRESHOLD
        or os.path.getsize(current) > SIZE_THRESHOLD
        or os.path.getsize(other) > SIZE_THRESHOLD
    ):
        # print("Cannot merge large files")
        return default_merge(
            ancestor, ancestor, current, current, other, other, conflict_marker_size
        )

    # Read the input files
    with open(ancestor, "rb") as f:
        ancestor_bytes = f.read()

    with open(current, "rb") as f:
        current_bytes = f.read()

    with open(other, "rb") as f:
        other_bytes = f.read()

    # Decode text as utf8
    try:
        ancestor_text = ancestor_bytes.decode(encoding="UTF-8", errors="strict")
        current_text = current_bytes.decode(encoding="UTF-8", errors="strict")
        other_text = other_bytes.decode(encoding="UTF-8", errors="strict")
    except UnicodeError:
        # print("Cannot merge binary files")
        return default_merge(
            ancestor, ancestor, current, current, other, other, conflict_marker_size
        )

    ancestor_text, current_text, other_text = smart_merge(
        ancestor_text, current_text, other_text
    )

    # Write back the merged changes
    with open(current, "wb") as f:
        f.write(current_text.encode("UTF-8"))

    # Check if we successfully merged conflics we know about
    if current_text == other_text:
        return True

    # Otherwise let git merge-files do the rest of the work
    with tempfile.TemporaryDirectory() as td:
        anc = os.path.join(td, os.path.basename(ancestor))
        oth = os.path.join(td, os.path.basename(other))
        with open(anc, "wb") as f:
            f.write(ancestor_text.encode("UTF-8"))
        with open(oth, "wb") as f:
            f.write(other_text.encode("UTF-8"))
        return default_merge(
            anc, ancestor, current, current, oth, other, conflict_marker_size
        )


def merging_main(smart_merge: Callable[[str, str, str], tuple[str, str, str]]) -> None:
    parser = argparse.ArgumentParser(description="Merge files")
    parser.add_argument("ancestor", type=str, help="Path to ancestor file")
    parser.add_argument("current", type=str, help="Path to our file")
    parser.add_argument("other", type=str, help="Path to other file")
    parser.add_argument(
        "--name", type=str, help="Name of the output file", required=True
    )
    parser.add_argument(
        "--conflict-marker-size", type=int, help="Length of conflict marker", default=7
    )
    args = parser.parse_args()

    if not merge(
        args.ancestor,
        args.current,
        args.other,
        args.name,
        args.conflict_marker_size,
        smart_merge,
    ):
        raise SystemExit(1)
