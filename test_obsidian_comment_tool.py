import tempfile
import unittest
from pathlib import Path

from obsidian_comment_tool import clean_folder, strip_highlight_markers


class StripHighlightMarkersTests(unittest.TestCase):
    def test_strips_markers_and_preserves_content(self) -> None:
        text, count = strip_highlight_markers("Avant ==texte== et ==autre texte==.")

        self.assertEqual(text, "Avant texte et autre texte.")
        self.assertEqual(count, 2)

    def test_clean_folder_is_recursive_and_ignores_hidden_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            folder = Path(temporary_dir)
            nested_note = folder / "dossier" / "note.md"
            hidden_note = folder / ".obsidian" / "interne.md"
            nested_note.parent.mkdir()
            hidden_note.parent.mkdir()
            nested_note.write_text("Un ==passage==.", encoding="utf-8")
            hidden_note.write_text("Un ==réglage==.", encoding="utf-8")

            result = clean_folder(folder)

            self.assertEqual(nested_note.read_text(encoding="utf-8"), "Un passage.")
            self.assertEqual(hidden_note.read_text(encoding="utf-8"), "Un ==réglage==.")
            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.modified_files, 1)
            self.assertEqual(result.removed_markers, 1)

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            note = Path(temporary_dir) / "note.md"
            note.write_text("Un ==passage==.", encoding="utf-8")

            result = clean_folder(Path(temporary_dir), dry_run=True)

            self.assertEqual(note.read_text(encoding="utf-8"), "Un ==passage==.")
            self.assertEqual(result.modified_files, 1)


if __name__ == "__main__":
    unittest.main()
