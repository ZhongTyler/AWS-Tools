"""Historical report prompts remain independently replayable without changing evidence."""
import copy
import json
import unittest

from test_contract import tool, report_request, report_fixture, approve, request


class ReportHistoryTests(unittest.TestCase):
    workflow = 'game-research'

    def candidate(self, source, version):
        return tool.candidate_receipt(self.workflow, source,
            lambda _: report_fixture(self.workflow, source), 'fixture', editor_version=version)

    def check(self, source, receipt):
        reviews = [approve(row) for row in receipt['items']]
        reviews.append(approve({'id': '/report-review', 'review_key': receipt['report_review_key']}))
        return tool.adoption_check(self.workflow, source, receipt, reviews)

    def test_each_known_prompt_replays_saved_payload_and_native_check(self):
        source = report_request()
        for version in ('1.0.0', '1.1.0'):
            with self.subTest(version=version):
                payload = tool.report_payload(self.workflow, source, editor_version=version)
                receipt = self.candidate(source, version)
                original = tool.json_bytes(receipt)
                result = tool.verify_report_payload(self.workflow, source, payload, expected_document=receipt['document'])
                self.assertEqual(result['editor_version'], version)
                self.assertEqual(self.check(source, receipt)['status'], 'pass')
                self.assertEqual(tool.prepare_edit_request(source, self.workflow, expected_document=receipt['document'])[3], receipt['document'])
                self.assertEqual(tool.json_bytes(receipt), original)

    def test_export_prompt_and_checked_prompt_are_distinct_and_wire_capture_unknown(self):
        source = report_request()
        old_payload = tool.report_payload(self.workflow, source, editor_version='1.0.0')
        export = tool.verify_report_payload(self.workflow, source, old_payload)
        checked = self.check(source, self.candidate(source, '1.1.0'))
        identity = tool.checked_report_identity(self.workflow, source, checked, export_document=export['document'])
        self.assertTrue(identity['prompt_changed_since_export'])
        self.assertEqual(identity['export_editor_version'], '1.0.0')
        self.assertEqual(identity['checked_editor_version'], '1.1.0')
        self.assertIn('unknown', identity['actual_transport_payload'])
        with self.assertRaisesRegex(tool.Failed, 'saved_payload_document_mismatch'):
            tool.verify_report_payload(self.workflow, source, old_payload, expected_document=checked['document'])

    def test_changed_prompt_user_layout_generation_or_source_cannot_replay(self):
        source = report_request()
        payload = tool.report_payload(self.workflow, source, editor_version='1.0.0')
        for key in ('systemInstruction', 'contents', 'generationConfig'):
            changed = copy.deepcopy(payload)
            changed[key] = {'unknown': True}
            with self.subTest(key=key), self.assertRaisesRegex(tool.Failed, 'unknown_or_changed_saved_report_payload'):
                tool.verify_report_payload(self.workflow, source, changed)
        checked = self.check(source, self.candidate(source, '1.0.0'))
        changed = copy.deepcopy(source)
        changed['document']['source']['title'] += '漂移'
        with self.assertRaisesRegex(tool.Failed, 'document_source_changed_or_scope_mismatched'):
            self.check(changed, self.candidate(source, '1.0.0'))
        with self.assertRaises(tool.Failed):
            tool.checked_report_identity(self.workflow, changed, checked, export_document=checked['document'])

    def test_unknown_versions_and_nonreport_options_fail(self):
        for version in ('unknown', [], 1):
            with self.subTest(version=version), self.assertRaises(tool.Failed):
                tool.report_payload(self.workflow, report_request(), editor_version=version)
        with self.assertRaisesRegex(tool.Failed, 'editor_version_requires_report'):
            tool.candidate_receipt('personal-site-copy', request('website', '原稿'), lambda _: {}, 'fixture', editor_version='1.0.0')

    def test_partial_or_changed_scope_is_never_upgraded_to_checked(self):
        source = report_request()
        checked = self.check(source, self.candidate(source, '1.0.0'))
        for change in ('status', 'report_review', 'workflow', 'document_key'):
            bad = copy.deepcopy(checked)
            if change == 'document_key':
                bad['document'][change] = 'unknown'
            else:
                bad[change] = 'partial'
            with self.subTest(change=change), self.assertRaises(tool.Failed):
                tool.checked_report_identity(self.workflow, source, bad, export_document=checked['document'])


if __name__ == '__main__':
    unittest.main()
