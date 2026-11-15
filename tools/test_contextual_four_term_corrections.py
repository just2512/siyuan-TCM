from __future__ import annotations

import unittest

from build_contextual_term_candidates import classify_span


class ContextualFourTermCorrectionTests(unittest.TestCase):
    def test_location_preposition_is_excluded_but_full_acupoint_span_remains(self):
        text = "这是实症，这两个症状，在绝骨穴都会有压痛"
        start = text.index("在绝骨穴")

        for fragment in ("在绝", "在绝骨", "在绝骨穴"):
            self.assertNotIn(
                ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
                classify_span(text, start, start + len(fragment)),
                fragment,
            )
        self.assertNotIn(
            ("ACUPOINT", "ACUPOINT_CONTEXT_01"),
            classify_span(text, start, start + len("在绝骨穴")),
        )

        point_start = start + 1
        self.assertIn(
            ("ACUPOINT", "ACUPOINT_CONTEXT_01"),
            classify_span(text, point_start, point_start + len("绝骨穴")),
        )

    def test_judgment_particle_is_excluded_but_syndrome_span_is_preserved(self):
        text = "一圈地方发凉，这便属于是心痛彻背"
        particle_start = text.index("是心痛彻背")
        for fragment in ("是心", "是心痛", "是心痛彻背"):
            self.assertNotIn(
                ("SYNDROME", "SYNDROME_CONTEXT_01"),
                classify_span(text, particle_start, particle_start + len(fragment)),
                fragment,
            )

        syndrome_start = particle_start + 1
        self.assertIn(
            ("SYNDROME", "SYNDROME_CONTEXT_01"),
            classify_span(text, syndrome_start, syndrome_start + len("心痛彻背")),
        )
        heart_pain_start = text.index("心痛")
        heart_pain_labels = classify_span(text, heart_pain_start, heart_pain_start + len("心痛"))
        self.assertIn(("SYMPTOM", "SYMPTOM_CONTEXT_02"), heart_pain_labels)
        self.assertNotIn(("SYNDROME", "SYNDROME_CONTEXT_01"), heart_pain_labels)

    def test_upper_and_lower_jiao_cold_are_theory_only(self):
        for term in ("上焦寒", "下焦寒"):
            labels = classify_span(term, 0, len(term))
            self.assertIn(("CLASSICAL_THEORY", "CLASSICAL_THEORY_CONTEXT_01"), labels)
            self.assertNotIn(("SYMPTOM", "SYMPTOM_CONTEXT_01"), labels)
            self.assertNotIn(("SYMPTOM", "SYMPTOM_CONTEXT_02"), labels)
            self.assertNotIn(("SYNDROME", "SYNDROME_CONTEXT_01"), labels)

    def test_jiao_cold_does_not_leave_a_symptom_prefix(self):
        for term in ("上焦", "下焦"):
            text = "症状哦，" + term + "寒"
            start = text.index(term)
            labels = classify_span(text, start, start + len(term))
            self.assertNotIn(("SYMPTOM", "SYMPTOM_CONTEXT_01"), labels)
            self.assertNotIn(("SYMPTOM", "SYMPTOM_CONTEXT_02"), labels)

    def test_neighbouring_existing_terms_keep_their_existing_types(self):
        self.assertIn(
            ("CLASSICAL_THEORY", "CLASSICAL_THEORY_CONTEXT_01"),
            classify_span("下焦", 0, len("下焦")),
        )
        self.assertIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_02"),
            classify_span("心痛", 0, len("心痛")),
        )


if __name__ == "__main__":
    unittest.main()
