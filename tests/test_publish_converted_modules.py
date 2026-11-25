from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.publish_converted_modules import module_filenames, publish


class PublishConvertedModulesTests(unittest.TestCase):
    def test_empty_source_list_prunes_last_generated_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            destination = root / "converted"
            artifact.mkdir()
            destination.mkdir()
            (root / "manifest.json").write_text('{"sources": []}', encoding="utf-8")
            (destination / "removed-module.yaml").write_text("name: stale\n", encoding="utf-8")
            publish(artifact, root / "manifest.json", destination)
            self.assertFalse((destination / "removed-module.yaml").exists())

    def test_failed_active_source_keeps_previous_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            destination = root / "converted"
            artifact.mkdir()
            destination.mkdir()
            (root / "manifest.json").write_text(
                '{"sources": [{"id": "active-module", "name": "Active.beta.module"}]}', encoding="utf-8"
            )
            (destination / "Active.beta.yaml").write_text("name: retained\n", encoding="utf-8")
            publish(artifact, root / "manifest.json", destination)
            self.assertEqual((destination / "Active.beta.yaml").read_text(encoding="utf-8"), "name: retained\n")

    def test_copies_current_artifacts_and_prunes_only_removed_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "artifact"
            destination = root / "modules" / "converted"
            artifact.mkdir()
            destination.mkdir(parents=True)
            name = "WeTalk\u7b7e\u5230.beta"
            (root / "manifest.json").write_text(
                json.dumps({"sources": [{"id": "active-module", "name": f"{name}.SGMODULE"}]}), encoding="utf-8"
            )
            (artifact / "active-module.yaml").write_text("name: updated\n", encoding="utf-8")
            (artifact / f"{name}.yaml").write_text("name: ignored\n", encoding="utf-8")
            (artifact / "summary.md").write_text("sync report\n", encoding="utf-8")
            (destination / f"{name}.yaml").write_text("name: old\n", encoding="utf-8")
            (destination / "active-module.yaml").write_text("name: old path\n", encoding="utf-8")
            (destination / "Removed.beta.yaml").write_text("name: stale\n", encoding="utf-8")
            (destination / "manual-notes.txt").write_text("keep\n", encoding="utf-8")
            summary = root / "summary-out.md"

            publish(artifact, root / "manifest.json", destination, summary)

            self.assertEqual((destination / f"{name}.yaml").read_text(encoding="utf-8"), "name: updated\n")
            self.assertFalse((destination / "active-module.yaml").exists())
            self.assertFalse((destination / "Removed.beta.yaml").exists())
            self.assertEqual((destination / "manual-notes.txt").read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(summary.read_text(encoding="utf-8"), "sync report\n")

    def test_case_and_unicode_collisions_need_distinct_output_names(self) -> None:
        primary = {"id": "primary", "name": "Caf\u00e9.conf"}
        secondary = {"id": "secondary", "name": "CAFE\u0301.sgmodule"}
        manifest = {"sources": [primary, secondary]}

        with self.assertRaises(ValueError):
            module_filenames(manifest)

        secondary["filename"] = "Second-Cafe.yaml"
        self.assertEqual(module_filenames(manifest), {"primary": "Caf\u00e9.yaml", "secondary": "Second-Cafe.yaml"})

    def test_rejects_unsafe_output_names(self) -> None:
        for name in ("../outside", "nested\\module", "CON.beta", "bad:name", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                module_filenames({"sources": [{"id": "source-id", "name": f"{name}.sgmodule"}]})
        with self.assertRaises(ValueError):
            module_filenames({"sources": [{"id": "source-id", "name": "safe.sgmodule", "filename": "bad.yml"}]})


if __name__ == "__main__":
    unittest.main()
