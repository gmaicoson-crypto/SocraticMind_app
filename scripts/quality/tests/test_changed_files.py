import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.quality.changed_files import collect


class ChangedFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "test/gy/scope")
        self.git("config", "user.name", "Scope Test")
        self.git("config", "user.email", "scope@example.test")

    def git(self, *arguments):
        return (
            subprocess.check_output(
                ["git", "-C", str(self.root), *arguments], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )

    def write(self, name, content="sample\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-m", "test: 创建范围用例")
        return self.git("rev-parse", "HEAD")

    def test_unborn_repository_includes_staged_and_untracked_not_ignored(self):
        self.write(".gitignore", "ignored/\n")
        self.write("已暂存.py")
        self.git("add", "已暂存.py")
        self.write("未暂存 name.py")
        self.write("ignored/private.py")
        result = collect(self.root)
        self.assertTrue(result["initial"])
        self.assertEqual([".gitignore", "已暂存.py", "未暂存 name.py"], result["files"])

    def test_worktree_uses_complete_current_file_not_staged_snapshot(self):
        self.write("code.py")
        base = self.commit()
        self.write("code.py", "staged\n")
        self.git("add", "code.py")
        self.write("code.py", "unstaged\n")
        result = collect(self.root)
        self.assertEqual(base, result["base"])
        self.assertEqual(["code.py"], result["files"])
        self.assertEqual("staged", self.git("show", ":code.py"))
        self.assertEqual("unstaged\n", (self.root / "code.py").read_text())

    def test_rename_is_explicit_delete_and_add_even_with_unusual_names(self):
        self.write("old\n中文.py")
        base = self.commit()
        self.git("mv", "old\n中文.py", "new space.py")
        head = self.commit()
        self.assertEqual(["new space.py", "old\n中文.py"], collect(self.root, base, head)["files"])

    def test_commit_range_excludes_uncommitted_files(self):
        self.write("old.py")
        base = self.commit()
        self.write("new.py")
        head = self.commit()
        self.write("not-in-commit.py")
        self.assertEqual(["new.py"], collect(self.root, base, head)["files"])

    def test_initial_commit_never_assumes_a_parent(self):
        self.write("first.py")
        head = self.commit()
        self.assertEqual(["first.py"], collect(self.root, head=head, initial=True)["files"])

    def test_clean_worktree_reports_an_empty_set(self):
        self.write("code.py")
        self.commit()
        self.assertEqual([], collect(self.root)["files"])

    def test_invalid_or_ambiguous_revisions_fail(self):
        self.write("code.py")
        self.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            collect(self.root, base="does-not-exist")
        with self.assertRaises(ValueError):
            collect(self.root, head="HEAD")
        with self.assertRaises(ValueError):
            collect(self.root, base="HEAD", initial=True)


if __name__ == "__main__":
    unittest.main()
