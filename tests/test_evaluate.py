from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="astrator eval ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "cases"

    def prepare(self, task=None):
        evaluate.prepare(self.root, [task] if task else None, 2)
        return self.root / (task or "onefilebug") / "repeat-01"

    def test_default_prepares_four_tasks_twice_without_overwrite(self):
        result = evaluate.prepare(self.root)
        self.assertEqual(result["task_count"], 8)
        before = (self.root / "manifest.json").read_bytes()
        with self.assertRaises(evaluate.EvaluationError):
            evaluate.prepare(self.root)
        self.assertEqual((self.root / "manifest.json").read_bytes(), before)

    def test_structural_is_not_behavioral_and_default_does_not_execute(self):
        workspace = self.prepare("onefilebug")
        (workspace / "src/calculator.py").write_text("raise RuntimeError('not executed')\n", encoding="utf-8")
        result = evaluate.check(workspace)
        self.assertEqual(result["verification"]["behavioral_outcome"], "unavailable")

    def test_comments_cannot_pass_behavior_and_equivalent_code_can(self):
        workspace = self.prepare("onefilebug")
        source = workspace / "src/calculator.py"
        source.write_text("# return left + right\ndef add(left, right):\n    return 0\n", encoding="utf-8")
        self.assertEqual(evaluate.check(workspace, execute=True)["outcome"], "failed")
        source.write_text("def add(a, b): return 5\n", encoding="utf-8")
        self.assertEqual(evaluate.check(workspace, execute=True)["outcome"], "failed")
        source.write_text("def add(a, b):\n    return sum((a, b))\n", encoding="utf-8")
        self.assertEqual(evaluate.check(workspace, execute=True)["outcome"], "passed")

    def test_all_fixed_behaviors_accept_correct_implementations(self):
        self.prepare()
        for repeat in ("repeat-01", "repeat-02"):
            (self.root / "onefilebug" / repeat / "src/calculator.py").write_text(
                "def add(a, b):\n    return a + b\n", encoding="utf-8")
            workspace = self.root / "multifilefeature" / repeat
            (workspace / "src/slug.py").write_text(
                "def slugify(text):\n    return '-'.join(''.join(c for c in text.lower() if c.isalnum() or c.isspace()).split())\n",
                encoding="utf-8")
            (workspace / "src/report.py").write_text(
                "from .slug import slugify\ndef format_label(title):\n    return f'{title} [{slugify(title)}]'\n", encoding="utf-8")
            (self.root / "statebug" / repeat / "src/state.py").write_text(
                "class Session:\n    def __init__(self): self.state = 'idle'\n    def start(self): self.state = 'running'\n    def stop(self): self.state = 'idle'\n", encoding="utf-8")
            (self.root / "offline-research-review" / repeat / "REVIEW.md").write_text(
                "## Findings\nOffline review: preview-first.\n## Evidence\nSupplied facts only; offline. No browsing.\n", encoding="utf-8")
        result = evaluate.check(self.root, execute=True)
        self.assertEqual(result["outcome"], "passed", result)
        self.assertEqual(result["verification"]["behavioral_outcome"], "passed")

    def test_broken_state_and_timeout_fail(self):
        workspace = self.prepare("statebug")
        self.assertEqual(evaluate.check(workspace, execute=True)["outcome"], "failed")
        (workspace / "src/state.py").write_text(
            "class Session:\n    def __init__(self): self.state = 'idle'\n    def start(self): self.state = 'running'\n    def stop(self): return 'idle'\n", encoding="utf-8")
        self.assertEqual(evaluate.check(workspace, execute=True)["outcome"], "failed")
        (workspace / "src/state.py").write_text("while True: pass\n", encoding="utf-8")
        self.assertEqual(evaluate.check(workspace, execute=True)["outcome"], "failed")

    def test_report_complete_checks_duplicates_and_privacy(self):
        workspace = self.prepare("onefilebug")
        result = evaluate.check(workspace, execute=True)
        report = evaluate.build_report(result, usage={"output_tokens": 20, "reasoning_tokens": 5})
        self.assertEqual(report["execution"]["model"], "unavailable")
        self.assertEqual(report["measurements"]["usage"]["output_tokens"], 20)
        self.assertNotIn(str(workspace), json.dumps(report))
        for mutation in ("missing", "duplicate", "private"):
            bad = copy.deepcopy(result)
            if mutation == "missing":
                bad["tasks"][0]["checks"].pop()
            elif mutation == "duplicate":
                bad["tasks"].append(bad["tasks"][0])
            else:
                bad["prompt"] = "private"
            with self.assertRaises(evaluate.EvaluationError):
                evaluate.build_report(bad)
        result["verification"]["behavioral_outcome"] = "passed"
        self.assertEqual(evaluate.build_report(result)["verification"]["behavioral_outcome"], "failed")
        for number in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(evaluate.EvaluationError):
                evaluate.build_report(result, duration_ms=number)

    def test_traversal_is_rejected(self):
        for path in ("../escape", "C:/escape", "a/../../b", "a\\b"):
            with self.assertRaises(evaluate.EvaluationError):
                evaluate._validate_relative_path(path)

    def test_alias_above_explicit_parent_is_accepted(self):
        explicit_parent = Path(self.temporary.name) / "explicit-parent"
        explicit_parent.mkdir()
        alias = Path(self.temporary.name) / "aliasaboveexplicitparent"
        try:
            alias.symlink_to(Path(self.temporary.name), target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")

        output = alias / explicit_parent.name / "cases"
        prepared = evaluate.prepare(output, ["onefilebug"], repeats=1)
        self.assertEqual(prepared["output"], str(output))
        workspace = output / "onefilebug" / "repeat-01"
        self.assertEqual(evaluate.check(workspace)["outcome"], "failed")

    def test_symlinked_workspace_leaf_and_direct_parent_are_rejected(self):
        self.prepare()
        workspace = self.root / "onefilebug" / "repeat-01"
        workspace_link = Path(self.temporary.name) / "workspaceleaf"
        direct_parent = Path(self.temporary.name) / "direct-parent"
        direct_parent_target = Path(self.temporary.name) / "direct-parent-target"
        direct_parent_target.mkdir()
        try:
            workspace_link.symlink_to(workspace, target_is_directory=True)
            direct_parent.symlink_to(direct_parent_target, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")

        with self.assertRaises(evaluate.EvaluationError):
            evaluate.check(workspace_link)
        with self.assertRaises(evaluate.EvaluationError):
            evaluate._emit({"kind": "test"}, direct_parent / "output.json")

    def test_symlinked_manifest_workspace_is_rejected(self):
        self.prepare()
        manifest_path = self.root / evaluate.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        nested_link = self.root / "onefilebug" / "manifestnested"
        try:
            nested_link.symlink_to(self.root / "onefilebug" / "repeat-01", target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        manifest["tasks"][0]["workspace"] = "onefilebug/manifestnested"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaises(evaluate.EvaluationError):
            evaluate.check(self.root)

    def test_symlinked_source_inside_workspace_is_not_read(self):
        workspace = self.prepare("onefilebug")
        source = workspace / "src/calculator.py"
        outside = Path(self.temporary.name) / "outside.py"
        outside.write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
        try:
            source.unlink()
            source.symlink_to(outside)
        except OSError:
            self.skipTest("symlink creation unavailable")

        self.assertEqual(evaluate.check(workspace)["outcome"], "failed")

    def test_symlinked_output_leaf_is_rejected(self):
        output_target = Path(self.temporary.name) / "output-target"
        output_target.mkdir()
        output = Path(self.temporary.name) / "output.json"
        try:
            output.symlink_to(output_target, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")

        with self.assertRaises(evaluate.EvaluationError):
            evaluate._emit({"kind": "test"}, output)

    def test_cli_exit_and_new_report_output(self):
        workspace = self.prepare("onefilebug")
        output = Path(self.temporary.name) / "check.json"
        command = [sys.executable, str(Path(evaluate.__file__)), "check", "--workspace", str(workspace), "--execute", "--output", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(output.exists())
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)

    def test_relative_workspace_behavior_cli(self):
        workspace = self.prepare("onefilebug")
        (workspace / "src/calculator.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(Path(evaluate.__file__).resolve()), "check", "--workspace", "cases/onefilebug/repeat-01", "--execute"],
            cwd=self.temporary.name, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_cli_rejects_unhashable_workspace_json_without_output(self):
        workspace = self.prepare("onefilebug")
        metadata_path = workspace / evaluate.METADATA_NAME
        manifest_path = self.root / evaluate.MANIFEST_NAME
        check_script = [sys.executable, str(Path(evaluate.__file__).resolve()), "check"]
        for path, command_workspace, field in (
            (metadata_path, workspace, "task_id"),
            (manifest_path, self.root, "task_id"),
        ):
            original = json.loads(path.read_text(encoding="utf-8"))
            for value in ([], {}):
                with self.subTest(path=path.name, value=value):
                    malformed = copy.deepcopy(original)
                    if path == manifest_path:
                        malformed["tasks"][0][field] = value
                    else:
                        malformed[field] = value
                    path.write_text(json.dumps(malformed), encoding="utf-8")
                    output = Path(self.temporary.name) / f"workspace-{path.name}-{type(value).__name__}.json"
                    result = subprocess.run(
                        check_script + ["--workspace", str(command_workspace), "--output", str(output)],
                        capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertNotIn("Traceback", result.stderr + result.stdout)
                    self.assertEqual(result.stdout, "")
                    self.assertFalse(output.exists())
            path.write_text(json.dumps(original), encoding="utf-8")

    def test_cli_rejects_unhashable_report_json_and_preserves_valid_report(self):
        workspace = self.prepare("onefilebug")
        check_payload = evaluate.check(workspace)
        input_path = Path(self.temporary.name) / "check-input.json"
        input_path.write_text(json.dumps(check_payload), encoding="utf-8")
        report_script = [sys.executable, str(Path(evaluate.__file__).resolve()), "report", "--input", str(input_path)]
        malformed_fields = (
            ("verification", "mode"),
            ("verification", "behavioral_outcome"),
            ("tasks", "task_id"),
            ("checks", "id"),
        )
        for parent_key, field in malformed_fields:
            for value in ([], {}):
                with self.subTest(field=f"{parent_key}.{field}", value=value):
                    malformed = copy.deepcopy(check_payload)
                    if parent_key == "verification":
                        malformed[parent_key][field] = value
                    elif parent_key == "tasks":
                        malformed[parent_key][0][field] = value
                    else:
                        malformed["tasks"][0]["checks"][0][field] = value
                    input_path.write_text(json.dumps(malformed), encoding="utf-8")
                    output = Path(self.temporary.name) / f"report-{parent_key}-{field}-{type(value).__name__}.json"
                    result = subprocess.run(
                        report_script + ["--output", str(output)],
                        capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertNotIn("Traceback", result.stderr + result.stdout)
                    self.assertEqual(result.stdout, "")
                    self.assertFalse(output.exists())

        input_path.write_text(json.dumps(check_payload), encoding="utf-8")
        output = Path(self.temporary.name) / "valid-report.json"
        result = subprocess.run(
            report_script + ["--output", str(output)], capture_output=True, text=True, timeout=15)
        expected = evaluate.build_report(check_payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), expected)


if __name__ == "__main__":
    unittest.main()
