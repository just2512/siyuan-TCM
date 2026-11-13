import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_relation_candidates import (
    extract,
    extract_source_note_associations,
    validate,
)


CONTEXT_FIELDS = [
    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
    "character_end", "evidence_start", "evidence_text", "classification_status",
]
MENTION_FIELDS = [
    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
    "character_end", "document", "source_sha256", "tree_position", "block_id",
]


def write_fixture(root: Path, source_text: str, unit_id: str, document: str,
                  sha: str, tree_position: str, block_id: str, terms: list[tuple[str, str, str]],
                  point_mentions: list[str] | None = None):
    context = root / "context.csv.gz"
    mentions = root / "mentions.csv.gz"
    units = root / "units.jsonl.gz"
    output = root / "relations.csv"
    with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CONTEXT_FIELDS)
        writer.writeheader()
        for candidate_id, term, candidate_type in terms:
            start = source_text.index(term)
            writer.writerow({
                "candidate_id": candidate_id,
                "term": term,
                "candidate_type": candidate_type,
                "rule_id": candidate_type + "_RULE",
                "evidence_document": document,
                "source_sha256": sha,
                "tree_position": tree_position,
                "block_id": block_id,
                "unit_id": unit_id,
                "character_start": start,
                "character_end": start + len(term),
                "evidence_start": 0,
                "evidence_text": source_text,
                "classification_status": "CONTEXT_RULE_CANDIDATE",
            })
    with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MENTION_FIELDS)
        writer.writeheader()
        for index, term in enumerate(point_mentions or []):
            start = source_text.index(term)
            writer.writerow({
                "mention_id": f"point-mention-{index}",
                "unit_id": unit_id,
                "entity_type": "POINT",
                "matched_text": term,
                "character_start": start,
                "character_end": start + len(term),
                "document": document,
                "source_sha256": sha,
                "tree_position": tree_position,
                "block_id": block_id,
            })
    unit = {
        "unit_id": unit_id,
        "source": {
            "document": document,
            "sha256": sha,
            "tree_position": tree_position,
            "block_id": block_id,
        },
        "content": {"source_text": source_text},
    }
    with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
        stream.write(json.dumps(unit, ensure_ascii=False))
                stream.write(chr(10))
    return context, mentions, units, output


class SourceNoteAssociationTests(unittest.TestCase):
    def test_symptom_label_links_to_points_and_acupuncture_techniques(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_text = "月经痛：针灸关元穴，艾灸血海穴；三阴交。"
            terms = [
                ("symptom-1", "月经痛", "SYMPTOM"),
                ("tech-1", "针灸", "ACUPUNCTURE_TECHNIQUE"),
                ("point-candidate-1", "关元穴", "ACUPOINT"),
                ("tech-2", "艾灸", "ACUPUNCTURE_TECHNIQUE"),
                ("point-candidate-2", "血海穴", "ACUPOINT"),
            ]
            context, mentions, units, output = write_fixture(
                root, source_text, "u1", "note/a.sy", "sha-a", "0.1", "b1",
                terms, point_mentions=["三阴交"],
            )
            self.assertEqual(
                extract(context, mentions, units, output)["contextual_relation_candidates"], 0
            )
            self.assertEqual(
                extract_source_note_associations(context, mentions, units, output), 5
            )
            self.assertEqual(validate(output, units, context, mentions), 5)
            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({row["predicate"] for row in rows}, {"SOURCE_NOTE_ASSOCIATES"})
            self.assertEqual(
                {row["object_text"] for row in rows},
                {"针灸", "关元穴", "艾灸", "血海穴", "三阴交"},
            )
            self.assertTrue(all(row["resolution_status"] == "UNRESOLVED_CANDIDATE" for row in rows))
            self.assertTrue(all(row["evidence_text"] == source_text for row in rows))

    def test_explicit_inner_canon_attribution_links_to_classical_theory(self):
        fixtures = [
            (
                "内经说人身上有四个气街。",
                [("classical-source", "内经", "CLASSICAL_SOURCE"),
                 ("theory", "气街", "CLASSICAL_THEORY")],
                "说",
            ),
            (
                "故黄帝内经有言：水精四布，下输膀胱。",
                [("classical-source", "黄帝内经", "CLASSICAL_SOURCE"),
                 ("theory", "水精四布", "CLASSICAL_THEORY")],
                "有言",
            ),
        ]
        for index, (source_text, terms, marker) in enumerate(fixtures):
            with self.subTest(source_text=source_text), tempfile.TemporaryDirectory() as temp:
                context, mentions, units, output = write_fixture(
                    Path(temp), source_text, f"classical-{index}", "classical/a.sy",
                    f"classical-sha-{index}", "0.1", "block-1", terms,
                )
                self.assertEqual(
                    extract(context, mentions, units, output)["contextual_relation_candidates"], 0
                )
                self.assertEqual(extract_source_note_associations(context, mentions, units, output), 1)
                self.assertEqual(validate(output, units, context, mentions), 1)
                with output.open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                row = rows[0]
                self.assertEqual(row["predicate"], "SOURCE_NOTE_ASSOCIATES")
                self.assertEqual(row["subject_type"], "CLASSICAL_SOURCE")
                self.assertEqual(row["object_type"], "CLASSICAL_THEORY")
                self.assertEqual(row["predicate_text"], marker)
                self.assertEqual(
                    row["extraction_rule"], "SOURCE_NOTE_ASSOCIATES_CLASSICAL_ATTRIBUTION_V1"
                )
                self.assertEqual(row["evidence_text"], source_text)
                self.assertEqual(row["resolution_status"], "UNRESOLVED_CANDIDATE")

    def test_point_label_links_to_multiple_symptom_mentions_in_source_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_text = "中脘穴：胃痛、恶心、呕吐。"
            terms = [
                ("point-label", "中脘穴", "ACUPOINT"),
                ("symptom-1", "胃痛", "SYMPTOM"),
                ("symptom-2", "恶心", "SYMPTOM"),
                ("symptom-3", "呕吐", "SYMPTOM"),
            ]
            context, mentions, units, output = write_fixture(
                root, source_text, "u2", "note/b.sy", "sha-b", "0.2", "b2", terms
            )
            self.assertEqual(
                extract(context, mentions, units, output)["contextual_relation_candidates"], 0
            )
            self.assertEqual(
                extract_source_note_associations(context, mentions, units, output), 3
            )
            self.assertEqual(validate(output, units, context, mentions), 3)
            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(all(row["subject_type"] == "ACUPOINT" for row in rows))
            self.assertEqual({row["object_text"] for row in rows}, {"胃痛", "恶心", "呕吐"})


if __name__ == "__main__":
    unittest.main()
