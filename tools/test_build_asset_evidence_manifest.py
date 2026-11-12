import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_asset_evidence_manifest.py")
SPEC = importlib.util.spec_from_file_location("build_asset_evidence_manifest", MODULE_PATH)
manifest = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(manifest)


class AssetEvidenceManifestTests(unittest.TestCase):
    def write_queue(self, path, rows):
        fields = ["reference", "candidate_status", "candidate_count", "candidate_paths"]
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_fingerprints_existing_files_and_keeps_content_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / "assets"
            assets.mkdir()
            (assets / "herb.jpg").write_bytes(b"same image bytes")
            queue = root / "queue.csv"
            self.write_queue(queue, [
                {"reference": "assets/herb", "candidate_status": "ONE_CANDIDATE",
                 "candidate_count": "1", "candidate_paths": "assets/herb.jpg"},
                {"reference": "assets/missing", "candidate_status": "NO_CANDIDATE",
                 "candidate_count": "0", "candidate_paths": ""},
            ])
            result = manifest.build_manifest(manifest.read_queue(queue), assets, root / "out")
            self.assertEqual(result["present"], 1)
            self.assertEqual(result["no_candidate"], 1)
            with (root / "out" / "asset_evidence_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["file_status"], "PRESENT")
            self.assertEqual(rows[0]["file_size_bytes"], str(len(b"same image bytes")))
            self.assertEqual(rows[0]["evidence_scope"], "BYTE_FINGERPRINT_ONLY_CONTENT_AND_REFERENCE_UNVERIFIED")
            self.assertEqual(rows[1]["file_status"], "NO_CANDIDATE")
            self.assertIn("不证明文件内容", (root / "out" / "asset_evidence_manifest.md").read_text(encoding="utf-8"))

    def test_rejects_traversal_and_symlink_escape_without_reading_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / "assets"
            assets.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (assets / "escape.txt").symlink_to(outside)
            queue = root / "queue.csv"
            self.write_queue(queue, [
                {"reference": "assets/a", "candidate_status": "ONE_CANDIDATE",
                 "candidate_count": "1", "candidate_paths": "assets/../outside.txt"},
                {"reference": "assets/b", "candidate_status": "ONE_CANDIDATE",
                 "candidate_count": "1", "candidate_paths": "assets/escape.txt"},
            ])
            result = manifest.build_manifest(manifest.read_queue(queue), assets, root / "out")
            self.assertEqual(result["unsafe"], 2)

    def test_rejects_inconsistent_queue_and_non_assets_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / "queue.csv"
            self.write_queue(queue, [
                {"reference": "assets/a", "candidate_status": "ONE_CANDIDATE",
                 "candidate_count": "2", "candidate_paths": "assets/a.jpg"},
            ])
            with self.assertRaises(ValueError):
                manifest.read_queue(queue)
            with self.assertRaises(ValueError):
                manifest.safe_candidate_path("../outside.txt")
            with self.assertRaises(ValueError):
                manifest.safe_candidate_path("other/file.jpg")


if __name__ == "__main__":
    unittest.main()
