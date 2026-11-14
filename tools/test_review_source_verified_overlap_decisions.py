import unittest
import review_source_verified_overlap_decisions as m
class RuleTests(unittest.TestCase):
 def test_formula_name_contained_organ_is_not_separate_organ(self):
  r={"left_type":"ORGAN","right_type":"FORMULA","overlap_kind":"nested_cross_type_entity","left_start":"0","left_end":"1","right_start":"0","right_end":"3"}
  self.assertEqual(m.decide_entity(r)[0],"KEEP_RIGHT_ONLY")
 def test_herb_name_contained_organ_is_not_separate_organ(self):
  r={"left_type":"HERB","right_type":"ORGAN","overlap_kind":"nested_cross_type_entity","left_start":"0","left_end":"2","right_start":"1","right_end":"2"}
  self.assertEqual(m.decide_entity(r)[0],"KEEP_LEFT_ONLY")
 def test_organ_inside_syndrome_keeps_both(self):
  r={"left_type":"ORGAN","right_type":"SYNDROME","overlap_kind":"nested_cross_type_entity"}
  self.assertEqual(m.decide_entity(r)[0],"KEEP_BOTH")
 def test_partial_overlap_unresolved(self):
  r={"left_type":"HERB","right_type":"FORMULA","overlap_kind":"partial_overlap"}
  self.assertIsNone(m.decide_entity(r))
 def test_technique_not_acupoint_suffix_fragment(self):
  r={"left_type":"ACUPUNCTURE_TECHNIQUE","left_term":"针刺","right_type":"ACUPOINT","right_term":"刺入穴"}
  self.assertEqual(m.decide_contextual(r)[0],"KEEP_LEFT_ONLY")
 def test_complete_pattern_and_region_kept(self):
  r={"left_type":"CLASSICAL_THEORY","left_term":"下焦","right_type":"SYNDROME","right_term":"下焦有热"}
  self.assertEqual(m.decide_contextual(r)[0],"KEEP_BOTH")
 def test_same_token_symptom_and_syndrome_unresolved(self):
  r={"left_type":"SYMPTOM","left_term":"头痛","right_type":"SYNDROME","right_term":"头痛"}
  self.assertIsNone(m.decide_contextual(r))
if __name__=="__main__": unittest.main()
