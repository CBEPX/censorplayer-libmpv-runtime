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


def parse_api_version(value):
    try:
        version = int(value, 10)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid libmpv API version") from error
    if not 0 <= version <= 0xFFFFFFFF:
        raise ValueError("invalid libmpv API version")
    return version


def package(libmpv, search_roots, output, objdump, api_version):
    def add_available(path):
        key = path.name.casefold()
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").digest()
        existing = available.get(key)
        if existing is not None:
            existing_path, existing_digest = existing
            if existing_path.resolve() != path.resolve() or existing_digest != digest:
                raise ValueError(f"duplicate available DLL name: {path.name}")
            return
        available[key] = (path, digest)

    available = {}
    add_available(libmpv)
    for root in search_roots:
        if not root.is_dir():
            raise ValueError(f"search root is not a directory: {root}")
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.casefold() == ".dll":
                add_available(path)

    records = {}
    pending = [libmpv.name.casefold()]
    while pending:
        key = pending.pop()
        if key in records:
            continue
        available_file = available.get(key)
        if available_file is None:
            raise ValueError(f"unresolved non-system import: {key}")
        path, _ = available_file
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
        "libmpv": {
            "path": "libmpv-2.dll",
            "api_version": api_version,
            "api_major": api_version >> 16,
        },
        "files": manifest_files,
    }
    inspection = {
        "schema": 1,
        "libmpv_api_version": api_version,
        "files": inspection_files,
    }
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
    parser.add_argument("--api-version", required=True)
    args = parser.parse_args()

    try:
        api_version = parse_api_version(args.api_version)
        count = package(
            args.libmpv, args.search_root, args.output, args.objdump, api_version
        )
    except (OSError, subprocess.CalledProcessError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"packaged {count} DLLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
