import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


from scripts.overlay_runtime import overlay


OVERLAY = Path(__file__).resolve().parents[1] / "scripts/overlay_runtime.py"


def write_candidate(root, files):
    candidate = root / "candidate"
    candidate.mkdir()
    records = []
    inspections = []
    for name, content in files.items():
        (candidate / name).write_bytes(content)
        records.append(
            {
                "path": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        inspections.append(
            {
                "path": name,
                "machine": "pei-x86-64",
                "exports": (
                    [
                        "mpv_client_api_version",
                        "mpv_command",
                        "mpv_create",
                        "mpv_initialize",
                        "mpv_terminate_destroy",
                        "mpv_wait_event",
                    ]
                    if name.casefold() == "libmpv-2.dll"
                    else []
                ),
                "imports": [],
            }
        )
    manifest = {
        "schema": 1,
        "target": {"os": "windows", "arch": "x86_64"},
        "libmpv": {"path": "libmpv-2.dll", "api_version": 131077, "api_major": 2},
        "files": records,
    }
    inspection = {"schema": 1, "libmpv_api_version": 131077, "files": inspections}
    return candidate, manifest, inspection


class OverlayRuntimeTests(unittest.TestCase):
    def test_replaces_libmpv_adds_dependencies_and_preserves_player_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root,
                {"libmpv-2.dll": b"new mpv", "libgcc_s_seh-1.dll": b"runtime"},
            )
            target = root / "portable"
            target.mkdir()
            (target / "LIBMPV-2.DLL").write_bytes(b"stock mpv")
            (target / "mpvnet.exe").write_bytes(b"player")
            nested = target / "portable_config/extensions/example"
            nested.mkdir(parents=True)
            (nested / "libgcc_s_seh-1.dll").write_bytes(b"extension-owned")

            count = overlay(manifest, inspection, candidate, target)

            self.assertEqual(count, 2)
            self.assertEqual((target / "LIBMPV-2.DLL").read_bytes(), b"new mpv")
            self.assertEqual(
                [
                    path.name
                    for path in target.iterdir()
                    if path.name.casefold() == "libmpv-2.dll"
                ],
                ["LIBMPV-2.DLL"],
            )
            self.assertEqual((target / "libgcc_s_seh-1.dll").read_bytes(), b"runtime")
            self.assertEqual((target / "mpvnet.exe").read_bytes(), b"player")
            self.assertEqual(
                (nested / "libgcc_s_seh-1.dll").read_bytes(), b"extension-owned"
            )

    def test_rejects_dependency_collision_before_replacing_libmpv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root,
                {"libmpv-2.dll": b"new mpv", "libssp-0.dll": b"candidate"},
            )
            target = root / "portable"
            target.mkdir()
            (target / "libmpv-2.dll").write_bytes(b"stock mpv")
            (target / "LIBSSP-0.DLL").write_bytes(b"player-owned")

            with self.assertRaisesRegex(ValueError, "target DLL collision: LIBSSP-0.DLL"):
                overlay(manifest, inspection, candidate, target)

            self.assertEqual((target / "libmpv-2.dll").read_bytes(), b"stock mpv")
            self.assertEqual((target / "LIBSSP-0.DLL").read_bytes(), b"player-owned")

    def test_verification_rejects_invalid_candidate_before_replacing_libmpv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root,
                {"libmpv-2.dll": b"new mpv", "libssp-0.dll": b"runtime"},
            )
            (candidate / "libssp-0.dll").write_bytes(b"tampered")
            target = root / "portable"
            target.mkdir()
            (target / "libmpv-2.dll").write_bytes(b"stock mpv")

            with self.assertRaisesRegex(ValueError, "libssp-0.dll: size mismatch"):
                overlay(manifest, inspection, candidate, target)

            self.assertEqual((target / "libmpv-2.dll").read_bytes(), b"stock mpv")
            self.assertFalse((target / "libssp-0.dll").exists())

    def test_rejects_target_without_stock_libmpv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root, {"libmpv-2.dll": b"new mpv"}
            )
            target = root / "portable"
            target.mkdir()

            with self.assertRaisesRegex(ValueError, "target has no stock libmpv-2.dll"):
                overlay(manifest, inspection, candidate, target)

    def test_rejects_missing_target_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root, {"libmpv-2.dll": b"new mpv"}
            )

            with self.assertRaisesRegex(ValueError, "target is not a directory"):
                overlay(manifest, inspection, candidate, root / "missing")

    def test_cli_overlays_verified_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root, {"libmpv-2.dll": b"new mpv"}
            )
            manifest_path = candidate / "runtime-manifest.json"
            inspection_path = candidate / "pe-inspection.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            inspection_path.write_text(json.dumps(inspection), encoding="utf-8")
            target = root / "portable"
            target.mkdir()
            (target / "libmpv-2.dll").write_bytes(b"stock mpv")

            result = subprocess.run(
                [
                    sys.executable,
                    str(OVERLAY),
                    "--manifest",
                    str(manifest_path),
                    "--inspection",
                    str(inspection_path),
                    "--candidate",
                    str(candidate),
                    "--target",
                    str(target),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("overlaid 1 verified DLLs", result.stdout)
            self.assertEqual((target / "libmpv-2.dll").read_bytes(), b"new mpv")

    def test_detects_copy_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root, {"libmpv-2.dll": b"new mpv"}
            )
            target = root / "portable"
            target.mkdir()
            (target / "libmpv-2.dll").write_bytes(b"stock mpv")

            with patch(
                "scripts.overlay_runtime.shutil.copy2",
                side_effect=lambda _source, destination: Path(destination).write_bytes(
                    b"corrupt"
                ),
            ):
                with self.assertRaisesRegex(ValueError, "target copy mismatch"):
                    overlay(manifest, inspection, candidate, target)

    def test_cli_reports_validation_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate, manifest, inspection = write_candidate(
                root, {"libmpv-2.dll": b"new mpv"}
            )
            manifest["target"]["arch"] = "x86"
            manifest_path = candidate / "runtime-manifest.json"
            inspection_path = candidate / "pe-inspection.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            inspection_path.write_text(json.dumps(inspection), encoding="utf-8")
            target = root / "portable"
            target.mkdir()
            (target / "libmpv-2.dll").write_bytes(b"stock mpv")

            result = subprocess.run(
                [
                    sys.executable,
                    str(OVERLAY),
                    "--manifest",
                    str(manifest_path),
                    "--inspection",
                    str(inspection_path),
                    "--candidate",
                    str(candidate),
                    "--target",
                    str(target),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("error: target must be windows/x86_64", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
