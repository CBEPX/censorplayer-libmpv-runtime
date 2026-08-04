import json
from pathlib import Path
import subprocess
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/gate0.yml"
STEP = "      - name: Package and verify recursive runtime closure"
PREFETCH_STEP = "Prefetch verified libiconv source"


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

    def test_libiconv_prefetch_populates_upstream_wget_cache(self):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".jobs.gate0.steps", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        steps = json.loads(result.stdout)
        step = next(step for step in steps if step.get("name") == PREFETCH_STEP)
        self.assertEqual(step["working-directory"], "upstream")
        names = [step.get("name") for step in steps]
        self.assertLess(
            names.index(PREFETCH_STEP), names.index("Build upstream dependency set")
        )
        script = step["run"]
        self.assertEqual(script.splitlines()[0], "set -euo pipefail")
        contracts = (
            "task_archive=libiconv-1.18.tar.gz",
            "curl --fail --show-error --silent --location",
            "--retry 5 --retry-all-errors --connect-timeout 20",
            '--output "$task_archive"',
            "https://ftp.gnu.org/gnu/libiconv/libiconv-1.18.tar.gz",
            'test "$(wc -c < "$task_archive")" -eq 5822590',
            "3b08f5f4f9b4eb82f151a7040bfd6fe6c6fb922efe4b1659c66ea933276965e8",
            "sha256sum --check --strict",
        )
        for contract in contracts:
            with self.subTest(contract=contract):
                self.assertIn(contract, script)


if __name__ == "__main__":
    unittest.main()
