#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

if __package__:
    from .verify_runtime import LIBMPV_NAME, verify
else:
    from verify_runtime import LIBMPV_NAME, verify


def overlay(manifest, inspection, candidate, target):
    candidate_dlls = verify(manifest, inspection, candidate)

    if not target.is_dir():
        raise ValueError(f"target is not a directory: {target}")
    # Only app-directory DLLs participate in this collision policy; nested
    # extension DLLs remain untouched while the new app copy wins load order.
    existing = {
        path.name.casefold(): path
        for path in target.iterdir()
        if path.is_file() and path.suffix.casefold() == ".dll"
    }
    if LIBMPV_NAME not in existing:
        raise ValueError("target has no stock libmpv-2.dll")
    for record in manifest["files"]:
        key = record["path"].casefold()
        if key in existing and key != LIBMPV_NAME:
            raise ValueError(f"target DLL collision: {existing[key].name}")

    # ponytail: the CI target is disposable; add staging/rollback before using
    # this helper for user-owned installations.
    for record in manifest["files"]:
        key = record["path"].casefold()
        source = candidate_dlls[key]
        destination = (
            existing[LIBMPV_NAME]
            if key == LIBMPV_NAME
            else target / record["path"]
        )
        shutil.copy2(source, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"target copy mismatch: {record['path']}")
    return len(manifest["files"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--inspection", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        inspection = json.loads(args.inspection.read_text(encoding="utf-8"))
        count = overlay(manifest, inspection, args.candidate, args.target)
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"overlaid {count} verified DLLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
