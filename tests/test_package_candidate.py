import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts" / "package_candidate.py"
VERIFIER = ROOT / "scripts" / "verify_runtime.py"
API_VERSION = (2 << 16) | 5


class PackageCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.search = self.root / "search"
        self.search.mkdir()
        (self.search / "libmpv-2.dll").write_bytes(b"libmpv")
        (self.search / "avcodec-62.dll").write_bytes(b"avcodec")
        self.objdump = self.root / "objdump"
        self.objdump.write_text(
            f"""#!{sys.executable}
import pathlib
import sys

mode, path = sys.argv[1:]
name = pathlib.Path(path).name
if mode == '-f':
    print(f'{{name}}: file format pei-x86-64')
elif mode == '-p' and name == 'libmpv-2.dll':
    print('''
\tDLL Name: KERNEL32.dll
\tDLL Name: UxTheme.dll
\tDLL Name: SHCore.DLL
\tDLL Name: avcodec-62.dll
[   0] mpv_client_api_version
[   1] mpv_command
[   2] mpv_create
[   3] mpv_initialize
[   4] mpv_terminate_destroy
[   5] mpv_wait_event
''')
elif mode == '-p':
    print('\tDLL Name: KERNEL32.dll')
else:
    raise SystemExit(2)
""",
            encoding="utf-8",
        )
        self.objdump.chmod(0o755)
        self.output = self.root / "candidate"

    def tearDown(self):
        self.tempdir.cleanup()

    def run_packager(self, extra_search_roots=(), api_version=API_VERSION):
        search_args = ["--search-root", str(self.search)]
        for root in extra_search_roots:
            search_args.extend(["--search-root", str(root)])
        return subprocess.run(
            [
                sys.executable,
                str(PACKAGER),
                "--libmpv",
                str(self.search / "libmpv-2.dll"),
                *search_args,
                "--output",
                str(self.output),
                "--objdump",
                str(self.objdump),
                "--api-version",
                str(api_version),
            ],
            capture_output=True,
            text=True,
        )

    def test_packages_recursive_non_system_dependency_closure(self):
        result = self.run_packager()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            sorted(path.name for path in self.output.glob("*.dll")),
            ["avcodec-62.dll", "libmpv-2.dll"],
        )
        manifest = json.loads(
            (self.output / "runtime-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [record["path"] for record in manifest["files"]],
            ["avcodec-62.dll", "libmpv-2.dll"],
        )
        self.assertEqual(manifest["libmpv"]["api_version"], API_VERSION)
        inspection = json.loads(
            (self.output / "pe-inspection.json").read_text(encoding="utf-8")
        )
        self.assertEqual(inspection["libmpv_api_version"], API_VERSION)
        libmpv = next(
            record for record in inspection["files"] if record["path"] == "libmpv-2.dll"
        )
        self.assertIn("UxTheme.dll", libmpv["imports"])
        self.assertIn("SHCore.DLL", libmpv["imports"])

        verified = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--manifest",
                str(self.output / "runtime-manifest.json"),
                "--inspection",
                str(self.output / "pe-inspection.json"),
                "--directory",
                str(self.output),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_rejects_duplicate_available_dll_basename(self):
        other = self.root / "other"
        other.mkdir()
        (other / "AVCODEC-62.DLL").write_bytes(b"different avcodec")

        result = self.run_packager([other])

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("duplicate available DLL name", result.stderr)

    def test_rejects_missing_search_root(self):
        missing = self.root / "missing"

        result = self.run_packager([missing])

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"search root is not a directory: {missing}", result.stderr)

    def test_rejects_invalid_measured_api_version(self):
        result = self.run_packager(api_version="not-a-version")

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("invalid libmpv API version", result.stderr)

    def test_rejects_measured_api_major_other_than_two(self):
        result = self.run_packager(api_version=(1 << 16) | 5)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("measured libmpv API major must be 2", result.stderr)


if __name__ == "__main__":
    unittest.main()
