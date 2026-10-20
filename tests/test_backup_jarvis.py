"""Tests for backing up and restoring Jarvis's personal data:  python -m unittest tests.test_backup_jarvis -v"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backup_jarvis as B  # noqa: E402


def make_tree(root, extra=None):
    """A little Jarvis folder: some personal data, some models, some code."""
    files = {".env": "USER_NAME=Ali\nJARVIS_PASSWORD_HASH=abc\n", "DataBase/Notes/n1.txt": "buy milk", "DataBase/Tasks/t1.txt": "call ali", "DataBase/memory.json": "{}",
             "DataBase/voiceprint.npz": "voice", "DataBase/FaceDetectionModule/trainer/trainer.yml": "face", "DataBase/FaceDetectionModule/samples/1.jpg": "photo",
             "Logs/conversations/2026-10-20.jsonl": "{}", "training/nlu_real.txt": "hello", "models/piper/v.onnx": "x" * 100, "models/nlu.joblib": "y" * 50,
             "config.py": "# code", "Startup.py": "# code", "DataBase/__pycache__/x.pyc": "junk", ".venv/lib/x.py": "junk"}
    files.update(extra or {})
    for relative, text in files.items():
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Path(root)


class Folders(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.project = make_tree(self.temp / "project")
        self.drive = self.temp / "drive"
        self.drive.mkdir()


class InventoryTests(Folders):
    def test_it_counts_each_part_and_leaves_out_rebuilt_folders(self):
        found = B.inventory(self.project)
        self.assertEqual(found["settings"]["files"], 1)
        self.assertEqual(found["notes"]["files"], 3)
        self.assertEqual(found["voice"]["files"], 1)
        self.assertEqual(found["face"]["files"], 2)
        self.assertEqual(found["models"]["files"], 2)
        self.assertTrue(found["models"]["big"])
        self.assertNotIn("shortcuts", found)                     # nothing there, so no entry
        self.assertEqual(sum(info["files"] for info in found.values()), 1 + 3 + 1 + 2 + 1 + 1 + 2)

    def test_human_sizes(self):
        self.assertEqual(B.human(933), "933 bytes")
        self.assertEqual(B.human(2048), "2.0 KB")
        self.assertEqual(B.human(5 * 1024 ** 2), "5.0 MB")
        self.assertEqual(B.human(3 * 1024 ** 3), "3.0 GB")


class MakeBackupTests(Folders):
    def test_a_backup_is_a_folder_with_the_files_a_list_and_a_readme(self):
        made = B.make_backup(self.drive, root=self.project)
        self.assertTrue(made.name.startswith("Jarvis-Backup-"))
        self.assertEqual((made / "files" / "DataBase" / "Notes" / "n1.txt").read_text(), "buy milk")
        self.assertTrue((made / "README.txt").exists())
        manifest = json.loads((made / "BACKUP.json").read_text())
        self.assertIn(".env", manifest["files"])
        self.assertEqual(len(manifest["files"]), 9)
        self.assertEqual(B.verify_backup(made), [])

    def test_the_big_models_are_only_included_when_asked(self):
        plain = B.make_backup(self.drive, root=self.project)
        self.assertFalse((plain / "files" / "models").exists())
        with_models = B.make_backup(self.drive, root=self.project, parts=list(B.PARTS))
        self.assertTrue((with_models / "files" / "models" / "piper" / "v.onnx").exists())

    def test_junk_folders_are_never_copied(self):
        made = B.make_backup(self.drive, root=self.project, parts=list(B.PARTS))
        copied = {p.relative_to(made / "files").as_posix() for p in (made / "files").rglob("*") if p.is_file()}
        self.assertFalse(any("__pycache__" in name or ".venv" in name for name in copied))

    def test_two_backups_in_the_same_minute_do_not_collide(self):
        first = B.make_backup(self.drive, root=self.project)
        second = B.make_backup(self.drive, root=self.project)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists() and second.exists())

    def test_verification_notices_a_missing_and_a_changed_file(self):
        made = B.make_backup(self.drive, root=self.project)
        (made / "files" / "DataBase" / "Notes" / "n1.txt").write_text("tampered")
        (made / "files" / "DataBase" / "memory.json").unlink()
        problems = B.verify_backup(made)
        self.assertEqual(sorted(problems), ["changed: DataBase/Notes/n1.txt", "missing: DataBase/memory.json"])

    def test_a_failed_backup_leaves_no_half_made_folder_behind(self):
        with mock.patch("shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                B.make_backup(self.drive, root=self.project)
        self.assertEqual(list(self.drive.iterdir()), [])

    def test_a_missing_destination_is_refused_plainly(self):
        with self.assertRaises(FileNotFoundError):
            B.make_backup(self.temp / "nowhere", root=self.project)


class FindBackupTests(Folders):
    def test_it_finds_our_backups_and_copies_of_the_whole_folder_newest_first(self):
        old = B.make_backup(self.drive, root=self.project)
        manifest = json.loads((old / "BACKUP.json").read_text())
        manifest["made"] = "2026-01-01T10:00:00"
        (old / "BACKUP.json").write_text(json.dumps(manifest))
        copy = make_tree(self.drive / "Backup-2026-10-20" / "Jarvis" / "New Jarvis")
        found = B.find_backups([self.drive])
        kinds = [(b.kind, Path(b.path).name) for b in found]
        self.assertIn(("project", "New Jarvis"), kinds)
        self.assertIn(("package", old.name), kinds)
        self.assertEqual(found[-1].path, old)                      # the 2026-01-01 one is the oldest
        self.assertTrue(copy.exists())

    def test_nothing_found_is_an_empty_list_not_an_error(self):
        self.assertEqual(B.find_backups([self.drive]), [])
        self.assertEqual(B.find_backups([self.temp / "no such drive"]), [])

    def test_the_folder_being_set_up_is_not_offered_as_its_own_backup(self):
        with mock.patch.object(B, "BASE_DIR", self.project):
            self.assertEqual([b for b in B.find_backups([self.temp]) if Path(b.path) == self.project], [])

    def test_saved_ollama_models_are_found_beside_a_whole_folder_copy(self):
        models = self.drive / "Backup" / "Jarvis" / "ollama-models" / "models"
        (models / "manifests").mkdir(parents=True)
        (models / "blobs").mkdir()
        self.assertEqual(B.ollama_models_beside(self.drive / "Backup" / "Jarvis" / "New Jarvis"), models)
        self.assertIsNone(B.ollama_models_beside(self.drive / "elsewhere"))


class RestoreTests(Folders):
    def fresh_target(self):
        target = self.temp / "new pc"
        target.mkdir()
        (target / "config.py").write_text("# code")
        (target / "Startup.py").write_text("# code")
        return target

    def backup_of_project(self):
        return B.Backup(self.project, "project", None, "a copy")

    def test_everything_missing_is_brought_back_from_a_whole_folder_copy(self):
        target = self.fresh_target()
        done = B.restore(self.backup_of_project(), target)
        self.assertEqual(done["copied"], 11)
        self.assertEqual((target / "DataBase" / "Notes" / "n1.txt").read_text(), "buy milk")
        self.assertEqual((target / ".env").read_text(), (self.project / ".env").read_text())

    def test_code_files_of_a_whole_folder_copy_are_not_touched(self):
        target = self.fresh_target()
        (self.project / "config.py").write_text("# an OLD copy of the code")
        B.restore(self.backup_of_project(), target)
        self.assertEqual((target / "config.py").read_text(), "# code")

    def test_models_come_back_only_when_that_part_is_chosen(self):
        target = self.fresh_target()
        B.restore(self.backup_of_project(), target, parts=["settings", "notes"])
        self.assertFalse((target / "models").exists())
        B.restore(self.backup_of_project(), target, parts=["models"])
        self.assertTrue((target / "models" / "piper" / "v.onnx").exists())

    def test_files_that_are_already_the_same_are_left_alone(self):
        target = self.fresh_target()
        B.restore(self.backup_of_project(), target)
        done = B.restore(self.backup_of_project(), target)
        self.assertEqual((done["copied"], done["replaced"], done["kept"]), (0, 0, 0))
        self.assertEqual(done["same"], 11)

    def prepare_conflict(self):
        target = self.fresh_target()
        (target / ".env").write_text("USER_NAME=Somebody else\n")
        return target

    def test_keep_replaces_nothing(self):
        target = self.prepare_conflict()
        done = B.restore(self.backup_of_project(), target, conflict="keep")
        self.assertEqual(done["kept"], 1)
        self.assertEqual((target / ".env").read_text(), "USER_NAME=Somebody else\n")

    def test_replace_takes_the_backups_file_and_first_saves_yours(self):
        target = self.prepare_conflict()
        done = B.restore(self.backup_of_project(), target, conflict="replace")
        self.assertEqual(done["replaced"], 1)
        self.assertIn("Ali", (target / ".env").read_text())
        saved = list((target / "Backups").rglob(".env"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(), "USER_NAME=Somebody else\n")

    def test_keep_newer_takes_whichever_changed_last(self):
        target = self.prepare_conflict()
        old = time.time() - 86400
        os.utime(self.project / ".env", (old, old))                    # the backup's copy is a day older than the one here
        self.assertEqual(B.restore(self.backup_of_project(), target, conflict="keep_newer")["kept"], 1)
        os.utime(self.project / ".env", None)
        os.utime(target / ".env", (old, old))                           # now the one here is the older
        self.assertEqual(B.restore(self.backup_of_project(), target, conflict="keep_newer")["replaced"], 1)

    def test_a_package_backup_round_trips_and_nothing_is_lost(self):
        made = B.make_backup(self.drive, root=self.project)
        target = self.fresh_target()
        backup = B.Backup(made, "package", None, "mine")
        plan = B.plan_restore(backup, target)
        self.assertEqual(len(plan["copy"]), 9)                        # (everything except the models, which a package leaves out)
        B.restore(backup, target)
        self.assertEqual((target / "DataBase" / "voiceprint.npz").read_text(), "voice")

    def test_planning_changes_nothing(self):
        target = self.fresh_target()
        B.plan_restore(self.backup_of_project(), target)
        self.assertFalse((target / ".env").exists())


class StartOverTests(Folders):
    def test_the_owners_things_are_saved_checked_and_only_then_cleared(self):
        (self.project / "DataBase" / "Books").mkdir(parents=True, exist_ok=True)
        (self.project / "DataBase" / "Books" / "story.pdf").write_text("a book")
        (self.project / "DataBase" / "setup_state.json").write_text("{}")
        saved, removed = B.start_over(self.project)
        self.assertEqual(saved.parent, self.project / "Backups")
        self.assertEqual(B.verify_backup(saved), [])
        self.assertEqual((saved / "files" / "DataBase" / "Notes" / "n1.txt").read_text(), "buy milk")
        self.assertEqual(removed, 8)                                                        # .env, 3 notes-part files, voice, 2 face, 1 log
        self.assertFalse((self.project / ".env").exists())
        self.assertEqual(list((self.project / "DataBase" / "Notes").iterdir()), [])         # the folder stays, empty
        self.assertFalse((self.project / "DataBase" / "voiceprint.npz").exists())
        self.assertFalse((self.project / "DataBase" / "setup_state.json").exists())

    def test_books_models_and_the_code_stay(self):
        (self.project / "DataBase" / "Books").mkdir(parents=True, exist_ok=True)
        (self.project / "DataBase" / "Books" / "story.pdf").write_text("a book")
        B.start_over(self.project)
        self.assertEqual((self.project / "DataBase" / "Books" / "story.pdf").read_text(), "a book")
        self.assertTrue((self.project / "models" / "piper" / "v.onnx").exists())
        self.assertTrue((self.project / "config.py").exists())
        self.assertTrue((self.project / "training" / "nlu_real.txt").exists())

    def test_a_copy_that_does_not_check_out_means_nothing_is_cleared(self):
        with mock.patch.object(B, "verify_backup", return_value=["changed: .env"]):
            with self.assertRaises(RuntimeError) as caught:
                B.start_over(self.project)
        self.assertIn("nothing was cleared", str(caught.exception))
        self.assertTrue((self.project / ".env").exists())
        self.assertTrue((self.project / "DataBase" / "Notes" / "n1.txt").exists())

    def test_a_folder_with_nothing_of_the_owners_is_already_brand_new(self):
        empty = self.temp / "empty"
        empty.mkdir()
        self.assertEqual(B.start_over(empty), (None, 0))
        self.assertFalse((empty / "Backups").exists())

    def test_the_saved_copy_can_be_restored_afterwards(self):
        saved, _ = B.start_over(self.project)
        B.restore(B.Backup(saved, "package", None, "before"), self.project)
        self.assertIn("USER_NAME=Ali", (self.project / ".env").read_text())
        self.assertEqual((self.project / "DataBase" / "voiceprint.npz").read_text(), "voice")


if __name__ == "__main__":
    unittest.main()
