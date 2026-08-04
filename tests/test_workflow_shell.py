import json
from pathlib import Path
import subprocess
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/gate0.yml"
STEP = "      - name: Package and verify recursive runtime closure"
ARCHIVE_PREFETCH_STEP = "Prefetch verified upstream archives"
NV_HEADERS_STEP = "Check out exact nv-codec-headers source"


class WorkflowShellTests(unittest.TestCase):
    def test_new_repository_pull_request_can_trigger_gate0(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".on", str(WORKFLOW)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        triggers = json.loads(result.stdout)
        self.assertIn("pull_request", triggers)
        self.assertIn("workflow_dispatch", triggers)

    def test_runtime_probe_pipeline_cannot_mask_wine_failure(self):
        lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
        step = lines.index(STEP)
        run = lines.index("        run: |", step)
        first_command = next(line[10:] for line in lines[run + 1 :] if line.strip())

        result = subprocess.run(
            ["bash", "-c", f"{first_command}\nfalse | true"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(
            result.returncode,
            0,
            "the packaging step can mask a failed command at the start of a pipeline",
        )

    def test_archive_prefetch_populates_upstream_wget_cache(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs.gate0.steps", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(result.stdout)
        matching_steps = [
            step for step in steps if step.get("name") == ARCHIVE_PREFETCH_STEP
        ]
        self.assertEqual(len(matching_steps), 1, "missing verified archive prefetch")
        step = matching_steps[0]
        self.assertEqual(step["working-directory"], "upstream")
        names = [step.get("name") for step in steps]
        self.assertLess(
            names.index(ARCHIVE_PREFETCH_STEP),
            names.index("Build upstream dependency set"),
        )
        script = step["run"]
        self.assertEqual(script.splitlines()[0], "set -euo pipefail")
        contracts = (
            "prefetch_archive() {",
            "curl --fail --show-error --silent --location",
            "--retry 5 --retry-all-errors --connect-timeout 20",
            '--output "$task_archive"',
            'test "$(wc -c < "$task_archive")" -eq "$task_size"',
            "task_sha256",
            "sha256sum --check --strict",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                self.assertIn(contract, script)
        archives = (
            (
                "libiconv-1.18.tar.gz",
                5822590,
                "3b08f5f4f9b4eb82f151a7040bfd6fe6c6fb922efe4b1659c66ea933276965e8",
                "https://ftp.gnu.org/gnu/libiconv/libiconv-1.18.tar.gz",
            ),
            (
                "zlib-1.3.1.tar.gz",
                1512791,
                "9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23",
                "https://zlib.net/fossils/zlib-1.3.1.tar.gz",
            ),
            (
                "AMF-headers-v1.5.0.tar.gz",
                82755,
                "d569647fa26f289affe81a206259fa92f819d06db1e80cc334559953e82a3f01",
                "https://github.com/GPUOpen-LibrariesAndSDKs/AMF/releases/download/v1.5.0/AMF-headers-v1.5.0.tar.gz",
            ),
            (
                "freetype-2.14.1.tar.xz",
                2664948,
                "32427e8c471ac095853212a37aef816c60b42052d4d9e48230bab3bdf2936ccc",
                "https://download-mirror.savannah.gnu.org/releases/freetype/freetype-2.14.1.tar.xz",
            ),
            (
                "fribidi-1.0.16.tar.xz",
                1098260,
                "1b1cde5b235d40479e91be2f0e88a309e3214c8ab470ec8a2744d82a5a9ea05c",
                "https://github.com/fribidi/fribidi/releases/download/v1.0.16/fribidi-1.0.16.tar.xz",
            ),
            (
                "harfbuzz-12.2.0.tar.xz",
                18221900,
                "ecb603aa426a8b24665718667bda64a84c1504db7454ee4cadbd362eea64e545",
                "https://github.com/harfbuzz/harfbuzz/releases/download/12.2.0/harfbuzz-12.2.0.tar.xz",
            ),
        )
        for archive in archives:
            with self.subTest(archive=archive[0]):
                self.assertIn(" ".join(map(str, archive)), script)

    def test_nv_codec_headers_checkout_is_pinned_before_upstream_build(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs.gate0.steps", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(result.stdout)
        matching_steps = [step for step in steps if step.get("name") == NV_HEADERS_STEP]
        self.assertEqual(len(matching_steps), 1, "missing pinned nv-codec-headers checkout")
        step = matching_steps[0]
        self.assertEqual(
            step,
            {
                "name": NV_HEADERS_STEP,
                "uses": "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
                "with": {
                    "repository": "FFmpeg/nv-codec-headers",
                    "ref": "876af32a202d0de83bd1d36fe74ee0f7fcf86b0d",
                    "path": "upstream/nv-codec-headers",
                    "persist-credentials": False,
                },
            },
        )
        names = [step.get("name") for step in steps]
        self.assertLess(
            names.index(NV_HEADERS_STEP), names.index("Build upstream dependency set")
        )


if __name__ == "__main__":
    unittest.main()
