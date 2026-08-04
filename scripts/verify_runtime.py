#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import sys


REQUIRED_EXPORTS = {
    "mpv_client_api_version",
    "mpv_command",
    "mpv_create",
    "mpv_initialize",
    "mpv_terminate_destroy",
    "mpv_wait_event",
}
SYSTEM_DLLS = {
    "advapi32.dll",
    "avrt.dll",
    "bcrypt.dll",
    "cfgmgr32.dll",
    "comctl32.dll",
    "comdlg32.dll",
    "crypt32.dll",
    "d3d11.dll",
    "d3d12.dll",
    "d3dcompiler_47.dll",
    "dcomp.dll",
    "ddraw.dll",
    "dinput8.dll",
    "dsound.dll",
    "dwmapi.dll",
    "dwrite.dll",
    "dxgi.dll",
    "dxva2.dll",
    "gdi32.dll",
    "hid.dll",
    "imm32.dll",
    "iphlpapi.dll",
    "kernel32.dll",
    "mf.dll",
    "mfplat.dll",
    "mfreadwrite.dll",
    "mfuuid.dll",
    "mmdevapi.dll",
    "mpr.dll",
    "msvcrt.dll",
    "ntdll.dll",
    "ole32.dll",
    "oleaut32.dll",
    "powrprof.dll",
    "propsys.dll",
    "psapi.dll",
    "rpcrt4.dll",
    "secur32.dll",
    "setupapi.dll",
    "shcore.dll",
    "shell32.dll",
    "shlwapi.dll",
    "user32.dll",
    "userenv.dll",
    "usp10.dll",
    "uuid.dll",
    "uxtheme.dll",
    "version.dll",
    "winhttp.dll",
    "wininet.dll",
    "winmm.dll",
    "wldap32.dll",
    "ws2_32.dll",
    "xinput1_4.dll",
}


def checked_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"unsafe path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.name != value:
        raise ValueError(f"unsafe path: {value!r}")
    if path.suffix.casefold() != ".dll":
        raise ValueError(f"not a DLL path: {value}")
    return value


def indexed_records(records, kind):
    if not isinstance(records, list):
        raise ValueError(f"{kind} files must be a list")
    indexed = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"invalid {kind} file record")
        path = checked_path(record.get("path"))
        key = path.casefold()
        if key in indexed:
            raise ValueError(f"duplicate path: {path}")
        indexed[key] = record
    return indexed


def is_system_dll(name):
    name = name.casefold()
    return (
        name in SYSTEM_DLLS
        or name.startswith("api-ms-win-")
        or name.startswith("ext-ms-win-")
    )


def verify(manifest, inspection, directory):
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    if not isinstance(inspection, dict):
        raise ValueError("inspection must be an object")
    if manifest.get("schema") != 1:
        raise ValueError("manifest schema must be 1")
    if inspection.get("schema") != 1:
        raise ValueError("inspection schema must be 1")
    if manifest.get("target") != {"os": "windows", "arch": "x86_64"}:
        raise ValueError("target must be windows/x86_64")
    libmpv = manifest.get("libmpv")
    if not isinstance(libmpv, dict):
        raise ValueError("manifest libmpv must be an object")
    if libmpv.get("path") != "libmpv-2.dll":
        raise ValueError("libmpv path must be libmpv-2.dll")
    api_version = libmpv.get("api_version")
    if (
        not isinstance(api_version, int)
        or isinstance(api_version, bool)
        or not 0 <= api_version <= 0xFFFFFFFF
    ):
        raise ValueError("manifest libmpv api_version must be an integer")
    inspected_api_version = inspection.get("libmpv_api_version")
    if inspected_api_version != api_version:
        raise ValueError("libmpv API version mismatch")
    if api_version >> 16 != 2:
        raise ValueError("measured libmpv API major must be 2")
    if libmpv.get("api_major") != 2:
        raise ValueError("libmpv API major must be 2")

    files = indexed_records(manifest.get("files"), "manifest")
    inspected = indexed_records(inspection.get("files"), "inspection")
    actual = {}
    for path in directory.rglob("*"):
        if not path.is_file() or path.suffix.casefold() != ".dll":
            continue
        relative = path.relative_to(directory).as_posix()
        key = relative.casefold()
        if key in actual:
            raise ValueError(f"duplicate physical DLL path: {relative}")
        actual[key] = path

    missing = files.keys() - actual.keys()
    extra = actual.keys() - files.keys()
    if missing:
        raise ValueError(f"missing DLLs: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"extra DLLs: {', '.join(sorted(extra))}")

    missing = files.keys() - inspected.keys()
    extra = inspected.keys() - files.keys()
    if missing:
        raise ValueError(f"missing PE inspection: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"extra PE inspection: {', '.join(sorted(extra))}")

    for key, record in files.items():
        path = actual[key]
        content = path.read_bytes()
        if record.get("size") != len(content):
            raise ValueError(f"{record['path']}: size mismatch")
        if record.get("sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError(f"{record['path']}: SHA-256 mismatch")

    for key, record in inspected.items():
        path = record["path"]
        if record.get("machine") != "pei-x86-64":
            raise ValueError(f"{path}: wrong PE machine")
        exports = record.get("exports")
        imports = record.get("imports")
        if not isinstance(exports, list) or not all(isinstance(x, str) for x in exports):
            raise ValueError(f"{path}: invalid exports")
        if not isinstance(imports, list) or not all(isinstance(x, str) for x in imports):
            raise ValueError(f"{path}: invalid imports")
        if key == "libmpv-2.dll":
            missing_exports = REQUIRED_EXPORTS - set(exports)
            if missing_exports:
                raise ValueError(
                    f"{path}: missing exports: {', '.join(sorted(missing_exports))}"
                )
        for imported in imports:
            if imported.casefold() not in files and not is_system_dll(imported):
                raise ValueError(f"undeclared non-system import: {imported}")

    return len(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--inspection", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        inspection = json.loads(args.inspection.read_text(encoding="utf-8"))
        count = verify(manifest, inspection, args.directory)
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"verified {count} DLLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
