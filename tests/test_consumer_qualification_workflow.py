import json
from pathlib import Path
import re
import subprocess
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/gate0.yml"
CONSUMER_COMMIT = "6d2586d32d9aa733f5e9c51fdfee28abe54bc1e4"


class ConsumerQualificationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".", str(WORKFLOW)],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.workflow = json.loads(result.stdout)
        cls.jobs = cls.workflow["jobs"]

    def step(self, steps, name):
        matches = [step for step in steps if step.get("name") == name]
        self.assertEqual(len(matches), 1, f"expected one workflow step named {name!r}")
        return matches[0]

    def test_qualification_uses_gate0_candidate_and_exact_consumer(self):
        job = self.jobs["qualify-consumer"]
        needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
        self.assertIn("gate0", needs)
        self.assertEqual(job["runs-on"], "windows-2025")

        steps = job["steps"]
        download = self.step(steps, "Download exact Gate 0 candidate")
        self.assertEqual(download["with"]["name"], "gate0-windows-x64-${{ github.sha }}")

        checkout = self.step(steps, "Check out exact CensorPlayer consumer")
        self.assertEqual(checkout["with"]["repository"], "CBEPX/mpvnet-censor-extension")
        self.assertEqual(checkout["with"]["ref"], CONSUMER_COMMIT)
        self.assertEqual(checkout["with"]["path"], "consumer")
        self.assertIs(checkout["with"]["persist-credentials"], False)

        setup = self.step(steps, "Set up pinned .NET SDK")
        self.assertEqual(setup["with"]["dotnet-version"], "10.0.302")

        build = self.step(steps, "Build and test exact CensorPlayer consumer")
        self.assertEqual(build["shell"], "bash")
        self.assertEqual(build["run"].splitlines()[0], "set -euo pipefail")

        stage = self.step(steps, "Stage stock portable CensorPlayer")["run"]
        self.assertIn("git rev-parse HEAD", stage)
        self.assertIn("-Commit $ConsumerCommit", stage)

    def test_all_actions_are_full_sha_pinned(self):
        pin = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")
        for job in self.jobs.values():
            for step in job.get("steps", []):
                if "uses" in step:
                    self.assertRegex(step["uses"], pin)

    def test_expensive_run_is_cancelled_only_by_a_new_run_on_the_same_ref(self):
        self.assertEqual(
            self.workflow["concurrency"],
            {
                "group": "${{ github.workflow }}-${{ github.ref }}",
                "cancel-in-progress": True,
            },
        )

    def test_source_subtrees_are_required_before_artifact_upload(self):
        steps = self.jobs["gate0"]["steps"]
        snapshot = self.step(steps, "Snapshot all corresponding source")["run"]
        self.assertEqual(snapshot.splitlines()[0], "set -euo pipefail")
        verifier = 'bash scripts/verify_source_snapshot.sh "$task_snapshot"'
        self.assertIn(verifier, snapshot)
        self.assertLess(snapshot.index(verifier), snapshot.index("tar -czf"))

    def test_qualification_verifies_overlay_before_consumer_smokes(self):
        steps = self.jobs["qualify-consumer"]["steps"]
        source = steps.index(self.step(steps, "Verify bundled recipe snapshot"))
        overlay = steps.index(self.step(steps, "Verify and overlay candidate runtime"))
        identity = steps.index(self.step(steps, "Verify loaded libmpv identity"))
        loader = steps.index(self.step(steps, "Verify staged extension loader contract"))
        audio = steps.index(self.step(steps, "Verify CensorPlayer audio filters"))
        runtime = steps.index(self.step(steps, "Verify CensorPlayer runtime behavior"))

        self.assertLess(source, overlay)
        self.assertLess(overlay, identity)
        self.assertLess(identity, loader)
        self.assertLess(loader, audio)
        self.assertLess(audio, runtime)
        self.assertIn("$env:QUALIFIED_MPVNET", steps[audio]["run"])
        self.assertIn("$env:QUALIFIED_MPVNET", steps[runtime]["run"])


if __name__ == "__main__":
    unittest.main()
