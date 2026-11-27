import contextlib
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


TOOLBOX = Path(__file__).resolve().parents[2] / "toolbox.py"
spec = importlib.util.spec_from_file_location("copy_polish", Path(__file__).with_name("run.py"))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def request(profile, draft, **extra):
    return {"profile": profile, "items": [{"id": "host-entry", "source_revision": "v1", "text": draft, **extra}]}


def response(rows, finish="STOP"):
    return {
        "candidates": [{"finishReason": finish, "content": {"parts": [{"text": json.dumps({"items": rows})}]}}],
        "modelVersion": "gemini-fixture-model",
        "usageMetadata": {"totalTokenCount": 27, "unrelated": "not for receipts"},
        "responseId": "do-not-echo",
    }


def approve(row):
    return {"id": row["id"], "review_key": row["review_key"], "decision": "approve", "reviewer": "host-agent"}


def report_request():
    return {"profile": "research", "context": "给设计者解释先后关系。", "document": {
        "format": "research-report-edit-v1", "source_revision": "study-v1",
        "source": {"schema": 1, "title": "研究全文", "toc_layout": {
            "type": "grouped", "groups": [{"id": "part", "title": "操作与后果", "sections": ["first", "last"]}]},
            "sections": [
                {"id": "first", "title": "先看案例", "references": ["S1"], "blocks": [
                    {"type": "p", "text": "先运行 20 次。"}, {"type": "p", "text": "观察「复位」后的结果。"},
                    {"type": "image", "src": "fixed.png", "alt": "原图", "caption": "查看图例。"},
                    {"type": "p", "text": "回到入口，复核 5 次。"},
                    {"type": "table", "headers": ["措施"], "rows": [["复位"]]},
                    {"type": "p", "text": "原结论仍适用。"}]},
                {"id": "last", "title": "结尾标题", "blocks": [{"type": "p", "text": "只在该条件下成立。"}]},
            ], "sources": {"S1": {"label": "对照来源", "url": "https://example.test/S1"}}},
        "surfaces": {"control": {"kind": "interface", "source_revision": "ui-v1", "text": "播放"}},
        "presentation": {"revision": "ui-v1", "anchors": [
            {"id": "player", "section": "first", "before": 4, "kind": "interactive",
             "surfaces": ["control"], "replaces_table": True}]},
        "protect": {"/sections/0/blocks/0/text": ["运行"]},
    }}


def response_object(body):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": json.dumps(body, ensure_ascii=False)}
    ]}}]}


def report_fixture(workflow, request, edits=None, omit_section=None, moves=None):
    wire = json.loads(tool.report_payload(workflow, request)["contents"][0]["parts"][0]["text"])
    if omit_section:
        wire["sections"] = [part for part in wire["sections"] if part["section"] != omit_section]
    edits = edits or {}
    moves = moves or {}

    def rows(value):
        if isinstance(value, list):
            if len(value) >= 3 and isinstance(value[0], str) and value[0].isdecimal():
                ident, role, text = value[:3]
                result = {"id": ident, "text": edits.get(text, text)}
                if role in ("p", "note"):
                    result["reason"] = "按阅读次序交代操作和结果。"
                if text in moves:
                    result["moves_from"] = moves[text]
                yield result
            else:
                for item in value:
                    yield from rows(item)
        if isinstance(value, dict):
            for child in value.values():
                yield from rows(child)

    return response(list(rows(wire)))


class ReportEditorTests(unittest.TestCase):
    workflow = "game-research"

    def candidate(self, source, edits=None, omit_section=None):
        return tool.candidate_receipt(self.workflow, source,
                                      lambda _: report_fixture(self.workflow, source, edits, omit_section), "fixture")

    def check(self, source, candidate):
        reviews = [approve(row) for row in candidate["items"]]
        reviews.append(approve({"id": "/report-review", "review_key": candidate["report_review_key"]}))
        return tool.adoption_check(self.workflow, source, candidate, reviews)

    def compact_fixture(self, source, edit=False):
        items = tool.prepare_request(source, self.workflow)[2]
        ids = [str(i) for i in range(1, len(items) + 1)]
        if not edit:
            return {"items": [], "retained_ids": ids}
        index = next(i for i, item in enumerate(items) if item["role"] == "p")
        row = items[index]
        changed = row["text"].replace("先运行 20 次。", "第一步是运行 20 次。")
        self.assertNotEqual(changed, row["text"])
        key = ids.pop(index)
        return {"items": [{"id": key, "text": changed, "reason": "在起句交代先做的动作。"}],
                "retained_ids": ids}

    def test_compact_report_explicit_retention_and_dual_reviews(self):
        source = report_request()
        for edit in (False, True):
            with self.subTest(edit=edit):
                fixture = self.compact_fixture(source, edit)
                receipt = tool.candidate_receipt(self.workflow, source, lambda _: response_object(fixture), "fixture")
                self.assertEqual(receipt["status"], "pass")
                items = tool.prepare_request(source, self.workflow)[2]
                for i, (row, original) in enumerate(zip(receipt["items"], items), 1):
                    if str(i) in fixture["retained_ids"]:
                        self.assertEqual(row["disposition"], "retained")
                        self.assertEqual(row["text"], original["text"])
                        self.assertEqual(row["status"], "pending_review")
                decisions = [approve(row) for row in receipt["items"]]
                rejected = tool.adoption_check(self.workflow, source, receipt, decisions)
                self.assertEqual(rejected["report_review"], "report_review_missing_or_stale")
                self.assertNotIn("revised_source", rejected)
                decisions.append(approve({"id": "/report-review", "review_key": receipt["report_review_key"]}))
                retained = next(row["id"] for row in receipt["items"] if row["disposition"] == "retained")
                rejected = tool.adoption_check(self.workflow, source, receipt,
                                               [row for row in decisions if row["id"] != retained])
                self.assertNotIn("revised_source", rejected)
                self.assertEqual(self.check(source, receipt)["status"], "pass")

    def test_explicit_source_retention_binds_original_candidate_and_whole_review(self):
        source=report_request();fixture=self.compact_fixture(source,True)
        receipt=tool.candidate_receipt(self.workflow,source,lambda _:response_object(fixture),'fixture')
        before=tool.json_bytes(receipt)
        revised=next(row for row in receipt['items'] if row['disposition']=='revised')
        originals={i['id']:i for i in tool.prepare_request(source,self.workflow)[2]}
        reviews=[approve(row) for row in receipt['items']]
        chosen=next(r for r in reviews if r['id']==revised['id'])
        chosen.update(decision='retain_source',source_key=revised['source_key'],reason='原候选改变适用范围，保留本次送审原文。')
        reviews.append(approve({'id':'/report-review','review_key':receipt['report_review_key']}))
        missing=tool.adoption_check(self.workflow,source,receipt,reviews)
        self.assertEqual(missing['status'],'failed');self.assertNotIn('revised_source',missing)
        reviews[-1]['retained_source_review_key']=tool.retained_source_review_key(self.workflow,source,receipt,reviews)
        adopted=tool.adoption_check(self.workflow,source,receipt,reviews)
        self.assertEqual(adopted['status'],'pass');self.assertIn('revised_source',adopted)
        row=next(r for r in adopted['items'] if r['id']==revised['id'])
        self.assertEqual(row['text'],originals[revised['id']]['text'])
        self.assertEqual(row['candidate_review_key'],revised['review_key'])
        self.assertEqual(row['decision'],'retain_source')
        self.assertEqual(tool.json_bytes(receipt),before)
        for field in ('source_key','review_key','reason'):
            wrong=copy.deepcopy(reviews);target=next(r for r in wrong if r['id']==revised['id']);target.pop(field)
            self.assertEqual(tool.adoption_check(self.workflow,source,receipt,wrong)['status'],'failed')
        wrong=copy.deepcopy(reviews);chosen=next(r for r in wrong if r['id']==revised['id']);chosen['reason']+='变更'
        self.assertEqual(tool.adoption_check(self.workflow,source,receipt,wrong)['status'],'failed')
        changed=copy.deepcopy(source);changed['document']['source_revision']+='new'
        with self.assertRaises(tool.Failed):tool.adoption_check(self.workflow,changed,receipt,reviews)
        for fault in ('timeout','missing_item','protection_failed'):
            bad=copy.deepcopy(receipt);bad['status']='failed';bad['items'][0]['status']=fault
            with self.assertRaises(tool.Failed):tool.adoption_check(self.workflow,source,bad,reviews)

    def test_compact_report_rejects_gaps_overlap_extras_and_invalid_assignments(self):
        source = report_request()
        fixture = self.compact_fixture(source, True)
        ids = fixture["retained_ids"]
        edits = fixture["items"]
        cases = [
            (dict(fixture, retained_ids=ids[1:]), "report_slot_coverage", {"missing": 1}),
            (dict(fixture, retained_ids=ids + [edits[0]["id"]]), "report_slot_coverage", {"duplicates": 1}),
            (dict(fixture, retained_ids=ids + [ids[0]]), "report_slot_coverage", {"duplicates": 1}),
            (dict(fixture, retained_ids=ids + ["999"]), "report_slot_coverage", {"extra": 1}),
            (dict(fixture, items=edits * 2), "report_slot_coverage", {"duplicates": 1}),
            (dict(fixture, retained_ids=ids + [3]), "invalid_report_slot_assignments", {}),
        ]
        for response_body, reason, details in cases:
            with self.subTest(reason=reason, details=details):
                failed = tool.candidate_receipt(self.workflow, source, lambda _: response_object(response_body), "fixture")
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["candidate_structure_error"]["reason"], reason)
                for key, value in details.items():
                    self.assertEqual(failed["candidate_structure_error"][key], value)
                self.assertNotIn("report_review_key", failed)
                with self.assertRaisesRegex(tool.Failed, "document_coverage_mismatch"):
                    tool.adoption_check(self.workflow, source, failed, [])

    def test_compact_output_is_restricted_to_report_mode(self):
        body = response_object({"items": [], "retained_ids": ["1"]})
        receipt = tool.candidate_receipt("personal-site-copy", request("website", "原介绍。"),
                                         lambda _: body, "fixture")
        self.assertEqual(receipt["candidate_structure_error"]["reason"], "unexpected_root_fields")

    def test_whole_report_allows_merge_split_and_reorder_with_fixed_presentation(self):
        source = report_request()
        payload = tool.report_payload(self.workflow, source)
        prompt = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("合并、拆分或调整段落", prompt)
        self.assertNotIn("不要省略、拆分、合并或重排段落", prompt)
        wire = json.loads(payload["contents"][0]["parts"][0]["text"])
        self.assertEqual(list(wire["contents"]["toc_layout"]["groups"][0]["sections"]), ["first", "last"])
        self.assertEqual([part["section"] for part in wire["sections"]], ["first", "last"])
        self.assertEqual(wire["sections"][1]["blocks"][0][2], "只在该条件下成立。")
        blocks = wire["sections"][0]["blocks"]
        self.assertEqual(blocks[1]["kind"], "image")
        self.assertEqual(blocks[3]["anchor"], "player")
        self.assertEqual(blocks[3]["surfaces"][0][2], "播放")
        self.assertTrue(blocks[4]["replaced"])
        self.assertIsNone(blocks[4]["labels"][0][0])
        receipt = self.candidate(source, {"先运行 20 次。\n\n观察「复位」后的结果。": "要观察「复位」后的结果，先运行 20 次。",
                                          "回到入口，复核 5 次。": "先回到入口。\n\n再复核 5 次。"})
        result = self.check(source, receipt)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["document"]["scope"], "whole_report")
        self.assertEqual(result["block_map"]["first"], {"2": 1, "4": 4})
        self.assertEqual(result["prose_map"]["/sections/0/prose/0:2"],
                         {"section": "first", "original": [0, 2], "revised": [0, 1]})
        rebuilt = result["revised_source"]["sections"][0]["blocks"]
        self.assertEqual([block["type"] for block in rebuilt], ["p", "image", "p", "p", "table", "p"])
        self.assertEqual(rebuilt[1], source["document"]["source"]["sections"][0]["blocks"][2])
        self.assertEqual(result["revised_presentation"], source["document"]["presentation"])
        self.assertEqual(result["revised_source"]["sources"], source["document"]["source"]["sources"])

    def test_rejects_missing_chapter_aggregate_fact_changes_stale_anchor_and_missing_review(self):
        source = report_request()
        partial = self.candidate(source, omit_section="last")
        self.assertEqual(partial["status"], "partial")
        with self.assertRaisesRegex(tool.Failed, "document_coverage_mismatch"):
            tool.adoption_check(self.workflow, source, partial, [])
        invalid = self.candidate(source, {"回到入口，复核 5 次。": "回到入口，复核 6 次。"})
        self.assertIn("protection_failed", [row["status"] for row in invalid["items"]])
        good = self.candidate(source, {"回到入口，复核 5 次。": "回到入口。\n\n复核 5 次。"})
        self.assertEqual(self.check(source, good)["revised_presentation"]["anchors"][0]["before"], 5)
        moved = copy.deepcopy(source)
        moved["document"]["presentation"]["anchors"][0].update(before=5)
        del moved["document"]["presentation"]["anchors"][0]["replaces_table"]
        with self.assertRaisesRegex(tool.Failed, "document_source_changed_or_scope_mismatched"):
            tool.adoption_check(self.workflow, moved, good, [])
        lacking = tool.adoption_check(self.workflow, source, good, [approve(row) for row in good["items"][1:]])
        self.assertEqual(lacking["status"], "failed")
        self.assertNotIn("revised_source", lacking)

    def test_whole_report_moves_an_explanation_with_aggregate_protection_and_global_review(self):
        source = report_request()
        source["document"]["source"]["sections"][1]["blocks"][0]["text"] = "只在 2 人参与时成立。"
        wire = json.loads(tool.report_payload(self.workflow, source)["contents"][0]["parts"][0]["text"])
        old_front = "先运行 20 次。\n\n观察「复位」后的结果。"
        old_end = "只在 2 人参与时成立。"
        edits = {old_front: "只在 2 人参与时成立。\n\n" + old_front, old_end: "以上是本节的结论。"}
        source_slot = wire["sections"][1]["blocks"][0][0]
        without_map = self.candidate(source, edits)
        self.assertEqual(without_map["status"], "partial")
        receipt = tool.candidate_receipt(self.workflow, source, lambda _: report_fixture(
            self.workflow, source, edits, moves={old_front: [source_slot]}
        ), "fixture")
        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(next(row for row in receipt["items"] if row.get("moves_from"))["moves_from"],
                         ["/sections/1/prose/0:1"])
        without_global = tool.adoption_check(self.workflow, source, receipt, [approve(row) for row in receipt["items"]])
        self.assertEqual(without_global["report_review"], "report_review_missing_or_stale")
        self.assertNotIn("revised_source", without_global)
        adopted = self.check(source, receipt)
        self.assertEqual(adopted["revised_source"]["sections"][0]["blocks"][0]["text"], old_end)
        self.assertEqual(adopted["revised_source"]["sections"][1]["blocks"][0]["text"], edits[old_end])
        self.assertEqual(adopted["report_review"], "approved")

    def test_quote_prompt_keeps_strict_protection_and_reuses_reviewed_chapter(self):
        source = report_request()
        source['document']['source']['sections'][0]['blocks'][0]['text'] = '先分清“离得最近的按钮”和“应该先移走的对象”。'
        source['document']['protect'] = {}  # This fixture replaces the paragraph containing the old explicit literal.
        bad = self.candidate(source, {'先分清“离得最近的按钮”和“应该先移走的对象”。\n\n观察「复位」后的结果。':
                                      '先分清“离得近”和“想先移走谁”。\n\n观察「复位」后的结果。'})
        self.assertEqual(bad['status'], 'partial')
        self.assertIn('protection_failed', [row['status'] for row in bad['items']])
        with self.assertRaisesRegex(tool.Failed, 'document_coverage_mismatch'):
            tool.adoption_check(self.workflow, source, bad, [])
        instruction = '原引号及其中的文字逐字保留，包括作者自写的说法，不改不删；不顺时可保留整段。'
        self.assertIn(instruction, tool.report_payload(self.workflow, source)['systemInstruction']['parts'][0]['text'])
        doc = source['document']
        doc['brief'] = {'revision': tool.report_revision(doc), 'direction': '从动作引出后果。',
                        'sections': {'first': '先交代操作。', 'last': '接续适用条件。'}}
        doc.update(sections=['last'], include_shared=False)
        old_candidate = tool.candidate_receipt(self.workflow, source,
            lambda _: report_fixture(self.workflow, source), "fixture", editor_version="1.0.0")
        old_second = self.check(source, old_candidate)
        old_second_identity = old_second['document']['document_key']
        # Removing a clause from the new default makes an unknown mixed prompt,
        # not a historical snapshot. Keep rejecting that invented identity.
        with patch.object(tool.report, 'EDITOR', tool.report.EDITOR.replace(instruction, '')):
            mixed = self.candidate(source)
            with self.assertRaisesRegex(tool.Failed, 'document_source_changed_or_scope_mismatched'):
                self.check(source, mixed)
        doc.update(sections=['first'], include_shared=True)
        new_first = self.check(source, self.candidate(source))
        self.assertNotEqual(new_first['document']['document_key'], old_second_identity)
        self.assertEqual(new_first['document']['brief_key'], old_second['document']['brief_key'])
        self.assertEqual(tool.report_coverage(doc, [new_first, old_second])['status'], 'pass')
        # Existing candidate identities stay immutable when the system prompt changes.
        doc.update(sections=['last'], include_shared=False)
        self.assertNotEqual(tool.prepare_request(source, self.workflow)[3]['document_key'], old_second_identity)

    def test_chapters_require_current_full_brief_and_keep_unselected_chapter(self):
        source = report_request()
        doc = source["document"]
        revision = tool.report_revision(doc)
        doc["sections"] = ["first"]
        with self.assertRaisesRegex(tool.Failed, "invalid_report_full_brief"):
            tool.report_payload(self.workflow, source)
        doc["brief"] = {"revision": revision, "direction": "从动作引出后果。",
                        "sections": {"first": "先交代操作。", "last": "接续说明适用条件。"}}
        wire = json.loads(tool.report_payload(self.workflow, source)["contents"][0]["parts"][0]["text"])
        self.assertEqual(wire["sections"][1]["editorial_context"], "接续说明适用条件。")
        self.assertNotIn("blocks", wire["sections"][1])
        checked = self.check(source, self.candidate(source))
        self.assertEqual(checked["document"]["scope"], "chapters")
        self.assertEqual(checked["document"]["sections"], ["first"])
        self.assertEqual(checked["revised_source"]["sections"][1], doc["source"]["sections"][1])
        with self.assertRaisesRegex(tool.Failed, "report_batch_coverage_mismatch"):
            tool.report_coverage(doc, [checked])
        doc["include_shared"] = True
        checked = self.check(source, self.candidate(source))
        doc["sections"] = ["last"]
        doc["include_shared"] = False
        second = self.check(source, self.candidate(source))
        self.assertEqual(tool.report_coverage(doc, [checked, second])["sections"], ["first", "last"])
        doc["source"]["sections"][1]["title"] += "已修改"
        with self.assertRaisesRegex(tool.Failed, "report_brief_source_changed"):
            tool.report_payload(self.workflow, source)


def knowledge_request(profile="raw"):
    return {
        "profile": profile, "context": "说明操作目的和适用条件。",
        "document": {
            "format": "knowledge-sections-v1", "kind": "source_digest" if profile == "raw" else "wiki",
            "source_revision": "frozen-draft-10",
            "source": {"opening": "来源说明和导读。", "sections": [
                {"id": "operation", "heading": "操作", "source_locator": "§2",
                 "blocks": [
                     {"id": "operation.body", "role": "prose",
                      "text": "保留演练状态。\n\n这一规则适用于 2 次演练。", "protect": ["演练状态"]},
                     {"id": "operation.quote", "role": "readonly", "text": "> 原话留在原位。"},
                 ]},
                {"id": "limitations", "heading": "限制", "source_locator": "§4",
                 "blocks": [{"id": "limitations.body", "role": "prose", "text": "只处理同一份资料。"}]},
            ]},
            "brief": {"direction": "先讲操作，接着解释限制。",
                      "sections": {"operation": "交代操作目的。", "limitations": "承接并限制适用范围。"}},
        },
    }


class KnowledgeDocumentTests(unittest.TestCase):
    def candidate(self, source, body):
        return tool.candidate_receipt("knowledge", source, lambda _: response_object(body), "fixture")

    def approved(self, source, candidate):
        reviews = [approve(row) for row in candidate["items"]]
        reviews.append(approve({"id": "/report-review", "review_key": candidate["report_review_key"]}))
        return tool.adoption_check("knowledge", source, candidate, reviews)

    def test_knowledge_profiles_keep_prose_mapping_and_readonly_context(self):
        for profile in ("raw", "wiki"):
            with self.subTest(profile=profile):
                source = knowledge_request(profile)
                payload = tool.report_payload("knowledge", source)
                wire = json.loads(payload["contents"][0]["parts"][0]["text"])
                first = wire["sections"][0]
                self.assertEqual(first["source_locator"], "§2")
                self.assertEqual(first["blocks"][1], [None, "readonly", "> 原话留在原位。"])
                self.assertEqual(wire["sections"][1]["editorial_context"], "承接并限制适用范围。")
                revised = "在 2 次演练中，保留演练状态。"
                body = {"items": [{"id": "1", "text": revised, "reason": "把条件和操作放到一句。"}],
                        "retained_ids": ["2"]}
                receipt = self.candidate(source, body)
                self.assertEqual(receipt["status"], "pass")
                without_overall = tool.adoption_check("knowledge", source, receipt,
                                                       [approve(row) for row in receipt["items"]])
                self.assertNotIn("revised_blocks", without_overall)
                accepted = self.approved(source, receipt)
                self.assertEqual(accepted["document"]["scope"], "whole_document")
                self.assertEqual(accepted["revised_blocks"],
                                 {"operation.body": revised, "limitations.body": "只处理同一份资料。"})

    def test_knowledge_format_rejects_wrong_kind_write_targets_and_new_structure(self):
        source = knowledge_request()
        incorrect = copy.deepcopy(source)
        incorrect["document"]["kind"] = "own_note"
        with self.assertRaisesRegex(tool.Failed, "invalid_knowledge_document_kind"):
            self.candidate(incorrect, {})
        for extra in ("operation.quote", "operation.body", "3"):
            receipt = self.candidate(source, {"items": [], "retained_ids": ["1", "2", extra]})
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["candidate_structure_error"]["extra"], 1)
        for text, steps in (
            ("# 演练状态\n\n这一规则适用于 2 次演练。", {}),
            ("保留演练状态。这一规则适用于 3 次演练。", {}),
            ("在 2 次演练中，保留演练状态。", {"moves_from": ["2"]}),
        ):
            with self.subTest(text=text, steps=steps):
                body = {"items": [dict(id="1", text=text, reason="解释操作。", **steps)], "retained_ids": ["2"]}
                receipt = self.candidate(source, body)
                self.assertEqual(receipt["status"], "partial")
                self.assertNotIn("report_review_key", receipt)

    def test_knowledge_identity_binds_readonly_policy_context_and_brief(self):
        source = knowledge_request()
        receipt = self.candidate(source, {"items": [], "retained_ids": ["1", "2"]})
        for variant in ("source_revision", "readonly", "locator", "protect", "context", "brief"):
            with self.subTest(variant=variant):
                changed = copy.deepcopy(source)
                doc = changed["document"]
                first = doc["source"]["sections"][0]
                if variant == "source_revision":
                    doc["source_revision"] += "-changed"
                elif variant == "readonly":
                    first["blocks"][1]["text"] = "> 原来源有修订。"
                elif variant == "locator":
                    first["source_locator"] = "§3"
                elif variant == "protect":
                    first["blocks"][0]["protect"].append("规则")
                elif variant == "context":
                    changed["context"] += "保留原语气。"
                else:
                    doc["brief"]["direction"] += "增加对照解释。"
                with self.assertRaisesRegex(tool.Failed, "document_source_changed_or_scope_mismatched"):
                    self.approved(changed, receipt)

    def test_knowledge_merge_rejects_post_review_changes_for_raw_and_wiki(self):
        for profile in ("raw", "wiki"):
            source = knowledge_request(profile)
            batches = []
            for section in ("operation", "limitations"):
                partial = copy.deepcopy(source)
                partial["document"]["sections"] = [section]
                receipt = self.candidate(partial, {"items": [], "retained_ids": ["1"]})
                batches.append(self.approved(partial, receipt))
            baseline = tool.knowledge_coverage(source, batches)
            self.assertEqual(baseline["status"], "pass")
            block_id = "operation.body"
            for variant in ("mapping", "row_text", "both_texts", "missing_row", "extra_row", "duplicate_row",
                            "nonready", "source_key", "reason", "review_key", "global_key", "missing_global",
                            "profile", "whole_review"):
                with self.subTest(profile=profile, variant=variant):
                    changed = copy.deepcopy(batches)
                    batch = changed[0]
                    row = batch["items"][0]
                    if variant == "mapping":
                        batch["revised_blocks"][block_id] = "未经复核，结论变成必然成立。"
                    elif variant == "row_text":
                        row["text"] += "补充说明。"
                    elif variant == "both_texts":
                        row["text"] += "补充说明。"
                        batch["revised_blocks"][block_id] = row["text"]
                    elif variant == "missing_row":
                        batch["items"] = []
                    elif variant == "extra_row":
                        batch["items"].append(dict(row, id="unknown.body"))
                    elif variant == "duplicate_row":
                        batch["items"].append(copy.deepcopy(row))
                    elif variant == "nonready":
                        row["status"] = "withheld"
                    elif variant == "source_key":
                        row["current_source_key"] = "stale"
                    elif variant == "reason":
                        row["reason"] += "不同的审阅依据。"
                    elif variant == "review_key":
                        row["review_key"] = "stale"
                    elif variant == "global_key":
                        batch["report_review_key"] = "stale"
                    elif variant == "missing_global":
                        del batch["report_review_key"]
                    elif variant == "profile":
                        batch["profile"] = "wiki" if profile == "raw" else "raw"
                    else:
                        batch["report_review"] = "rejected"
                    with self.assertRaisesRegex(tool.Failed, "knowledge_batch_(review|scope)_mismatch"):
                        tool.knowledge_coverage(source, changed)

    def test_knowledge_chapters_cover_frozen_context_once_and_in_order(self):
        source = knowledge_request()
        approved = []
        for section in ("operation", "limitations"):
            partial = copy.deepcopy(source)
            partial["document"]["sections"] = [section]
            payload = tool.report_payload("knowledge", partial)
            wire = json.loads(payload["contents"][0]["parts"][0]["text"])
            other = next(row for row in wire["sections"] if row["section"] != section)
            self.assertIn("editorial_context", other)
            self.assertNotIn("blocks", other)
            candidate = self.candidate(partial, {"items": [], "retained_ids": ["1"]})
            approved.append(self.approved(partial, candidate))
        for bad in (approved[:1], approved[::-1], approved + approved[:1]):
            with self.assertRaisesRegex(tool.Failed, "knowledge_batch_coverage_mismatch"):
                tool.knowledge_coverage(source, bad)
        changed = copy.deepcopy(source)
        changed["document"]["brief"]["direction"] += "比较前后。"
        with self.assertRaisesRegex(tool.Failed, "knowledge_batch_scope_mismatch"):
            tool.knowledge_coverage(changed, approved)
        combined = tool.knowledge_coverage(source, approved)
        self.assertEqual(combined["sections"], ["operation", "limitations"])
        self.assertEqual(set(combined["revised_blocks"]), {"operation.body", "limitations.body"})


class CopyPolishTests(unittest.TestCase):
    def candidate(self, workflow, source, *rows):
        return tool.candidate_receipt(workflow, source, lambda payload: response(rows), "fixture")

    def test_host_profiles_use_one_request_and_keep_local_identity(self):
        cases = [
            ("personal-site-copy", request("website", "由我完成，并且仍是预览版。"), "由我完成，目前是预览版。"),
            ("game-research", request("research", "根据 [S1]，只在局面 A 验证过。", protect=["局面 A"]),
             "据 [S1]，验证范围仅限局面 A。"),
            ("knowledge", request("raw", "这是我对 2 项结果的摘要。", kind="own_summary"), "我在此概括 2 项结果。"),
            ("knowledge", request("wiki", "---\nowner: private-identity\n---\n## 概述 {#overview}\n可以看 [来源](https://example.test/x)。"),
             "## 概述 {#overview}\n参见 [来源](https://example.test/x)。"),
            ("game-development", request("game", "[b]{player}[/b] 可领取 %d 枚金币。"), "[b]{player}[/b] 能领 %d 枚金币。"),
        ]
        for workflow, source, revision in cases:
            with self.subTest(workflow=workflow, profile=source["profile"]):
                calls = []
                def fake(payload):
                    calls.append(payload)
                    return response([{"id": "1", "text": revision}])
                receipt = tool.candidate_receipt(workflow, source, fake, "fixture")
                self.assertEqual(len(calls), 1)
                wire = json.dumps(calls, ensure_ascii=False)
                for private_value in ("host-entry", "private-identity", "source_revision"):
                    self.assertNotIn(private_value, wire)
                self.assertEqual(receipt["usage"], {"totalTokenCount": 27})
                self.assertNotIn("do-not-echo", str(receipt))
                row = receipt["items"][0]
                self.assertEqual(row["status"], "pending_review")
                if source["profile"] == "wiki":
                    self.assertTrue(row["text"].startswith("---\nowner: private-identity\n---\n"))
                checked = tool.adoption_check(workflow, source, receipt, [approve(row)])
                self.assertEqual(checked["items"][0]["text"], row["text"])

    def test_page_edit_uses_full_context_and_binds_review_to_the_whole_page(self):
        source = request("website", "[[F001]] 我的 2 款作品。", protect=["我的"])
        source.update(edit_mode="page", context="首页先交代主线，详卡继续解释过程。")
        source["items"].append({"id": "card", "source_revision": "site-v1", "text": "[[F002]] 这里展开过程。"})
        revisions = [{"id": "1", "text": "[[F001]] 从这 2 款作品，可以看到我的设计方向。"},
                     {"id": "2", "text": "[[F002]] 这里展开过程。"}]

        def fixture(payload):
            prompt = payload["systemInstruction"]["parts"][0]["text"]
            self.assertIn("跨区重复和前后衔接", prompt)
            self.assertIn("可重写", prompt)
            self.assertNotIn("允许轻微措辞", prompt)
            wire = json.loads(payload["contents"][0]["parts"][0]["text"])
            self.assertEqual(wire["context"], source["context"])
            self.assertEqual([item["id"] for item in wire["items"]], ["1", "2"])
            self.assertNotIn("site-v1", str(wire))
            return response(revisions)

        receipt = tool.candidate_receipt("personal-site-copy", source, fixture, "fixture")
        reviews = [approve(row) for row in receipt["items"]]
        checked = tool.adoption_check("personal-site-copy", source, receipt, reviews)
        self.assertEqual(checked["status"], "pass")
        self.assertEqual(checked["items"][0]["text"], revisions[0]["text"])
        for change in ("other_field", "context", "order", "mode"):
            with self.subTest(change=change):
                current = copy.deepcopy(source)
                if change == "other_field":
                    current["items"][1]["text"] = "[[F002]] 这里展开新的过程。"
                elif change == "context":
                    current["context"] += " 还需解释取舍。"
                elif change == "order":
                    current["items"].reverse()
                else:
                    del current["edit_mode"]
                with self.assertRaisesRegex(tool.Failed, "page_source_changed_or_scope_mismatched"):
                    tool.adoption_check("personal-site-copy", current, receipt, reviews)

    def test_page_edit_rejects_shifted_or_empty_display_fields_and_partial_receipts(self):
        source = request("website", "[[F001]] 仍是预览版。\n[[F002]] 展示 2 张图。", protect=["预览版"])
        source.update(edit_mode="page", context="首处是状态，末处是图片说明。")
        cases = [
            "[[F001]] 这是说明。\n[[F002]] 预览版展示 2 张图。",
            "[[F001]] 仍是预览版。 [[F002]] 展示 2 张图。",
            "[[F001]] 仍是预览版。\n[[F002]] ",
        ]
        for text in cases:
            with self.subTest(text=text):
                receipt = self.candidate("personal-site-copy", source, {"id": "1", "text": text})
                self.assertEqual(receipt["items"][0]["status"], "protection_failed")
                with self.assertRaisesRegex(tool.Failed, "page_coverage_mismatch"):
                    tool.adoption_check("personal-site-copy", source, receipt, [])
        missing = self.candidate("personal-site-copy", source, {"id": "2", "text": "多余的条目。"})
        self.assertEqual(missing["items"][0]["status"], "missing_item")
        with self.assertRaisesRegex(tool.Failed, "page_coverage_mismatch"):
            tool.adoption_check("personal-site-copy", source, missing, [])

    def test_page_edit_rejects_other_workflows_and_requests_without_page_context(self):
        source = request("research", "当前版本仍是草稿。")
        source.update(edit_mode="page", context="这不是网站页面。")
        with self.assertRaisesRegex(tool.Failed, "invalid_edit_mode"):
            tool.candidate_receipt("game-research", source, self.fail, "fixture")
        source.update(profile="website", context="  ")
        with self.assertRaisesRegex(tool.Failed, "invalid_edit_mode"):
            tool.candidate_receipt("personal-site-copy", source, self.fail, "fixture")

    def test_raw_excerpt_and_bad_wiki_header_never_reach_transport(self):
        for source, reason in [
            (request("raw", "原文摘录", kind="excerpt"), "raw_allows_own_summary_or_note_only"),
            (request("wiki", "---\nprivate: value\n无结束标记"), "unclosed_front_matter"),
        ]:
            with self.assertRaisesRegex(tool.Failed, reason):
                tool.candidate_receipt("knowledge", source, self.fail, "fixture")

    def test_mixed_batch_preserves_good_item_and_detects_duplicate_and_missing(self):
        source = request("game", "可领取 2 枚。")
        source["items"] += [
            {"id": "bad", "source_revision": "1", "text": "可领取 5 枚。"},
            {"id": "duplicate", "source_revision": "1", "text": "确认。"},
            {"id": "missing", "source_revision": "1", "text": "取消。"},
        ]
        receipt = self.candidate("game-development", source,
                                 {"id": "1", "text": "能领 2 枚。"}, {"id": "2", "text": "可领取 6 枚。"},
                                 {"id": "3", "text": "确认"}, {"id": "3", "text": "接受"},
                                 {"id": "99", "text": "忽略此条"})
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["unexpected_output_rows"], 1)
        self.assertEqual([row["status"] for row in receipt["items"]],
                         ["pending_review", "protection_failed", "duplicate_item", "missing_item"])
        result = tool.adoption_check("game-development", source, receipt, [approve(receipt["items"][0])])
        self.assertEqual([row.get("text") for row in result["items"]], ["能领 2 枚。", None, None, None])

    def test_review_and_source_concurrency_are_independent(self):
        source = request("website", "本作仍在制作中。")
        receipt = self.candidate("personal-site-copy", source, {"id": "1", "text": "本作仍在开发。"})
        approved = approve(receipt["items"][0])
        changed = copy.deepcopy(source)
        changed["items"][0]["source_revision"] = "v2"
        rejected = dict(approved, decision="reject")
        for current, reviews, expected in [
            (source, [], "review_missing_or_stale"),
            (source, [rejected], "review_not_approved"),
            (changed, [approved], "source_changed"),
        ]:
            row = tool.adoption_check("personal-site-copy", current, receipt, reviews)["items"][0]
            self.assertEqual(row["status"], expected)
            self.assertNotIn("text", row)
        changed["items"][0]["source_revision"] = "v1"
        changed["items"][0]["text"] = "本作已发布。"
        self.assertEqual(tool.adoption_check("personal-site-copy", changed, receipt, [approved])
                         ["items"][0]["status"], "source_changed")
        receipt["items"][0]["text"] = "替换候选。"
        self.assertEqual(tool.adoption_check("personal-site-copy", source, receipt, [approved])
                         ["items"][0]["status"], "review_missing_or_stale")

    def test_context_is_bounded_and_slot_length_is_checked(self):
        source = request("game", "领取奖品", context="按钮，玩家已完成任务", max_chars=4)
        source["context"] = "教程供首次上线的玩家使用"
        def fake(payload):
            wire = json.loads(payload["contents"][0]["parts"][0]["text"])
            self.assertEqual(wire["context"], source["context"])
            self.assertEqual(wire["items"][0]["context"], "按钮，玩家已完成任务")
            self.assertEqual(wire["items"][0]["max_chars"], 4)
            return response([{"id": "1", "text": "领取你的奖品"}])
        rejected = tool.candidate_receipt("game-development", source, fake, "fixture")
        self.assertEqual(rejected["items"][0]["status"], "length_exceeded")
        receipt = self.candidate("game-development", source, {"id": "1", "text": "领奖"})
        current = dict(source, context="改为回流玩家")
        checked = tool.adoption_check("game-development", current, receipt, [approve(receipt["items"][0])])
        self.assertEqual(checked["items"][0]["status"], "source_changed")
        with self.assertRaisesRegex(tool.Failed, "invalid_context"):
            tool.candidate_receipt("game-development", dict(source, context="x" * 1001), self.fail, "fixture")

    def test_output_truncation_is_never_salvaged(self):
        source = request("website", "仍在制作。")
        result = tool.candidate_receipt(
            "personal-site-copy", source, lambda payload: response([{"id": "1", "text": "仍在开发。"}], "MAX_TOKENS"),
            "fixture",
        )
        self.assertEqual(result["items"][0]["status"], "output_truncated")
        self.assertNotIn("text", result["items"][0])

    def test_mocked_live_transport_is_encoded_single_call_and_failures_are_redacted(self):
        key = "secret-fixture-value"
        source = request("website", "仍在制作。")
        provider_result = response([{"id": "1", "text": "仍在开发。"}])
        for fault, expected in [(None, "pending_review"), (TimeoutError(key), "timeout"),
                                (b'{"candidate":', "invalid_or_truncated_response"),
                                (json.dumps({"echo": key}).encode(), "credential_in_response")]:
            with self.subTest(expected=expected), patch.dict(tool.os.environ, {tool.KEY_ENV: key}), \
                    patch.object(tool, "RELAYS", {"https://provider.example.test"}), \
                    patch.object(tool.urllib.request, "build_opener") as opener:
                open_request = opener.return_value.open
                if isinstance(fault, Exception):
                    open_request.side_effect = fault
                else:
                    raw = fault if fault is not None else json.dumps(provider_result).encode()
                    open_request.return_value = contextlib.nullcontext(io.BytesIO(raw))
                result = tool.candidate_receipt("personal-site-copy", source, lambda p: tool.generate(p, 4, relay="https://provider.example.test"), "live")
                self.assertEqual(result["items"][0]["status"], expected)
                self.assertNotIn(key, str(result))
                self.assertEqual(open_request.call_count, 1)
                sent = open_request.call_args.args[0]
                url = urlsplit(sent.full_url)
                self.assertEqual((url.scheme, url.netloc), ("https", "provider.example.test"))
                self.assertEqual(url.path, "/v1beta/models/" + tool.urllib.parse.quote(tool.MODEL,safe="") + ":generateContent")
                self.assertEqual(parse_qs(url.query), {"key": [key]})
                self.assertEqual(sent.get_method(), "POST")
                opener.assert_called_once()
                self.assertIsInstance(opener.call_args.args[0], tool.NoRedirect)
                self.assertNotIn(key.encode(), sent.data)
                self.assertEqual(open_request.call_args.kwargs, {"timeout": 4})

    def test_toolbox_offline_routes_and_unreviewed_cli_never_returns_ready_text(self):
        with tempfile.TemporaryDirectory() as path:
            path = Path(path)
            source, fixture, receipt = (path / name for name in ("source.json", "fixture.json", "receipt.json"))
            source.write_text(json.dumps(request("website", "still in development")), encoding="utf-8")
            fixture.write_text(json.dumps(response([{"id": "1", "text": "in development"}])), encoding="utf-8")
            home = path / 'external-tools-home'
            prepare_spec = importlib.util.spec_from_file_location('portable_home', TOOLBOX.parent / 'prepare_home.py')
            prepare = importlib.util.module_from_spec(prepare_spec); prepare_spec.loader.exec_module(prepare)
            prepare.prepare(home, TOOLBOX.parent)
            command = [sys.executable, "-X", "utf8", "-B", str(home / 'toolbox.py')]
            for workflow in tool.PROFILES:
                plan = subprocess.run(command + ["request", "--workflow", workflow, "--tool", "copy-polish",
                                                "--action", "candidate"], capture_output=True, check=True)
                self.assertEqual(json.loads(plan.stdout)["workflow"], workflow)
            run = command + ["run", "--workflow", "personal-site-copy", "--tool", "copy-polish"]
            drafted = subprocess.run(run + ["--action", "candidate", "--", "--request", str(source),
                                            "--response-fixture", str(fixture)], capture_output=True, check=True)
            receipt.write_bytes(drafted.stdout)
            check = subprocess.run(run + ["--action", "check", "--", "--request", str(source),
                                          "--receipt", str(receipt)], capture_output=True)
            self.assertEqual(check.returncode, 1, check.stderr)
            self.assertEqual(json.loads(check.stdout)["items"][0]["status"], "review_missing_or_stale")




class StudyDocumentTests(unittest.TestCase):
    workflow = "game-research"

    def setUp(self):
        self.source = {
            "schema": 1, "title": "任务报告原题", "subtitle": "先看一眼说明", "reader": "入门导读",
            "toc_layout": {"type": "grouped", "groups": [{"id": "private-group", "title": "目录原组名",
                            "sections": ["private-section"], "chapter": {"opening": "private-section", "closing": "private-section"}}]},
            "sources": {"private/reference": {"label": "阅读来源", "url": "https://example.test/private"}},
            "sections": [{
                "id": "private-section", "title": "小节原题", "subtitle": "小节原副题", "reader_goals": ["读者原目标"],
                "references": ["private/reference"],
                "blocks": [
                    {"type": "p", "text": "作者写道“保持原句”。确认 60 秒和 `{player}` 后开钟。"},
                    {"type": "table", "headers": ["第一章原表头"], "rows": [["原单元格"]], "widths": [1.0]},
                    {"type": "flow", "items": ["流程原标签"]},
                    {"type": "image", "src": "private/asset.png", "caption": "原图注", "alt": "原替代文字",
                     "markers": [{"x": 0.4, "y": 0.7, "label": "图内原标签"}]},
                    {"type": "links", "items": [["原链接显示文字", "private/reference"]]},
                    {"type": "note", "text": "截图内不可改原话"},
                ],
            }],
        }
        self.request = {"profile": "research", "document": {
            "format": "research-study-v1", "source_revision": "private-version", "source": self.source,
            "retain": {"/sections/0/blocks/5/text": "screenshot_text"},
            "surfaces": {
                "private-svg-node": {"kind": "svg", "source_revision": "svg-v1", "text": "SVG 原标签"},
                "private-draw-label": {"kind": "image", "source_revision": "draw-v1", "text": "图片原标签"},
                "private-button": {"kind": "interface", "source_revision": "reader-v1", "text": "按钮原文案"},
            },
        }}

    def run_candidate(self, edit):
        def transport(payload):
            items = json.loads(payload["contents"][0]["parts"][0]["text"])["items"]
            return response(edit(items))
        transport_mock = unittest.mock.Mock(side_effect=transport)
        receipt = tool.candidate_receipt(self.workflow, self.request, transport_mock, "fixture")
        transport_mock.assert_called_once()
        return receipt

    @staticmethod
    def all_items(items):
        return [{"id": row["id"], "text": row["text"].replace("原", "新").replace("新句", "原句")}
                for row in items]

    def test_all_display_fields_round_trip_and_unchanged_fields_require_review(self):
        def edit(items):
            sent = json.dumps(items, ensure_ascii=False)
            for locked in ("private-section", "private-group", "private/reference", "private-version",
                           "example.test", "private/asset.png", "截图内不可改原话", "private-button", "reader-v1"):
                self.assertNotIn(locked, sent)
            roles = {row["role"] for row in items}
            self.assertTrue({"contents group title", "section and contents title", "table header", "table cell",
                             "flow step label", "image marker label", "image caption", "image alt text",
                             "reader guide", "link display label", "authored SVG label", "authored image drawing label",
                             "report interface label"} <= roles)
            return self.all_items(items)
        receipt = self.run_candidate(edit)
        self.assertEqual(receipt["status"], "pass")
        self.assertIn("/sources/private~1reference/label", {row["id"] for row in receipt["items"]})
        reviews = [approve(row) for row in receipt["items"]]
        checked = tool.adoption_check(self.workflow, self.request, receipt, reviews)
        revised = checked["revised_source"]
        self.assertEqual(revised["toc_layout"]["groups"][0]["title"], "目录新组名")
        self.assertEqual(revised["toc_layout"]["groups"][0]["chapter"],
                         {"opening": "private-section", "closing": "private-section"})
        self.assertEqual(revised["sections"][0]["title"], "小节新题")
        self.assertEqual(checked["revised_surfaces"], {"private-svg-node": "SVG 新标签",
                                                       "private-draw-label": "图片新标签",
                                                       "private-button": "按钮新文案"})
        self.assertEqual(revised["sections"][0]["id"], "private-section")
        self.assertEqual(revised["sections"][0]["references"], ["private/reference"])
        blocks = revised["sections"][0]["blocks"]
        self.assertEqual(blocks[1], {"type": "table", "headers": ["第一章新表头"], "rows": [["新单元格"]], "widths": [1.0]})
        self.assertEqual(blocks[3]["src"], "private/asset.png")
        self.assertEqual(blocks[3]["alt"], "新替代文字")
        self.assertEqual(blocks[3]["markers"], [{"x": 0.4, "y": 0.7, "label": "图内新标签"}])
        self.assertEqual(blocks[4]["items"], [["新链接显示文字", "private/reference"]])
        self.assertEqual(blocks[5], self.source["sections"][0]["blocks"][5])
        rows = {row["id"]: row for row in checked["items"]}
        self.assertEqual(rows["/reader"]["disposition"], "retained")
        self.assertEqual(rows["/toc_layout/groups/0/title"]["disposition"], "revised")
        missing_review = [row for row in reviews if row["id"] != "/reader"]
        blocked = tool.adoption_check(self.workflow, self.request, receipt, missing_review)
        self.assertEqual(blocked["status"], "failed")
        self.assertNotIn("revised_source", blocked)
        self.assertTrue(all("text" not in row for row in blocked["items"]))

    def test_missing_duplicate_and_unexpected_fields_block_document_adoption(self):
        def at(items, role):
            return next(i for i, item in enumerate(items) if item["role"] == role)
        for fault in ("missing", "duplicate", "unexpected", "missing_interface"):
            with self.subTest(fault=fault):
                def edit(items):
                    rows = self.all_items(items)
                    if fault == "missing":
                        del rows[at(items, "contents group title")]
                    elif fault == "duplicate":
                        rows.append(rows[at(items, "table header")])
                    elif fault == "missing_interface":
                        del rows[at(items, "report interface label")]
                    else:
                        rows.append({"id": "extra", "text": "extra"})
                    return rows
                receipt = self.run_candidate(edit)
                self.assertEqual(receipt["status"], "partial")
                reviews = [approve(row) for row in receipt["items"] if row["status"] == "pending_review"]
                with self.assertRaisesRegex(tool.Failed, "document_coverage_mismatch"):
                    tool.adoption_check(self.workflow, self.request, receipt, reviews)

    def test_quote_number_variable_and_full_source_version_are_protected(self):
        for old, new in (("原句", "别句"), ("60", "90"), ("player", "actor")):
            with self.subTest(protected=old):
                receipt = self.run_candidate(lambda items: [dict(row, text=row["text"].replace(old, new))
                                             for row in self.all_items(items)])
                problem = next(row for row in receipt["items"] if row["id"] == "/sections/0/blocks/0/text")
                self.assertEqual(problem["status"], "protection_failed")
        receipt = self.run_candidate(self.all_items)
        reviews = [approve(row) for row in receipt["items"]]
        current = copy.deepcopy(self.request)
        current["document"]["source"]["sources"]["private/reference"]["url"] = "https://example.test/new-target"
        with self.assertRaisesRegex(tool.Failed, "document_source_changed_or_scope_mismatched"):
            tool.adoption_check(self.workflow, current, receipt, reviews)

    def test_knowledge_wiki_study_uses_the_same_title_contract(self):
        self.request["profile"] = "wiki"
        self.workflow = "knowledge"
        receipt = self.run_candidate(self.all_items)
        checked = tool.adoption_check(self.workflow, self.request, receipt, [approve(row) for row in receipt["items"]])
        self.assertEqual(checked["status"], "pass")
        self.assertEqual(checked["revised_source"]["title"], "任务报告新题")

    def test_chapter_reference_and_external_revision_are_checked(self):
        receipt = self.run_candidate(self.all_items)
        reviews = [approve(row) for row in receipt["items"]]
        current = copy.deepcopy(self.request)
        current["document"]["surfaces"]["private-button"]["source_revision"] = "reader-v2"
        with self.assertRaisesRegex(tool.Failed, "document_source_changed_or_scope_mismatched"):
            tool.adoption_check(self.workflow, current, receipt, reviews)
        self.source["toc_layout"]["groups"][0]["chapter"]["opening"] = "missing-section"
        transport = unittest.mock.Mock()
        with self.assertRaisesRegex(tool.Failed, "invalid_study_chapter_references"):
            tool.candidate_receipt(self.workflow, self.request, transport, "fixture")
        transport.assert_not_called()

    def test_unknown_visible_structure_fails_before_transport(self):
        self.source["sections"][0]["blocks"][1]["summary"] = "未登记的表格说明"
        transport = unittest.mock.Mock()
        with self.assertRaisesRegex(tool.Failed, "unsupported_study_field"):
            tool.candidate_receipt(self.workflow, self.request, transport, "fixture")
        transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
