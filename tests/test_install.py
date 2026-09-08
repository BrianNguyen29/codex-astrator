from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
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

    def test_preview_is_read_only(self) -> None:
        result = self.run_cli("--scope", "project", "--target", str(self.target))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertIn("PREVIEW", result.stdout)

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
        self.assertEqual(manifest["version"], 2)
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

        def fail_commit_and_restore(path: Path, data: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls in (4, 5):
                raise installer.InstallerError("injected commit/restore failure")
            original_write(path, data)

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
        self.assertFalse(manifest_path.exists())

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

    def test_real_repository_installs_exactly_six_agent_profiles(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(INSTALL), "install", "--source", str(ROOT),
                "--scope", "project", "--target", str(self.target), "--apply",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = sorted(path.name for path in (self.target / ".codex" / "agents").glob("*.toml"))
        self.assertEqual(installed, [
            "complex_worker.toml", "explorer.toml", "researcher.toml",
            "reviewer.toml", "tester.toml", "worker.toml",
        ])


if __name__ == "__main__":
    unittest.main()
