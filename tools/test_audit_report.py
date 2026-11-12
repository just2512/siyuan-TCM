import json
import tempfile
import unittest
from pathlib import Path

from audit_report import write_audit_report


class AuditReportWriterTests(unittest.TestCase):
    def test_writes_versioned_report_and_preserves_zero_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "audit.json"
            write_audit_report(path, {
                "checked_rows": 0,
                "counts_by_predicate": {"SYMPTOM_TO_SYNDROME": 0},
                "status": "PASS",
            })
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["checked_rows"], 0)
            self.assertEqual(report["counts_by_predicate"]["SYMPTOM_TO_SYNDROME"], 0)
            self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
