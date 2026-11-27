"""Synthetic offline author-freeze contracts; no model, server or live receipt."""
from copy import deepcopy
import json
import unittest
import test_contract as contract

tool = contract.tool

class AuthorFrozenTests(unittest.TestCase):
    frozen = ['/sections/0/blocks/1/text', '/sections/1/blocks/0/text']

    def source(self):
        request = contract.report_request()
        request['document']['retain'] = dict.fromkeys(self.frozen, 'author_frozen')
        return request

    def test_readonly_wire_and_complete_source_roundtrip(self):
        request = self.source()
        payload = tool.report_payload('game-research', request)
        wire = json.loads(payload['contents'][0]['parts'][0]['text'])
        readonly = []
        def walk(value):
            if isinstance(value, list):
                if len(value) >= 3 and value[0] is None:
                    readonly.append(value[2])
                for child in value: walk(child)
            elif isinstance(value, dict):
                for child in value.values(): walk(child)
        walk(wire)
        self.assertIn('观察「复位」后的结果。', readonly)
        self.assertIn('只在该条件下成立。', readonly)
        fixture = contract.ReportEditorTests()
        candidate = fixture.candidate(request)
        self.assertEqual(candidate['mode'], 'fixture')
        checked = fixture.check(request, candidate)
        self.assertEqual(checked['status'], 'pass')
        self.assertEqual(checked['revised_source'], request['document']['source'])
        self.assertEqual(checked['revised_surfaces'], {k:v['text'] for k,v in request['document']['surfaces'].items()})

    def test_freeze_changes_identity_and_old_receipt_cannot_authorize_it(self):
        old = contract.report_request()
        fixture = contract.ReportEditorTests()
        candidate = fixture.candidate(old)
        frozen = self.source()
        self.assertNotEqual(tool.report_revision(old['document']), tool.report_revision(frozen['document']))
        with self.assertRaises(tool.Failed): fixture.check(frozen, candidate)
        unknown = deepcopy(frozen)
        unknown['document']['retain']['/sections/99/blocks/0/text'] = 'author_frozen'
        with self.assertRaises(tool.Failed): tool.report_payload('game-research', unknown)

    def test_other_profile_retention_policy_and_numeric_guard_stay_strict(self):
        study = contract.report_request()
        study['document']['format'] = 'research-study-v1'
        study['document'].pop('presentation')
        study['document'].pop('protect')
        study['document']['retain'] = {'/title':'fixed_label'}
        tool.prepare_edit_request(study, 'game-research')
        study['document']['retain']['/title'] = 'author_frozen'
        with self.assertRaises(tool.Failed): tool.prepare_edit_request(study, 'game-research')
        request = self.source()
        candidate = tool.candidate_receipt('game-research', request,
            lambda _: contract.report_fixture('game-research', request, {'先运行 20 次。':'先运行 21 次。'}), 'fixture')
        self.assertEqual(candidate['status'], 'partial')
        self.assertTrue(any(row['status']=='protection_failed' for row in candidate['items']))

if __name__ == '__main__': unittest.main()
