"""Exercise the deployed code-review route in temporary Git work trees."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOLBOX = Path(__file__).resolve().parents[2] / "toolbox.py"


def git(repo, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(repo), *args], stderr=subprocess.PIPE
    )


def snapshot(repo):
    return (
        git(repo, "status", "--porcelain=v2", "-z", "--ignore-submodules=none"),
        git(repo, "rev-parse", "HEAD"),
        hashlib.sha256((repo / ".git/index").read_bytes()).hexdigest(),
        hashlib.sha256((repo / ".git/config").read_bytes()).hexdigest(),
    )


class ScopeContract(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Scope Fixture")
        git(self.repo, "config", "user.email", "scope-fixture@example.invalid")
        self.put("README.md", "fixture\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")

    def put(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def collect(self, *args, exit_code=0):
        before = snapshot(self.repo)
        process = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(TOOLBOX), "run", "--workflow",
             "code-review", "--tool", "git-scope", "--action", "collect", "--",
             "--workspace", ".", "--json", *args],
            cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(process.returncode, exit_code, (process.stdout, process.stderr))
        self.assertEqual(snapshot(self.repo), before)
        return json.loads(process.stdout)

    def test_portable_license_matches_exact_pinned_bytes(self):
        base=Path(__file__).resolve().parent
        lock=json.loads((base/'source-lock.json').read_text(encoding='utf8'))
        self.assertEqual(hashlib.sha256((base/'LICENSE').read_bytes()).hexdigest(),lock['license_sha256'])

    def test_unicode_worktree_paths_and_state_are_preserved(self):
        self.put('允许/中文.md','original text\n')
        git(self.repo,'add','.')
        git(self.repo,'commit','-qm','unicode base')
        self.put('允许/中文.md','changed text\n')
        self.put('外部/新增.txt','new file\n')
        report=self.collect('--allow','允许/**')
        self.assertEqual({row['path'] for row in report['files']},{'允许/中文.md','外部/新增.txt'})
        self.assertIn('外部/新增.txt',report['out_of_scope_paths'])

    def test_nested_directory_is_not_silently_a_different_root(self):
        (self.repo/'nested').mkdir()
        report=self.collect('--workspace','nested',exit_code=1)
        self.assertEqual(report['status'],'ERROR')

    def test_each_rename_endpoint_is_subject_to_scope(self):
        for rel, text in [
            ("allowed/out.txt", "outward move"), ("outside/in.txt", "inward move"),
            ("allowed/old.txt", "inside move"),
        ]:
            self.put(rel, text)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "original paths")
        for source, target in [
            ("allowed/out.txt", "outside/out.txt"), ("outside/in.txt", "allowed/in.txt"),
            ("allowed/old.txt", "allowed/new.txt"),
        ]:
            git(self.repo, "mv", source, target)
        report = self.collect("--staged", "--allow", "allowed/**")
        self.assertEqual(report["out_of_scope_paths"], {
            "outside/out.txt": ["outside/out.txt"], "allowed/in.txt": ["outside/in.txt"],
        })
        self.assertEqual({row["status"] for row in report["files"]}, {"renamed"})

    def test_invalid_and_empty_ranges_return_different_states(self):
        for base in ("missing..HEAD", "HEAD...missing", "--quiet..HEAD", "missing"):
            with self.subTest(base=base):
                failed = self.collect(f"--base={base}", exit_code=1)
                self.assertEqual(failed["status"], "ERROR")
                self.assertNotIn("summary", failed)
        for base in ("HEAD..HEAD", "HEAD...HEAD", "HEAD..."):
            with self.subTest(base=base):
                report = self.collect("--base", base)
                self.assertEqual(report["status"], "OK")
                self.assertEqual(report["summary"]["changed_files"], 0)
                self.assertFalse(report["auto_fallback"])

    def test_gitlink_is_visible_when_git_config_hides_it(self):
        git(self.repo, "config", "diff.ignoreSubmodules", "all")
        git(self.repo, "config", "diff.submodule", "log")
        git(self.repo, "config", "submodule.child.ignore", "all")
        first = git(self.repo, "rev-parse", "HEAD").decode().strip()
        git(self.repo, "update-index", "--add", "--cacheinfo", f"160000,{first},child")
        git(self.repo, "commit", "-qm", "first child")
        second = git(self.repo, "rev-parse", "HEAD").decode().strip()
        git(self.repo, "update-index", "--cacheinfo", f"160000,{second},child")
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only").strip(), b"")
        staged = self.collect("--staged", "--allow", "child")
        self.assertEqual(staged["out_of_scope_paths"], {})
        self.assertEqual([(f["path"], f["gitlink"]) for f in staged["files"]], [("child", True)])
        git(self.repo, "commit", "-qm", "second child")
        history = self.collect("--base", "HEAD^..HEAD", "--allow", "child")
        self.assertEqual([(f["path"], f["gitlink"]) for f in history["files"]], [("child", True)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
