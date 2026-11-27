"""Synthetic response-policy cases; never represents a live model invocation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from test_contract import tool
import reassess_report

class ResponsePolicy(unittest.TestCase):
    def setUp(self):self.slots={'1':{'text':'source 20'},'2':{'text':'unchanged'}}
    def parse(self,value,**options):return tool.response_items(json.dumps(value),report_slots=self.slots,**options)
    def test_exact_noop_is_retained_only_under_explicit_new_policy(self):
        value={'items':[{'id':'1','text':'source 20','reason':'inaccurate reason does not change source'}],'retained_ids':['2']}
        with self.assertRaisesRegex(tool.Failed,'invalid_candidate_structure'):self.parse(value)
        rows=self.parse(value,allow_noop_edits=True)
        self.assertEqual(rows[0]['text'],'source 20');self.assertNotEqual(rows[0]['reason'],value['items'][0]['reason'])
    def test_noop_cannot_hide_movement_extra_fields_or_ambiguous_coverage(self):
        cases=[{'items':[{'id':'1','text':'source 20','moves_from':['2']}],'retained_ids':['2']},
               {'items':[{'id':'1','text':'source 20','other':True}],'retained_ids':['2']},
               {'items':[{'id':'1','text':'source 20'}],'retained_ids':['1','2']},
               {'items':[],'retained_ids':['1']},{'items':[],'retained_ids':['1','2','3']}]
        for value in cases:
            with self.subTest(value=value),self.assertRaises(tool.Failed):self.parse(value,allow_noop_edits=True)
    def test_malformed_json_and_new_quote_or_number_loss_remain_rejected(self):
        with self.assertRaises(tool.Failed):tool.response_items('{"items":[',report_slots=self.slots,allow_noop_edits=True)
        for text in ['“accept/reject”, 20 and 20','accept/reject, 20']:
            self.assertTrue(tool.report_prose_issues([{'id':'p','text':'accept/reject, 20 and 20'}],{'p':{}},{'p':{'text':text}}))
    def test_unknown_derived_version_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'unknown_reassessment_version'):
            reassess_report.verify(SimpleNamespace(),'game-research',{}, {'reassessment':{'version':'unknown'}})
    def test_fixture_is_not_promoted_to_saved_live_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths={}
            for name in reassess_report.MEMBERS:
                value={'mode':'fixture','status':'partial'} if name=='original_receipt' else {}
                p=root/(name+'.json');p.write_text(json.dumps(value),encoding='utf8');paths[name]=str(p)
            with self.assertRaisesRegex(ValueError,'original_partial_live_required'):
                reassess_report.build(SimpleNamespace(),'game-research',paths)

if __name__=='__main__':unittest.main()
