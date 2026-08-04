import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from scripts.verify_runtime import verify


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_runtime.py"
REQUIRED_EXPORTS = [
    "mpv_client_api_version",
    "mpv_command",
    "mpv_create",
    "mpv_initialize",
    "mpv_terminate_destroy",
    "mpv_wait_event",
]
API_VERSION = (2 << 16) | 5


class VerifyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name) / "candidate"
        self.directory.mkdir()
        self.write_dll("libmpv-2.dll", b"libmpv")
        self.write_dll("avcodec-62.dll", b"avcodec")
        self.manifest = {
            "schema": 1,
            "target": {"os": "windows", "arch": "x86_64"},
            "libmpv": {
                "path": "libmpv-2.dll",
                "api_version": API_VERSION,
                "api_major": 2,
            },
            "files": [
                self.file_record("libmpv-2.dll"),
                self.file_record("avcodec-62.dll"),
            ],
        }
        self.inspection = {
            "schema": 1,
            "libmpv_api_version": API_VERSION,
            "files": [
                {
                    "path": "libmpv-2.dll",
                    "machine": "pei-x86-64",
                    "exports": list(REQUIRED_EXPORTS),
                    "imports": ["KERNEL32.dll", "avcodec-62.dll"],
                },
                {
                    "path": "avcodec-62.dll",
                    "machine": "pei-x86-64",
                    "exports": [],
                    "imports": ["KERNEL32.dll"],
                },
            ],
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def write_dll(self, path, content):
        target = self.directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def file_record(self, path):
        content = (self.directory / path).read_bytes()
        return {
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def run_verifier(self):
        manifest_path = self.directory / "runtime-manifest.json"
        inspection_path = Path(self.tempdir.name) / "pe-inspection.json"
        manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        inspection_path.write_text(json.dumps(self.inspection), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--manifest",
                str(manifest_path),
                "--inspection",
                str(inspection_path),
                "--directory",
                str(self.directory),
            ],
            capture_output=True,
            text=True,
        )

    def assert_rejected(self, message):
        result = self.run_verifier()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)

    def test_accepts_matching_windows_x64_runtime(self):
        result = self.run_verifier()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified 2 DLLs", result.stdout)

    def test_rejects_wrong_target_architecture(self):
        self.manifest["target"]["arch"] = "x86"

        self.assert_rejected("target must be windows/x86_64")

    def test_rejects_wrong_pe_architecture(self):
        self.inspection["files"][0]["machine"] = "pei-i386"

        self.assert_rejected("libmpv-2.dll: wrong PE machine")

    def test_rejects_missing_required_libmpv_export(self):
        self.inspection["files"][0]["exports"].remove("mpv_initialize")

        self.assert_rejected("libmpv-2.dll: missing exports: mpv_initialize")

    def test_rejects_api_major_other_than_two(self):
        self.manifest["libmpv"]["api_major"] = 1

        self.assert_rejected("libmpv API major must be 2")

    def test_rejects_measured_api_major_other_than_two(self):
        api_version = (1 << 16) | 99
        self.manifest["libmpv"]["api_version"] = api_version
        self.inspection["libmpv_api_version"] = api_version

        self.assert_rejected("measured libmpv API major must be 2")

    def test_rejects_mismatched_api_version_evidence(self):
        self.inspection["libmpv_api_version"] += 1

        self.assert_rejected("libmpv API version mismatch")

    def test_rejects_missing_api_version_evidence(self):
        del self.manifest["libmpv"]["api_version"]

        self.assert_rejected("manifest libmpv api_version must be an integer")

    def test_rejects_wrong_manifest_schema(self):
        self.manifest["schema"] = 2

        self.assert_rejected("manifest schema must be 1")

    def test_rejects_wrong_inspection_schema(self):
        self.inspection["schema"] = 2

        self.assert_rejected("inspection schema must be 1")

    def test_rejects_path_traversal(self):
        self.manifest["files"][0]["path"] = "../libmpv-2.dll"

        self.assert_rejected("unsafe path")

    def test_rejects_windows_path_traversal(self):
        self.manifest["files"][0]["path"] = "..\\libmpv-2.dll"

        self.assert_rejected("unsafe path")

    def test_rejects_case_insensitive_duplicate_paths(self):
        duplicate = dict(self.manifest["files"][1])
        duplicate["path"] = "AVCODEC-62.DLL"
        self.manifest["files"].append(duplicate)

        self.assert_rejected("duplicate path")

    def test_rejects_case_insensitive_duplicate_physical_dlls(self):
        def physical_path(name, content):
            path = Mock()
            path.is_file.return_value = True
            path.suffix = ".dll"
            path.relative_to.return_value = PurePosixPath(name)
            path.read_bytes.return_value = content
            return path

        directory = Mock()
        directory.rglob.return_value = [
            physical_path("libmpv-2.dll", b"libmpv"),
            physical_path("avcodec-62.dll", b"avcodec"),
            physical_path("AVCODEC-62.DLL", b"avcodec"),
        ]

        with self.assertRaisesRegex(ValueError, "duplicate physical DLL path"):
            verify(self.manifest, self.inspection, directory)

    def test_rejects_non_object_manifest_without_traceback(self):
        self.manifest = []

        self.assert_rejected("manifest must be an object")

    def test_rejects_non_object_inspection_without_traceback(self):
        self.inspection = []

        self.assert_rejected("inspection must be an object")

    def test_rejects_non_object_libmpv_without_traceback(self):
        self.manifest["libmpv"] = []

        self.assert_rejected("manifest libmpv must be an object")

    def test_rejects_missing_dll(self):
        (self.directory / "avcodec-62.dll").unlink()

        self.assert_rejected("missing DLLs: avcodec-62.dll")

    def test_rejects_extra_dll(self):
        self.write_dll("stray.dll", b"stray")

        self.assert_rejected("extra DLLs: stray.dll")

    def test_rejects_size_mismatch(self):
        self.manifest["files"][0]["size"] += 1

        self.assert_rejected("libmpv-2.dll: size mismatch")

    def test_rejects_hash_mismatch(self):
        self.manifest["files"][0]["sha256"] = "0" * 64

        self.assert_rejected("libmpv-2.dll: SHA-256 mismatch")

    def test_rejects_undeclared_non_system_import(self):
        self.inspection["files"][0]["imports"].append("missing-runtime.dll")

        self.assert_rejected("undeclared non-system import: missing-runtime.dll")

    def test_rejects_missing_pe_inspection_record(self):
        self.inspection["files"].pop()

        self.assert_rejected("missing PE inspection: avcodec-62.dll")

    def test_rejects_extra_pe_inspection_record(self):
        self.inspection["files"].append(
            {
                "path": "stray.dll",
                "machine": "pei-x86-64",
                "exports": [],
                "imports": [],
            }
        )

        self.assert_rejected("extra PE inspection: stray.dll")


if __name__ == "__main__":
    unittest.main()
