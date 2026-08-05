from pathlib import Path
import subprocess
import tempfile
import unittest


VERIFIER = Path(__file__).resolve().parents[1] / "scripts/verify_source_snapshot.sh"


class SourceSnapshotTests(unittest.TestCase):
    def test_rejects_empty_subtree_then_accepts_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("recipe", "upstream", "toolchain-source", "cargo"):
                (root / name).mkdir()
            for name in ("recipe", "upstream", "toolchain-source"):
                (root / name / "source.txt").write_text(name, encoding="utf-8")

            rejected = subprocess.run(
                ["bash", str(VERIFIER), str(root)],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("source snapshot subtree is empty: cargo", rejected.stderr)

            (root / "cargo/source.txt").write_text("cargo", encoding="utf-8")
            accepted = subprocess.run(
                ["bash", str(VERIFIER), str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)


if __name__ == "__main__":
    unittest.main()
