from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "install.py"


class StateCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="astrator state ")
        self.target = Path(self.temp.name) / "target"
        self.target.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, command: str, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(INSTALL), command, "--scope", "project", "--target", str(self.target), *extra],
            text=True,
            capture_output=True,
        )

    def install(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(INSTALL), "install", "--source", str(ROOT),
                "--scope", "project", "--target", str(self.target), "--apply",
            ],
            text=True,
            capture_output=True,
        )

    def test_status_absent_and_verify_absent_are_read_only(self) -> None:
        before = list(self.target.iterdir())
        status = self.run_cli("status")
        verify = self.run_cli("verify")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("state=absent", status.stdout)
        self.assertEqual(verify.returncode, 2)
        self.assertIn("state=absent", verify.stdout)
        self.assertEqual(list(self.target.iterdir()), before)

    def test_healthy_status_reports_aggregate_integrity_only(self) -> None:
        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        status = self.run_cli("status")
        verify = self.run_cli("verify")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertRegex(
            status.stdout,
            r"^STATUS: state=healthy scope=project manifest=current managed=\d+/\d+ backups=\d+/\d+ roles=6/6\n$",
        )
        manifest = json.loads((self.target / ".codex" / "astrator-manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["entries"]:
            self.assertNotIn(entry["installed_sha256"], status.stdout)
            self.assertNotIn(entry.get("backup") or "impossible-backup-name", status.stdout)

    def test_missing_and_drift_are_unhealthy_without_echoing_contents(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        role = self.target / ".codex" / "agents" / "worker.toml"
        secret = "synthetic-secret-that-must-not-be-logged"
        role.write_text(secret, encoding="utf-8")
        drifted = self.run_cli("verify")
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("state=drifted", drifted.stdout)
        self.assertNotIn(secret, drifted.stdout + drifted.stderr)
        role.unlink()
        missing = self.run_cli("status")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("state=drifted", missing.stdout)

    def test_legacy_and_corrupt_backup_are_reported_without_mutation(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text("unrelated = 1\n", encoding="utf-8")
        self.assertEqual(self.install().returncode, 0)
        manifest_path = self.target / ".codex" / "astrator-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        before = manifest_path.read_bytes()
        legacy = self.run_cli("status")
        self.assertEqual(legacy.returncode, 2)
        self.assertIn("state=legacy", legacy.stdout)
        self.assertEqual(manifest_path.read_bytes(), before)

        manifest["version"] = 2
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        backup_rel = next(entry["backup"] for entry in manifest["entries"] if entry.get("backup"))
        self.target.joinpath(*backup_rel.split("/")).write_text("corrupt", encoding="utf-8")
        corrupt = self.run_cli("verify")
        self.assertEqual(corrupt.returncode, 2)
        self.assertIn("state=invalid", corrupt.stdout)

    def test_identical_preexisting_role_is_valid_but_survives_uninstall(self) -> None:
        role = self.target / ".codex" / "agents" / "worker.toml"
        role.parent.mkdir(parents=True)
        original = (ROOT / "payload" / "agents" / "worker.toml").read_bytes()
        role.write_bytes(original)
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.run_cli("verify").returncode, 0)
        removed = self.run_cli("uninstall", "--apply")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(role.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
