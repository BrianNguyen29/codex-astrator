from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts" / "install.py"


class InstallerLockTests(unittest.TestCase):
    def test_two_process_contention_is_deterministic_and_recoverable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="astrator lock ") as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            holder_code = (
                "import pathlib,sys; sys.path.insert(0,sys.argv[1]); "
                "from install import TargetLock; target=pathlib.Path(sys.argv[2]); "
                "lock=TargetLock(target); lock.__enter__(); print('LOCKED', flush=True); "
                "sys.stdin.readline(); lock.__exit__(None,None,None)"
            )
            holder = subprocess.Popen(
                [sys.executable, "-c", holder_code, str(ROOT / "scripts"), str(target)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(holder.stdout.readline().strip(), "LOCKED")
                command = [
                    sys.executable, str(INSTALL), "install", "--source", str(ROOT),
                    "--scope", "project", "--target", str(target), "--apply",
                ]
                blocked = subprocess.run(command, text=True, capture_output=True, timeout=10)
                self.assertEqual(blocked.returncode, 2)
                self.assertIn("another codex-astrator apply is active", blocked.stderr)
                self.assertFalse((target / ".codex" / "astrator-manifest.json").exists())

                preview = subprocess.run(command[:-1], text=True, capture_output=True, timeout=10)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                self.assertIn("PREVIEW", preview.stdout)
            finally:
                if holder.stdin:
                    holder.stdin.write("release\n")
                    holder.stdin.flush()
                holder.wait(timeout=10)
            holder_error = holder.stderr.read() if holder.stderr else ""
            for stream in (holder.stdin, holder.stdout, holder.stderr):
                if stream:
                    stream.close()
            self.assertEqual(holder.returncode, 0, holder_error)
            applied = subprocess.run(command, text=True, capture_output=True, timeout=20)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            lock_path = target / ".codex" / ".astrator.lock"
            self.assertEqual(lock_path.read_bytes(), b"codex-astrator installer lock\n")


if __name__ == "__main__":
    unittest.main()
