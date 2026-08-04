#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from verify_runtime import is_system_dll, verify


def inspect(objdump, path):
    header = subprocess.run(
        [objdump, "-f", path], check=True, capture_output=True, text=True
    ).stdout
    details = subprocess.run(
        [objdump, "-p", path], check=True, capture_output=True, text=True
    ).stdout
    match = re.search(r"\bfile format (\S+)", header)
    if not match:
        raise ValueError(f"{path.name}: objdump did not report a PE machine")
    return {
        "path": path.name,
        "machine": match.group(1),
        "exports": re.findall(r"^\s*\[\s*\d+\]\s+(mpv_[A-Za-z0-9_]+)\s*$", details, re.M),
        "imports": re.findall(r"^\s*DLL Name:\s*(\S+)\s*$", details, re.M),
    }


def package(libmpv, search_roots, output, objdump):
    available = {libmpv.name.casefold(): libmpv}
    for root in search_roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.casefold() == ".dll":
                available.setdefault(path.name.casefold(), path)

    records = {}
    pending = [libmpv.name.casefold()]
    while pending:
        key = pending.pop()
        if key in records:
            continue
        path = available.get(key)
        if path is None:
            raise ValueError(f"unresolved non-system import: {key}")
        record = inspect(objdump, path)
        records[key] = (path, record)
        for imported in record["imports"]:
            imported_key = imported.casefold()
            if imported_key not in records and not is_system_dll(imported):
                pending.append(imported_key)

    output.mkdir(parents=True, exist_ok=False)
    manifest_files = []
    inspection_files = []
    for key in sorted(records):
        source, inspection = records[key]
        destination = output / source.name
        shutil.copy2(source, destination)
        content = destination.read_bytes()
        manifest_files.append(
            {
                "path": destination.name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        inspection_files.append(inspection)

    manifest = {
        "schema": 1,
        "target": {"os": "windows", "arch": "x86_64"},
        "libmpv": {"path": "libmpv-2.dll", "api_major": 2},
        "files": manifest_files,
    }
    inspection = {"schema": 1, "files": inspection_files}
    (output / "runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (output / "pe-inspection.json").write_text(
        json.dumps(inspection, indent=2) + "\n", encoding="utf-8"
    )
    verify(manifest, inspection, output)
    return len(manifest_files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--libmpv", required=True, type=Path)
    parser.add_argument("--search-root", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--objdump", required=True)
    args = parser.parse_args()

    try:
        count = package(
            args.libmpv, args.search_root, args.output, args.objdump
        )
    except (OSError, subprocess.CalledProcessError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"packaged {count} DLLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
