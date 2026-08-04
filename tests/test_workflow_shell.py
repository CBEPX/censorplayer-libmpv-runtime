from pathlib import Path
import subprocess
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/gate0.yml"
STEP = "      - name: Package and verify recursive runtime closure"


class WorkflowShellTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
