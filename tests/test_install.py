from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "install.py"
DOCTOR = ROOT / "scripts" / "doctor.py"


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codex astrator ")
        self.base = Path(self.temp.name)
        self.source = self.base / "payload source"
        self.target = self.base / "project with spaces"
        (self.source / "profiles").mkdir(parents=True)
        (self.source / "payload" / "agents").mkdir(parents=True)
        (self.source / "payload" / "skills" / "astra-orchestrator").mkdir(parents=True)
        (self.source / "payload" / "instructions").mkdir(parents=True)
        self.target.mkdir()
        (self.source / "profiles" / "reference.toml").write_text(
            "# owned profile\n[features]\nmulti_agent = true\n[agents]\ndefaults = \"safe\"\n",
            encoding="utf-8",
        )
        (self.source / "payload" / "agents" / "default.toml").write_text(
            'name = "default"\n', encoding="utf-8"
        )
        (self.source / "payload" / "skills" / "astra-orchestrator" / "SKILL.md").write_text(
            "# Astra orchestrator\n", encoding="utf-8"
        )
        (self.source / "payload" / "instructions" / "orchestration.md").write_text(
            "Use the community profile safely.\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(INSTALL), *args]
        if "uninstall" not in args and "--uninstall" not in args:
            command += ["--source", str(self.source)]
        return subprocess.run(command, text=True, capture_output=True, env=env)

    def install(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli("--scope", "project", "--target", str(self.target), "--apply", *extra)

    def snapshot_files(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file()
        }

    def test_preview_is_read_only(self) -> None:
        result = self.run_cli("--scope", "project", "--target", str(self.target))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertIn("PREVIEW", result.stdout)
        self.assertIn(".codex/.astrator-backups/.gitignore", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows-specific fail-closed contract")
    def test_windows_existing_file_is_refused_but_fresh_lifecycle_works(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_bytes(b"user_owned = true\n")
        before = self.snapshot_files()

        refused = self.install()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Windows ACL-preserving backup and restore is unavailable", refused.stderr)
        after_refusal = self.snapshot_files()
        self.assertEqual(after_refusal.pop(".codex/.astrator.lock"), b"codex-astrator installer lock\n")
        self.assertEqual(after_refusal, before)

        config.unlink()
        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        manifest_before = (self.target / ".codex" / "astrator-manifest.json").read_bytes()
        repeated = self.install()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(
            (self.target / ".codex" / "astrator-manifest.json").read_bytes(),
            manifest_before,
        )
        removed = self.run_cli(
            "uninstall", "--scope", "project", "--target", str(self.target), "--apply"
        )
        self.assertEqual(removed.returncode, 0, removed.stderr)

    def test_noop_apply_repairs_only_missing_backup_ignore(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        manifest = self.target / ".codex" / "astrator-manifest.json"
        ignore = self.target / ".codex" / ".astrator-backups" / ".gitignore"
        manifest_before = manifest.read_bytes()
        managed_before = {
            path: (path.read_bytes(), path.stat().st_ino)
            for path in self.target.rglob("*")
            if path.is_file() and path not in {ignore, manifest}
        }
        ignore.unlink()

        repaired = self.install()
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(ignore.read_bytes(), b"*\n")
        self.assertEqual(manifest.read_bytes(), manifest_before)
        self.assertEqual(
            {path: (path.read_bytes(), path.stat().st_ino) for path in managed_before},
            managed_before,
        )

    def test_uninstall_failure_rolls_back_only_completed_mutations(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        self.assertEqual(self.install().returncode, 0)
        manifest_path, manifest, manifest_snapshot = installer._load_manifest(self.target, "project")
        self.assertIsNotNone(manifest)
        destinations = [self.target.joinpath(*entry["path"].split("/")) for entry in manifest["entries"]]
        untouched = destinations[1]
        untouched_before = (untouched.read_bytes(), untouched.stat().st_ino)
        original_remove = installer._remove_file
        original_write = installer._write_bytes
        removals = 0
        rollback_writes: list[Path] = []

        def fail_second_removal(path: Path) -> None:
            nonlocal removals
            if path in destinations:
                removals += 1
                if removals == 2:
                    raise installer.InstallerError("injected uninstall deletion failure")
            original_remove(path)

        def record_write(path: Path, data: bytes, **kwargs) -> None:
            rollback_writes.append(path)
            original_write(path, data, **kwargs)

        installer._remove_file = fail_second_removal
        installer._write_bytes = record_write
        try:
            with self.assertRaisesRegex(installer.InstallerError, "changes rolled back"):
                installer._uninstall(
                    self.target, "project", manifest_path, manifest, manifest_snapshot,
                    apply=True,
                )
        finally:
            installer._remove_file = original_remove
            installer._write_bytes = original_write
        self.assertEqual(rollback_writes, [destinations[0]])
        self.assertEqual((untouched.read_bytes(), untouched.stat().st_ino), untouched_before)
        self.assertTrue(manifest_path.exists())

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable on Windows")
    def test_existing_modes_survive_apply_update_and_uninstall(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_bytes(b"# original config\n")
        config.chmod(0o700)
        agents = self.target / "AGENTS.md"
        agents.write_bytes(b"# original instructions\n")
        agents.chmod(0o600)

        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(agents.stat().st_mode), 0o600)
        manifest = json.loads(
            (self.target / ".codex" / "astrator-manifest.json").read_text(encoding="utf-8")
        )
        modes = {entry["path"]: entry["original_mode"] for entry in manifest["entries"]}
        self.assertEqual(modes[".codex/config.toml"], 0o700)
        self.assertEqual(modes["AGENTS.md"], 0o600)

        (self.source / "payload" / "instructions" / "orchestration.md").write_text(
            "Updated instructions.\n", encoding="utf-8"
        )
        updated = self.install("--replace-existing")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(agents.stat().st_mode), 0o600)

        removed = self.run_cli(
            "uninstall", "--scope", "project", "--target", str(self.target), "--apply"
        )
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(agents.stat().st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable on Windows")
    def test_backup_storage_is_private_under_broad_umask(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_bytes(b"private = true\n")
        previous_umask = os.umask(0)
        try:
            installed = self.install()
        finally:
            os.umask(previous_umask)
        self.assertEqual(installed.returncode, 0, installed.stderr)

        backup_root = self.target / ".codex" / ".astrator-backups"
        for directory in [backup_root, *(path for path in backup_root.iterdir() if path.is_dir())]:
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((backup_root / ".gitignore").stat().st_mode), 0o600)
        backups = list(backup_root.rglob("*.bak"))
        self.assertTrue(backups)
        for backup in backups:
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable on Windows")
    def test_chmod_after_plan_is_detected_and_rollback_restores_mode(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_bytes(b"# original\n")
        config.chmod(0o640)
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        self.assertFalse(conflicts)
        config.chmod(0o600)
        with self.assertRaisesRegex(installer.InstallerError, "stale plan"):
            installer._apply_plan(
                self.target, "project", plan, old_manifest, manifest_path,
                managed_agent_paths, snapshot,
            )
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)

        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        installer._FAIL_AFTER = 3
        try:
            with self.assertRaisesRegex(installer.InstallerError, "changes rolled back"):
                installer._apply_plan(
                    self.target, "project", plan, old_manifest, manifest_path,
                    managed_agent_paths, snapshot,
                )
        finally:
            installer._FAIL_AFTER = None
        self.assertEqual(config.read_bytes(), b"# original\n")
        self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_late_edit_after_backup_is_not_overwritten_by_rollback(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_bytes(b"# inspected original\n")
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        self.assertFalse(conflicts)
        original_copy_backup = installer._copy_backup
        intervening = b"# editor changed this after backup\n"

        def copy_then_edit(source: Path, destination: Path) -> None:
            original_copy_backup(source, destination)
            if source == config:
                config.write_bytes(intervening)

        installer._copy_backup = copy_then_edit
        try:
            with self.assertRaisesRegex(installer.InstallerError, "stale plan"):
                installer._apply_plan(
                    self.target, "project", plan, old_manifest, manifest_path,
                    managed_agent_paths, snapshot,
                )
        finally:
            installer._copy_backup = original_copy_backup
        self.assertEqual(config.read_bytes(), intervening)
        self.assertFalse(manifest_path.exists())
        self.assertEqual(list((self.target / ".codex" / ".astrator-backups").rglob("*.bak")), [])

    def test_recovery_transaction_without_manifest_blocks_every_install_mode(self) -> None:
        backup_root = self.target / ".codex" / ".astrator-backups"
        payload = backup_root / ".txn-interrupted" / "recovery.bak"
        payload.parent.mkdir(parents=True)
        (backup_root / ".gitignore").write_bytes(b"*\n")
        payload.write_bytes(b"retained recovery bytes")
        (self.target / ".codex" / ".astrator.lock").write_bytes(
            b"codex-astrator installer lock\n"
        )
        before = self.snapshot_files()

        for extra in ((), ("--apply",), ("--apply", "--replace-existing")):
            with self.subTest(extra=extra):
                result = self.run_cli(
                    "--scope", "project", "--target", str(self.target), *extra
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("recovery-required", result.stderr)
                self.assertEqual(self.snapshot_files(), before)

    def test_unreferenced_recovery_payload_blocks_update_and_uninstall(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        backup_root = self.target / ".codex" / ".astrator-backups"

        for directory in (".txn-interrupted", "orphan-backup"):
            with self.subTest(directory=directory):
                payload = backup_root / directory / "recovery.bak"
                payload.parent.mkdir(parents=True)
                payload.write_bytes(b"retained recovery bytes")
                before = self.snapshot_files()
                commands = (
                    ("--scope", "project", "--target", str(self.target)),
                    (
                        "--scope", "project", "--target", str(self.target),
                        "--apply", "--replace-existing",
                    ),
                    ("uninstall", "--scope", "project", "--target", str(self.target)),
                    (
                        "uninstall", "--scope", "project", "--target", str(self.target),
                        "--apply",
                    ),
                )
                for command in commands:
                    result = self.run_cli(*command)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("recovery-required", result.stderr)
                    self.assertEqual(self.snapshot_files(), before)
                payload.unlink()
                payload.parent.rmdir()

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_referenced_backup_and_benign_marker_allow_repeat_apply(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_bytes(b"# original config\n")
        self.assertEqual(self.install().returncode, 0)
        manifest_path = self.target / ".codex" / "astrator-manifest.json"
        before = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(any(entry.get("backup") for entry in before["entries"]))

        preview = self.run_cli("--scope", "project", "--target", str(self.target))
        self.assertEqual(preview.returncode, 0, preview.stderr)
        repeated = self.install()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        after = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(after["entries"], before["entries"])

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_unmanaged_orchestration_warning_preserves_legacy_content(self) -> None:
        agents = self.target / "AGENTS.md"
        legacy = "# Existing policy\nAlways delegate implementation to sub-agents.\n"
        agents.write_text(legacy, encoding="utf-8")

        preview = self.run_cli("--scope", "project", "--target", str(self.target))
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("WARNING: existing unmanaged orchestration-like instructions", preview.stdout)
        self.assertIn("does not claim the combined policy is coherent", preview.stdout)
        self.assertEqual(agents.read_text(encoding="utf-8"), legacy)

        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertTrue(agents.read_text(encoding="utf-8").startswith(legacy))

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    @unittest.skipUnless(shutil.which("git"), "git is required for ignore integration test")
    def test_sensitive_project_backup_is_ignored_by_git(self) -> None:
        subprocess.run(["git", "init", "--quiet", str(self.target)], check=True)
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        secret = b'service_token = "synthetic-secret-do-not-stage"\n'
        config.write_bytes(secret)

        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertNotIn("synthetic-secret-do-not-stage", installed.stdout + installed.stderr)
        manifest = json.loads(
            (self.target / ".codex" / "astrator-manifest.json").read_text(encoding="utf-8")
        )
        config_entry = next(entry for entry in manifest["entries"] if entry["path"] == ".codex/config.toml")
        backup = self.target.joinpath(*config_entry["backup"].split("/"))
        self.assertEqual(backup.read_bytes(), secret)
        ignored = subprocess.run(
            ["git", "-C", str(self.target), "check-ignore", "--quiet", "--", config_entry["backup"]]
        )
        self.assertEqual(ignored.returncode, 0)
        status = subprocess.run(
            ["git", "-C", str(self.target), "status", "--short"],
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertNotIn(".astrator-backups", status.stdout)

    @unittest.skipUnless(shutil.which("git"), "git is required for tracked-backup safety test")
    def test_tracked_preexisting_backup_is_refused(self) -> None:
        subprocess.run(["git", "init", "--quiet", str(self.target)], check=True)
        tracked = self.target / ".codex" / ".astrator-backups" / "old.bak"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("previous secret\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.target), "add", "--force", "--", ".codex/.astrator-backups/old.bak"],
            check=True,
        )

        refused = self.install()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Git already tracks content", refused.stderr)
        self.assertEqual(tracked.read_text(encoding="utf-8"), "previous secret\n")
        self.assertFalse((tracked.parent / ".gitignore").exists())

    def test_unsafe_backup_ignore_is_refused_without_overwrite(self) -> None:
        ignore = self.target / ".codex" / ".astrator-backups" / ".gitignore"
        ignore.parent.mkdir(parents=True)
        ignore.write_text("!*.bak\n", encoding="utf-8")

        refused = self.install()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("required protective '*' rule", refused.stderr)
        self.assertEqual(ignore.read_text(encoding="utf-8"), "!*.bak\n")

    def test_backup_directory_symlink_is_refused(self) -> None:
        outside = self.base / "outside backups"
        outside.mkdir()
        state = self.target / ".codex"
        state.mkdir()
        try:
            (state / ".astrator-backups").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")

        refused = self.install()
        self.assertEqual(refused.returncode, 2)
        self.assertRegex(refused.stderr, "symlink|path escapes target")
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX permission modes are unavailable on Windows")
    def test_permissive_existing_backup_directory_is_not_silently_hardened(self) -> None:
        backup_root = self.target / ".codex" / ".astrator-backups"
        backup_root.mkdir(parents=True)
        backup_root.chmod(0o755)
        (backup_root / ".gitignore").write_bytes(b"*\n")

        refused = self.install()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("permissions are too broad", refused.stderr)
        self.assertEqual(stat.S_IMODE(backup_root.stat().st_mode), 0o755)
        self.assertFalse((self.target / ".codex" / "astrator-manifest.json").exists())

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_real_profile_existing_final_table_and_uninstall(self) -> None:
        import tomllib
        (self.source / "profiles" / "reference.toml").write_bytes(
            (ROOT / "profiles" / "reference.toml").read_bytes()
        )
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        original = b"# user settings\n[features]\nother = true\n"
        config.write_bytes(original)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertTrue(parsed["features"]["multi_agent"])
        self.assertTrue(parsed["features"]["other"])
        self.assertNotIn("multi_agent", parsed["agents"])
        self.assertEqual(parsed["model_reasoning_effort"], "low")
        self.assertEqual(parsed["model_context_window"], 400000)
        self.assertEqual(parsed["model_auto_compact_token_limit"], 250000)
        self.assertEqual(parsed["model_auto_compact_token_limit_scope"], "total")
        self.assertEqual(self.install().returncode, 0)
        snapshot = {p: p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        preview = self.run_cli("uninstall", "--scope", "project", "--target", str(self.target))
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(snapshot, {p: p.read_bytes() for p in self.target.rglob("*") if p.is_file()})
        applied = self.run_cli("uninstall", "--scope", "project", "--target", str(self.target), "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(config.read_bytes(), original)

    def test_install_repeat_is_idempotent(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        files = {p.relative_to(self.target).as_posix(): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        second = self.install()
        self.assertEqual(second.returncode, 0, second.stderr)
        again = {p.relative_to(self.target).as_posix(): p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(files, again)
        self.assertIn("0 file change(s)", second.stdout)

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_clean_update_preserves_first_original_for_uninstall(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        original_config = b"# original config\nunrelated = 7\n"
        config.write_bytes(original_config)
        agents = self.target / "AGENTS.md"
        original_agents = b"# original project instructions\n"
        agents.write_bytes(original_agents)
        self.assertEqual(self.install().returncode, 0)

        (self.source / "profiles" / "reference.toml").write_text(
            "# updated profile\n[features]\nmulti_agent = true\nextra = false\n"
            "[agents]\ndefaults = \"safe\"\n",
            encoding="utf-8",
        )
        (self.source / "payload" / "instructions" / "orchestration.md").write_text(
            "Updated community profile safely.\n", encoding="utf-8"
        )
        (self.source / "payload" / "agents" / "default.toml").write_text(
            'name = "default"\ndescription = "updated"\n', encoding="utf-8"
        )
        updated = self.install("--replace-existing")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        manifest = json.loads(
            (self.target / ".codex" / "astrator-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], 3)
        self.assertIn(b"extra = false", config.read_bytes())

        removed = self.run_cli("uninstall", "--scope", "project", "--target", str(self.target), "--apply")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(config.read_bytes(), original_config)
        self.assertEqual(agents.read_bytes(), original_agents)

    def test_identical_preexisting_agent_survives_repeat_and_uninstall(self) -> None:
        source_agent = self.source / "payload" / "agents" / "default.toml"
        installed_agent = self.target / ".codex" / "agents" / "default.toml"
        installed_agent.parent.mkdir(parents=True)
        original = source_agent.read_bytes()
        installed_agent.write_bytes(original)

        first = self.install()
        self.assertEqual(first.returncode, 0, first.stderr)
        manifest = json.loads(
            (self.target / ".codex" / "astrator-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["managed_agent_paths"], [".codex/agents/default.toml"])
        self.assertNotIn(".codex/agents/default.toml", {entry["path"] for entry in manifest["entries"]})

        repeated = self.install()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        removed = self.run_cli("uninstall", "--scope", "project", "--target", str(self.target), "--apply")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(installed_agent.read_bytes(), original)

    def test_managed_role_set_change_requires_uninstall_first(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        installed = self.target / ".codex" / "agents" / "default.toml"
        before = installed.read_bytes()
        (self.source / "payload" / "agents" / "replacement.toml").write_text(
            'name = "replacement"\n', encoding="utf-8"
        )
        refused = self.install("--replace-existing")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("uninstall the previous version first", refused.stderr)
        self.assertEqual(installed.read_bytes(), before)
        self.assertFalse((self.target / ".codex" / "agents" / "replacement.toml").exists())

    def test_missing_table_with_multiple_owned_keys_is_valid_toml(self) -> None:
        (self.source / "profiles" / "reference.toml").write_text(
            "[features]\nmulti_agent = true\nother_feature = false\n", encoding="utf-8"
        )
        self.assertEqual(self.install().returncode, 0)
        config = (self.target / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertEqual(config.count("[features]"), 1)
        import tomllib
        self.assertEqual(tomllib.loads(config)["features"], {"multi_agent": True, "other_feature": False})

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_existing_config_comments_and_unrelated_values_survive(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        original = "# keep this\nother = 7\n[features]\n# feature note\nmulti_agent = false # user value\n"
        config.write_text(original, encoding="utf-8")
        preview = self.run_cli("--scope", "project", "--target", str(self.target))
        self.assertEqual(preview.returncode, 3)
        self.assertEqual(config.read_text(encoding="utf-8"), original)
        self.assertEqual(self.install().returncode, 3)
        replaced = self.install("--replace-existing")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        result = config.read_text(encoding="utf-8")
        self.assertIn("# keep this", result)
        self.assertIn("other = 7", result)
        self.assertIn("multi_agent = true # user value", result)

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_quoted_table_headers_preserve_paths_comments_and_values(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        original = (
            "# keep this\n"
            "[projects.'D:\\WorkSpace\\EEG\\eeg.ds004752'] # literal path\n"
            "keep_literal = 1\n"
            "[projects.\"D:\\\\WorkSpace\\\\EEG\\\\eeg.ds004753\"] # basic path\n"
            "keep_basic = 2\n"
        )
        config.write_text(original, encoding="utf-8")

        installed = self.install()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        result = config.read_text(encoding="utf-8")
        self.assertTrue(result.startswith(original))
        import tomllib
        parsed = tomllib.loads(result)
        self.assertEqual(
            parsed["projects"][r"D:\WorkSpace\EEG\eeg.ds004752"]["keep_literal"], 1
        )
        self.assertEqual(
            parsed["projects"][r"D:\WorkSpace\EEG\eeg.ds004753"]["keep_basic"], 2
        )
        self.assertTrue(parsed["features"]["multi_agent"])

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_quoted_equivalent_managed_table_is_replaced_in_place(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        original = '["features"]\n# feature note\nmulti_agent = false # user value\n'
        config.write_text(original, encoding="utf-8")

        preview = self.run_cli("--scope", "project", "--target", str(self.target))
        self.assertEqual(preview.returncode, 3)
        replaced = self.install("--replace-existing")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        result = config.read_text(encoding="utf-8")
        self.assertIn('["features"]', result)
        self.assertIn("# feature note", result)
        self.assertIn("multi_agent = true # user value", result)

    def test_malformed_quoted_table_is_refused_before_mutation(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        original = '[projects."D:\\WorkSpace\\EEG"]\nkeep = true\n'
        config.write_text(original, encoding="utf-8")

        refused = self.install()
        self.assertEqual(refused.returncode, 2)
        self.assertIn("existing config is invalid TOML", refused.stderr)
        self.assertEqual(config.read_text(encoding="utf-8"), original)
        self.assertFalse((self.target / "AGENTS.md").exists())

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_collision_requires_explicit_replace(self) -> None:
        skill = self.target / ".agents" / "skills" / "astra-orchestrator" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("user skill\n", encoding="utf-8")
        blocked = self.install()
        self.assertEqual(blocked.returncode, 3)
        self.assertEqual(skill.read_text(encoding="utf-8"), "user skill\n")
        allowed = self.install("--replace-existing")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_modified_uninstall_refuses_without_touching_manifest(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        skill = self.target / ".agents" / "skills" / "astra-orchestrator" / "SKILL.md"
        skill.write_text("edited by user\n", encoding="utf-8")
        preview = self.run_cli("uninstall", "--scope", "project", "--target", str(self.target))
        self.assertEqual(preview.returncode, 2)
        self.assertEqual(skill.read_text(encoding="utf-8"), "edited by user\n")
        refused = self.run_cli("uninstall", "--scope", "project", "--target", str(self.target), "--apply")
        self.assertEqual(refused.returncode, 2)
        self.assertTrue((self.target / ".codex" / "astrator-manifest.json").exists())
        self.assertEqual(skill.read_text(encoding="utf-8"), "edited by user\n")

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_apply_rolls_back_injected_failure(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text("# original\n", encoding="utf-8")
        env = os.environ.copy()
        env["CODEX_ASTRATOR_TEST_FAIL_AFTER"] = "2"
        result = self.run_cli("--scope", "project", "--target", str(self.target), "--apply", env=env)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(config.read_text(encoding="utf-8"), "# original\n")
        self.assertFalse((self.target / ".codex" / "astrator-manifest.json").exists())
        self.assertFalse((self.target / "AGENTS.md").exists())
        self.assertEqual(
            (self.target / ".codex" / ".astrator-backups" / ".gitignore").read_bytes(),
            b"*\n",
        )

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    @unittest.skipUnless(shutil.which("git"), "git is required for rollback privacy test")
    def test_rollback_retains_ignore_when_backup_cleanup_is_denied(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        subprocess.run(["git", "init", "--quiet", str(self.target)], check=True)
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('token = "synthetic-private-value"\n', encoding="utf-8")
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        self.assertFalse(conflicts)
        original_unlink = installer.Path.unlink

        def deny_backup_unlink(path: Path, *args, **kwargs) -> None:
            if path.suffix == ".bak":
                raise PermissionError("injected backup deletion denial")
            original_unlink(path, *args, **kwargs)

        installer.Path.unlink = deny_backup_unlink
        installer._FAIL_AFTER = 3
        try:
            with self.assertRaisesRegex(installer.InstallerError, "changes rolled back"):
                installer._apply_plan(
                    self.target, "project", plan, old_manifest, manifest_path,
                    managed_agent_paths, snapshot,
                )
        finally:
            installer.Path.unlink = original_unlink
            installer._FAIL_AFTER = None

        retained = list((self.target / ".codex" / ".astrator-backups").rglob("*.bak"))
        self.assertTrue(retained, "deletion-denied recovery bytes must remain protected")
        self.assertEqual(
            (self.target / ".codex" / ".astrator-backups" / ".gitignore").read_bytes(),
            b"*\n",
        )
        for backup in retained:
            relative = backup.relative_to(self.target).as_posix()
            ignored = subprocess.run(
                ["git", "-C", str(self.target), "check-ignore", "--quiet", "--", relative]
            )
            self.assertEqual(ignored.returncode, 0)

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_restore_failure_retains_recovery_backups(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text("# original\n", encoding="utf-8")
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        self.assertFalse(conflicts)
        original_write = installer._write_bytes
        calls = 0

        def fail_commit_and_restore(path: Path, data: bytes, **kwargs) -> None:
            nonlocal calls
            calls += 1
            if calls in (4, 5):
                raise installer.InstallerError("injected commit/restore failure")
            original_write(path, data, **kwargs)

        installer._write_bytes = fail_commit_and_restore
        try:
            with self.assertRaises(installer.InstallerError) as raised:
                installer._apply_plan(
                    self.target, "project", plan, old_manifest, manifest_path, managed_agent_paths, snapshot
                )
        finally:
            installer._write_bytes = original_write
        self.assertIn("rollback is incomplete", str(raised.exception))
        recovery = list((self.target / ".codex" / ".astrator-backups").glob(".txn-*"))
        self.assertTrue(recovery, "transaction backups must remain for manual recovery")
        self.assertEqual(
            (self.target / ".codex" / ".astrator-backups" / ".gitignore").read_bytes(),
            b"*\n",
        )
        self.assertFalse(manifest_path.exists())
        status = subprocess.run(
            [
                sys.executable, str(INSTALL), "status", "--scope", "project",
                "--target", str(self.target),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(status.returncode, 2)
        self.assertIn("state=recovery-required", status.stdout)
        self.assertNotIn("# original", status.stdout + status.stderr)

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_update_rejects_tracked_drift_even_with_replace(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text("# original config\n", encoding="utf-8")
        agents = self.target / "AGENTS.md"
        agents.write_text("# original instructions\n", encoding="utf-8")
        self.assertEqual(self.install().returncode, 0)

        config.write_text("# user config edit\n", encoding="utf-8")
        agents.write_text("# user instruction edit\n", encoding="utf-8")
        (self.source / "profiles" / "reference.toml").write_text(
            "# changed payload\n[features]\nmulti_agent = false\n[agents]\ndefaults = \"new\"\n",
            encoding="utf-8",
        )
        (self.source / "payload" / "instructions" / "orchestration.md").write_text(
            "Changed payload instructions.\n", encoding="utf-8"
        )
        before_manifest = (self.target / ".codex" / "astrator-manifest.json").read_bytes()
        refused = self.install("--replace-existing")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("drift detected", refused.stderr)
        self.assertEqual(config.read_text(encoding="utf-8"), "# user config edit\n")
        self.assertEqual(agents.read_text(encoding="utf-8"), "# user instruction edit\n")
        self.assertEqual((self.target / ".codex" / "astrator-manifest.json").read_bytes(), before_manifest)

    def test_update_rejects_drift_for_files_originally_absent(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        config = self.target / ".codex" / "config.toml"
        agents = self.target / "AGENTS.md"
        config.write_text("# user config edit after install\n", encoding="utf-8")
        agents.write_text("# user instructions after install\n", encoding="utf-8")
        (self.source / "payload" / "instructions" / "orchestration.md").write_text(
            "Changed payload instructions.\n", encoding="utf-8"
        )
        refused = self.install("--replace-existing")
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(config.read_text(encoding="utf-8"), "# user config edit after install\n")
        self.assertEqual(agents.read_text(encoding="utf-8"), "# user instructions after install\n")

    def test_update_rejects_missing_tracked_file(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        missing = self.target / ".agents" / "skills" / "astra-orchestrator" / "SKILL.md"
        missing.unlink()
        manifest = self.target / ".codex" / "astrator-manifest.json"
        before_manifest = manifest.read_bytes()
        refused = self.install("--replace-existing")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("required path does not exist", refused.stderr)
        self.assertFalse(missing.exists())
        self.assertEqual(manifest.read_bytes(), before_manifest)

    def test_apply_rejects_destination_change_after_unchanged_plan(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        self.assertEqual(self.install().returncode, 0)
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        self.assertEqual(plan, [])
        self.assertEqual(conflicts, [])
        config = self.target / ".codex" / "config.toml"
        edited = b"# intervening user edit\n"
        config.write_bytes(edited)
        with self.assertRaisesRegex(installer.InstallerError, "stale plan"):
            installer._apply_plan(
                self.target, "project", plan, old_manifest, manifest_path,
                managed_agent_paths, snapshot,
            )
        self.assertEqual(config.read_bytes(), edited)

    def test_apply_rejects_unowned_preexisting_destination_change(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        agent = self.target / ".codex" / "agents" / "default.toml"
        agent.parent.mkdir(parents=True)
        agent.write_bytes((self.source / "payload" / "agents" / "default.toml").read_bytes())
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        edited = b'user_owned = "intervening"\n'
        agent.write_bytes(edited)
        with self.assertRaisesRegex(installer.InstallerError, "stale plan"):
            installer._apply_plan(
                self.target, "project", plan, old_manifest, manifest_path,
                managed_agent_paths, snapshot,
            )
        self.assertEqual(agent.read_bytes(), edited)
        self.assertFalse(manifest_path.exists())

    def test_apply_rejects_intervening_manifest_write(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        self.assertEqual(self.install().returncode, 0)
        (self.source / "payload" / "instructions" / "orchestration.md").write_text(
            "Changed payload instructions.\n", encoding="utf-8"
        )
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        intervening = manifest_path.read_bytes() + b" \n"
        manifest_path.write_bytes(intervening)
        before_files = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*") if path.is_file()
        }
        with self.assertRaisesRegex(installer.InstallerError, "stale plan"):
            installer._apply_plan(
                self.target, "project", plan, old_manifest, manifest_path,
                managed_agent_paths, snapshot,
            )
        after_files = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*") if path.is_file()
        }
        self.assertEqual(after_files, before_files)
        self.assertEqual(manifest_path.read_bytes(), intervening)

    def test_direct_mutation_functions_recheck_recovery_guard(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        self.assertEqual(self.install().returncode, 0)
        plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = installer._build_plan(
            self.target, "project", self.source, False
        )
        self.assertEqual(conflicts, [])
        loaded_path, manifest, manifest_snapshot = installer._load_manifest(self.target, "project")
        self.assertIsNotNone(manifest)
        payload = self.target / ".codex" / ".astrator-backups" / ".txn-late" / "recovery.bak"
        payload.parent.mkdir()
        payload.write_bytes(b"late recovery bytes")
        before = self.snapshot_files()

        with self.assertRaisesRegex(installer.InstallerError, "recovery-required"):
            installer._apply_plan(
                self.target, "project", plan, old_manifest, manifest_path,
                managed_agent_paths, snapshot,
            )
        with self.assertRaisesRegex(installer.InstallerError, "recovery-required"):
            installer._uninstall(
                self.target, "project", loaded_path, manifest, manifest_snapshot,
                apply=True,
            )
        self.assertEqual(self.snapshot_files(), before)

    def test_install_uses_same_manifest_bytes_for_parse_and_snapshot(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        self.assertEqual(self.install().returncode, 0)
        manifest_path = self.target / ".codex" / "astrator-manifest.json"
        before_destinations = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file() and path != manifest_path
        }
        original_source_files = installer._source_files
        intervening = b""
        mutated = False

        def mutate_manifest_during_source_inspection(root: Path):
            nonlocal intervening, mutated
            result = original_source_files(root)
            if not mutated:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["version"] = 1
                intervening = json.dumps(manifest).encode("utf-8")
                manifest_path.write_bytes(intervening)
                mutated = True
            return result

        installer._source_files = mutate_manifest_during_source_inspection
        try:
            plan, conflicts, old_manifest, loaded_path, managed_agent_paths, snapshot = installer._build_plan(
                self.target, "project", self.source, False
            )
        finally:
            installer._source_files = original_source_files
        with self.assertRaisesRegex(installer.InstallerError, "stale plan"):
            installer._apply_plan(
                self.target, "project", plan, old_manifest, loaded_path,
                managed_agent_paths, snapshot,
            )
        after_destinations = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file() and path != manifest_path
        }
        self.assertEqual(after_destinations, before_destinations)
        self.assertEqual(manifest_path.read_bytes(), intervening)

    def test_uninstall_uses_same_manifest_bytes_for_parse_and_snapshot(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import install as installer

        self.assertEqual(self.install().returncode, 0)
        manifest_path, manifest, manifest_snapshot = installer._load_manifest(self.target, "project")
        self.assertIsNotNone(manifest)
        before_destinations = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file() and path != manifest_path
        }
        legacy = dict(manifest)
        legacy["version"] = 1
        intervening = json.dumps(legacy).encode("utf-8")
        original_read = installer._read_bytes
        mutated = False

        def mutate_manifest_during_destination_inspection(path: Path) -> bytes:
            nonlocal mutated
            if path != manifest_path and not mutated:
                manifest_path.write_bytes(intervening)
                mutated = True
            return original_read(path)

        installer._read_bytes = mutate_manifest_during_destination_inspection
        try:
            with self.assertRaisesRegex(installer.InstallerError, "stale plan"):
                installer._uninstall(
                    self.target, "project", manifest_path, manifest, manifest_snapshot,
                    apply=True,
                )
        finally:
            installer._read_bytes = original_read
        after_destinations = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*")
            if path.is_file() and path != manifest_path
        }
        self.assertEqual(after_destinations, before_destinations)
        self.assertEqual(manifest_path.read_bytes(), intervening)

    def test_legacy_manifest_blocks_install_and_uninstall_without_mutation(self) -> None:
        self.assertEqual(self.install().returncode, 0)
        manifest_path = self.target / ".codex" / "astrator-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        before = {
            path.relative_to(self.target).as_posix(): path.read_bytes()
            for path in self.target.rglob("*") if path.is_file()
        }
        for args in (
            ("--scope", "project", "--target", str(self.target)),
            ("uninstall", "--scope", "project", "--target", str(self.target)),
            ("uninstall", "--scope", "project", "--target", str(self.target), "--apply"),
        ):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertIn("legacy installer manifest safety version", result.stderr)
            self.assertIn("Manually reconcile", result.stderr)
            after = {
                path.relative_to(self.target).as_posix(): path.read_bytes()
                for path in self.target.rglob("*") if path.is_file()
            }
            self.assertEqual(after, before)

    def test_malicious_manifest_path_is_refused(self) -> None:
        state = self.target / ".codex"
        state.mkdir()
        outside = self.base / "outside.txt"
        outside.write_text("do not touch", encoding="utf-8")
        manifest = {
            "version": 1,
            "scope": "project",
            "entries": [{
                "path": "../../outside.txt",
                "installed_sha256": hashlib.sha256(b"do not touch").hexdigest(),
                "original_exists": False,
                "original_sha256": None,
                "backup": None,
            }],
        }
        (state / "astrator-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_cli("uninstall", "--scope", "project", "--target", str(self.target))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(outside.exists())

    def test_symlink_ancestor_is_refused(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        try:
            (self.target / ".agents").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        result = self.install()
        self.assertEqual(result.returncode, 2)
        self.assertFalse((outside / "skills").exists())

    def test_source_above_boundary_symlink_is_allowed(self) -> None:
        alias = self.base / "system alias"
        try:
            alias.symlink_to(self.base, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        result = subprocess.run(
            [
                sys.executable, str(INSTALL), "install", "--source", str(alias / self.source.name),
                "--scope", "project", "--target", str(self.target), "--apply",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_boundary_and_inner_payload_symlinks_are_refused(self) -> None:
        outside = self.base / "outside source file"
        outside.write_text('name = "default"\n', encoding="utf-8")
        role = self.source / "payload" / "agents" / "default.toml"
        role.unlink()
        try:
            role.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        result = self.install()
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)

        role.unlink()
        role.write_text('name = "default"\n', encoding="utf-8")
        source_alias = self.base / "source boundary alias"
        source_alias.symlink_to(self.source, target_is_directory=True)
        boundary_result = subprocess.run(
            [
                sys.executable, str(INSTALL), "install", "--source", str(source_alias),
                "--scope", "project", "--target", str(self.target), "--apply",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(boundary_result.returncode, 2)
        self.assertIn("symlink", boundary_result.stderr)

    def test_doctor_is_static_payload_check(self) -> None:
        result = subprocess.run(
            [sys.executable, str(DOCTOR), "--source", str(ROOT)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("runtime compatibility is not evaluated", result.stdout)

    def test_repository_payload_has_exact_supported_roles(self) -> None:
        import tomllib
        expected = {
            "explorer": ("gpt-5.6-luna", "low", "read-only"),
            "worker": ("gpt-5.6-luna", "xhigh", "workspace-write"),
            "complex_worker": ("gpt-5.6-sol", "medium", "workspace-write"),
            "tester": ("gpt-5.6-luna", "medium", "workspace-write"),
            "researcher": ("gpt-5.6-luna", "medium", "read-only"),
            "reviewer": ("gpt-6-astra", "low", "read-only"),
        }
        actual = {}
        for path in (ROOT / "payload" / "agents").glob("*.toml"):
            role = tomllib.loads(path.read_text(encoding="utf-8"))
            actual[role["name"]] = (
                role["model"], role["model_reasoning_effort"], role["sandbox_mode"]
            )
            self.assertEqual(path.name, f'{role["name"]}.toml')
        self.assertEqual(actual, expected)

    @unittest.skipIf(os.name == "nt", "Windows safely refuses installs that require user-file backups")
    def test_real_repository_installs_exactly_six_agent_profiles(self) -> None:
        config = self.target / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text(
            "# keep this setting\nunrelated = 7\n"
            "[features.context_management]\nunrelated_nested = true\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable, str(INSTALL), "install", "--source", str(ROOT),
                "--scope", "project", "--target", str(self.target), "--apply",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        import tomllib
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(parsed["model_context_window"], 400000)
        self.assertEqual(parsed["model_auto_compact_token_limit"], 250000)
        self.assertEqual(parsed["model_auto_compact_token_limit_scope"], "total")
        self.assertEqual(parsed["unrelated"], 7)
        self.assertTrue(parsed["features"]["context_management"]["experimental_mode"])
        self.assertTrue(parsed["features"]["context_management"]["unrelated_nested"])
        installed = sorted(path.name for path in (self.target / ".codex" / "agents").glob("*.toml"))
        self.assertEqual(installed, [
            "complex_worker.toml", "explorer.toml", "researcher.toml",
            "reviewer.toml", "tester.toml", "worker.toml",
        ])


if __name__ == "__main__":
    unittest.main()
