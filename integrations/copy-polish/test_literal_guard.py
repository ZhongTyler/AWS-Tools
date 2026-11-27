"""Explicit source boundaries retain both legacy Unicode protection and literal counts."""
import hashlib
import unittest
from test_contract import tool


def inventory(text, literals=('outside_ruin',), numbers=()):
    return {'status':'maintenance_reviewed_literal_boundaries','contract_version':'literal-boundaries-v2',
            'source_id':'p','source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'literal_counts':{x:text.count(x) for x in literals}, 'numbers':{x:text.count(x) for x in numbers}}


def issues(before, after, declaration):
    return tool.report_prose_issues([{'id':'p','text':before}], {'p':{}},
                                   {'p':{'id':'p','text':after}}, literal_inventory=declaration)


class LiteralBoundaries(unittest.TestCase):
    def test_cjk_prose_and_identifier_spacing_are_not_code_changes(self):
        before='20项规则依赖按evidence/sources/rules.json声明替身，另见first-floor，旧outside_ruin蓝图。'
        after='20 项规则按 evidence/sources/rules.json 声明替身，另见 first-floor，旧 outside_ruin 蓝图。'
        declaration=inventory(before,('evidence/sources/rules.json','first-floor','outside_ruin'),('20',))
        self.assertEqual(issues(before,after,declaration),set())

    def test_original_seven_counterexamples_still_reject(self):
        for before,after in [('20','21'),('20','20再20'),('evidence/rules.json','evidence/other.json'),
                             ('outside_ruin','inside_ruin'),('“资源/规则.json”','“资源/新规.json”'),
                             ('资源/规则.json','资源/新规.json'),('evidence/规则.json','evidence/新规.json')]:
            with self.subTest(before=before):
                source='anchor_id；'+before
                self.assertTrue(issues(source,'anchor_id；'+after,inventory(source,('anchor_id',))))

    def test_declared_unicode_paths_counts_and_added_residual_paths_reject(self):
        before='outside_ruin，资源/规则.json，20项。'
        declaration=inventory(before,('outside_ruin','资源/规则.json'),('20',))
        for after in ['outside_ruin，新资源/规则.json，20项。','outside_ruin，资源/新规.json，20项。',
                      before+' 新资源/另一.json',before+' evidence/another.json',before+' outside_ruin',
                      before.replace('20','120'),before.replace('20','20，再20')]:
            with self.subTest(after=after):self.assertTrue(issues(before,after,declaration))

    def test_connected_code_and_directory_changes_reject(self):
        before='见evidence/rules.json与outside_ruin。'
        declaration=inventory(before,('evidence/rules.json','outside_ruin'))
        for after in ['见新目录/evidence/rules.json与outside_ruin。','见evidence/rules.json.bak与outside_ruin。',
                      '见evidence/rules.json与new_outside_ruin。']:
            with self.subTest(after=after):self.assertTrue(issues(before,after,declaration))

    def test_chinese_number_counts_reject(self):
        before='outside_ruin，十八类工具、十二条定义。'
        declaration=inventory(before,('outside_ruin',),('十八','十二'))
        for after in [before.replace('十八','十九'),before+'十八',before.replace('十八','一十八')]:
            self.assertTrue(issues(before,after,declaration))

    def test_new_quotes_and_code_changes_reject(self):
        before='outside_ruin，接受或拒绝，`变量`保持。'
        declaration=inventory(before)
        for after in [before.replace('接受或拒绝','“接受/拒绝”'),before.replace('变量','新变量')]:
            self.assertTrue(issues(before,after,declaration))

    def test_source_and_inventory_drift_reject(self):
        source='outside_ruin 20'
        declaration=inventory(source,numbers=('20',))
        declaration['source_text_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'literal_source_changed'):issues(source,source,declaration)
        declaration=inventory(source);declaration['literal_counts']['outside_ruin']=2
        with self.assertRaisesRegex(ValueError,'literal_count'):issues(source,source,declaration)


if __name__=='__main__':unittest.main()
