import csv
import json
import tempfile
import unittest
from pathlib import Path

from build_dosage_expression_candidates import build


class DosageExpressionCandidateTests(unittest.TestCase):
    def test_extracts_dosage_patterns_with_document_and_paragraph_locator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            notebook = root / "notebook"
            notebook.mkdir()
            payload = {"Children": [{"Type": "NodeParagraph", "Children": [
                {"Type": "NodeText", "Data": "桂枝三两，芍药二两，水七升，煮取三升。"}
            ]}]}
            (notebook / "formula.sy").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            output = root / "catalog" / "generated"
            result = build(root, output)
            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["candidates"], 3)
            with (output / "dosage_expression_candidates.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["matched_expression"] for row in rows],
                             ["三两", "二两", "七升"])
            self.assertTrue(all(row["document"] == "notebook/formula.sy" for row in rows))
            self.assertTrue(all(row["paragraph_index"] == "1" for row in rows))
            self.assertTrue(all(row["review_status"] == "NOT_REVIEWED" for row in rows))

    def test_does_not_invent_candidates_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broken.sy").write_text("{bad", encoding="utf-8")
            result = build(root, root / "catalog" / "generated")
            self.assertEqual(result["parse_errors"], 1)
            self.assertEqual(result["candidates"], 0)


if __name__ == "__main__":
    unittest.main()
