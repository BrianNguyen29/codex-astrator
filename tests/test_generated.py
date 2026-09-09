from __future__ import annotations

from pathlib import Path
import random
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "install.py"


class GeneratedPayloadTests(unittest.TestCase):
    def _generate(self, target: Path) -> None:
        result = subprocess.run(
            [
                sys.executable, str(INSTALL), "install", "--source", str(ROOT),
                "--scope", "project", "--target", str(target), "--apply",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_generated_toml_preserves_reference_and_role_invariants(self) -> None:
        with tempfile.TemporaryDirectory(prefix="astrator generated ") as temporary:
            target = Path(temporary)
            self._generate(target)
            generated = tomllib.loads((target / ".codex" / "config.toml").read_text(encoding="utf-8"))
            reference = tomllib.loads((ROOT / "profiles" / "reference.toml").read_text(encoding="utf-8"))
            self.assertEqual(generated, reference)

            names = set()
            for path in sorted((target / ".codex" / "agents").glob("*.toml")):
                role = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(role["name"], path.stem)
                self.assertNotIn(role["name"], names)
                names.add(role["name"])
                for key in ("description", "model", "model_reasoning_effort", "sandbox_mode", "developer_instructions"):
                    self.assertIsInstance(role[key], str)
                    self.assertTrue(role[key])
            self.assertEqual(len(names), 6)

    def test_clean_generation_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="astrator deterministic ") as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            first.mkdir()
            second.mkdir()
            self._generate(first)
            self._generate(second)
            excluded = {".codex/.astrator.lock"}
            first_files = {
                path.relative_to(first).as_posix(): path.read_bytes()
                for path in first.rglob("*") if path.is_file()
                and path.relative_to(first).as_posix() not in excluded
            }
            second_files = {
                path.relative_to(second).as_posix(): path.read_bytes()
                for path in second.rglob("*") if path.is_file()
                and path.relative_to(second).as_posix() not in excluded
            }
            self.assertEqual(first_files, second_files)

    def test_seeded_merge_corpus_preserves_unmanaged_toml_and_is_idempotent(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import install

        generator = random.Random(20260909)
        profile = [
            install.ProfileKey((), "model", "gpt-test"),
            install.ProfileKey(("features",), "multi_agent", True),
            install.ProfileKey(("features", "context"), "experimental_mode", True),
        ]
        for _ in range(24):
            newline = generator.choice(("\n", "\r\n"))
            unicode_value = generator.choice(("xin chào", "安全", "café", "🌙"))
            number = generator.randrange(1, 10_000)
            existing = newline.join(
                (
                    f'"quoted key" = {unicode_value!r}',
                    f"unmanaged_number = {number}",
                    'notes = """unmanaged multiline',
                    "[not.a.table]",
                    f'{unicode_value} # still string"""',
                    "[features]",
                    f'unchanged = "{unicode_value}"',
                    "[features.context]",
                    "unmanaged_nested = true",
                    "",
                )
            ).replace(f"{unicode_value!r}", '"' + unicode_value + '"')
            merged, conflicts = install._merge_profile(existing.encode("utf-8"), profile, False)
            self.assertEqual(conflicts, [])
            parsed = tomllib.loads(merged.decode("utf-8"))
            self.assertEqual(parsed["quoted key"], unicode_value)
            self.assertEqual(parsed["unmanaged_number"], number)
            self.assertEqual(parsed["features"]["unchanged"], unicode_value)
            self.assertTrue(parsed["features"]["context"]["unmanaged_nested"])
            self.assertEqual(parsed["model"], "gpt-test")
            self.assertTrue(parsed["features"]["multi_agent"])
            self.assertTrue(parsed["features"]["context"]["experimental_mode"])
            self.assertIn(newline, merged.decode("utf-8"))
            repeated, repeated_conflicts = install._merge_profile(merged, profile, False)
            self.assertEqual(repeated_conflicts, [])
            self.assertEqual(repeated, merged)

    def test_malformed_toml_apply_leaves_target_unchanged(self) -> None:
        malformed_cases = (
            b"[features\nmulti_agent = false\n",
            b"key = \"unterminated\n",
            b"[features]\nmulti_agent = [1,,2]\n",
        )
        for malformed in malformed_cases:
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory(prefix="astrator malformed ") as temporary:
                target = Path(temporary)
                config = target / ".codex" / "config.toml"
                config.parent.mkdir()
                config.write_bytes(malformed)
                (target / ".codex" / ".astrator.lock").write_bytes(b"codex-astrator installer lock\n")
                before = {
                    path.relative_to(target).as_posix(): path.read_bytes()
                    for path in target.rglob("*") if path.is_file()
                }
                result = subprocess.run(
                    [
                        sys.executable, str(INSTALL), "install", "--source", str(ROOT),
                        "--scope", "project", "--target", str(target), "--apply",
                    ],
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 2)
                after = {
                    path.relative_to(target).as_posix(): path.read_bytes()
                    for path in target.rglob("*") if path.is_file()
                }
                self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
