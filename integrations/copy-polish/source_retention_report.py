"""Explicit source retention for rejected slots in one complete saved live report.

No transport. The original partial receipt and visible model text remain evidence.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import reassess_report

VERSION = 'saved-report-source-retention-v1'
MODE = 'live_response_source_retention'
MEMBERS = (reassess_report.MEMBERS - {'literal_inventory'}) | {'author_decisions'}
need = reassess_report.need


def text_sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def build(api, workflow, paths):
    values, proofs, payload_identity = reassess_report.bound_response(api, workflow, paths, members=MEMBERS)
    request, original, diagnostic, plan = [values[k] for k in ('request','original_receipt','diagnostic','author_decisions')]
    profile, context, items, document, prepared = api.prepare_edit_request(request, workflow, expected_document=original['document'])
    need(prepared is not None and document['format'] == api.report.FORMAT, 'report_source_retention_only')
    required = {'schema_version','status','workflow','request_sha256','original_receipt_sha256','diagnostic_sha256','decisions'}
    need(isinstance(plan,dict) and required <= plan.keys() <= required | {'author_decision_origin'}
         and plan['schema_version'] == 1 and plan['workflow'] == workflow and api.report.label(plan['status'],200), 'invalid_source_retention_plan')
    for key in ('request','original_receipt','diagnostic'):
        need(plan[key+'_sha256'] == proofs[key]['sha256'], 'source_retention_plan_identity_changed')
    failed = {r['id']:r for r in original['items'] if r.get('status') == 'protection_failed'}
    need(failed and all(r.get('status') in ('pending_review','protection_failed') for r in original['items'])
         and original.get('unexpected_output_rows') == 0, 'only_complete_protection_failures_may_be_retained')
    decisions = api.index_by_id(plan['decisions'])
    need(decisions.keys() == failed.keys(), 'all_and_only_failed_slots_need_explicit_decisions')
    slots = {str(i):item for i,item in enumerate(items,1)}
    version = api.resolve_report_editor(request, document)[1]
    returned = api.response_items(diagnostic['visible_text'],report_slots=slots,allow_noop_edits=version=='1.2.0')
    need(len(returned)==len(slots) and len({r['id'] for r in returned})==len(slots)
         and {r['id'] for r in returned}==slots.keys(), 'complete_saved_slot_coverage_required')
    by_id = {slots[row['id']]['id']:row for row in returned}
    originals = {item['id']:item for item in items}
    for name, decision in decisions.items():
        need(set(decision)=={'id','source_key','rejected_candidate_text_sha256','decision','reviewer','reason'}
             and decision['decision']=='retain_source' and decision['source_key']==failed[name]['source_key']
             and isinstance(decision['reviewer'],str) and bool(decision['reviewer'].strip())
             and api.report.label(decision['reason'],500)
             and decision['rejected_candidate_text_sha256']==text_sha(by_id[name]['text']), 'invalid_or_stale_source_retention_decision')
    origin = None
    if 'author_decision_origin' in plan:
        entry = plan['author_decision_origin']
        need(isinstance(entry,dict) and entry.keys()=={'path','sha256'}, 'invalid_author_decision_origin')
        origin_values, origin_proof = reassess_report.read_files({'origin':entry['path']},members={'origin'})
        need(origin_proof['origin']['sha256']==entry['sha256'], 'author_decision_origin_changed')
        original_decisions = origin_values['origin']
        need(original_decisions.get('kind')=='author_source_retention_decisions'
             and original_decisions.get('parent_sha256')==proofs['original_receipt']['sha256']
             and original_decisions.get('diagnostic_sha256')==proofs['diagnostic']['sha256']
             and original_decisions.get('document')==document, 'author_decision_origin_scope_changed')
        origin_rows = api.index_by_id(original_decisions.get('decisions'))
        need(origin_rows.keys()==decisions.keys(), 'author_decision_origin_slots_changed')
        for name,row in origin_rows.items():
            need(all(row.get(k)==decisions[name][k] for k in ('id','source_key','decision','reviewer','reason'))
                 and row.get('rejected_proposal_sha256')==decisions[name]['rejected_candidate_text_sha256']
                 and row.get('source_text_sha256')==text_sha(originals[name]['text']), 'author_decision_origin_content_changed')
        origin = origin_proof['origin']
    effective = deepcopy(returned)
    for row in effective:
        name = slots[row['id']]['id']
        if name in decisions:
            # An author choice, explicitly not a normalized model response.
            row.clear()
            row.update(id=next(key for key,item in slots.items() if item['id']==name),
                       text=originals[name]['text'],reason=decisions[name]['reason'])
    receipt = {k:deepcopy(v) for k,v in original.items() if k not in {'items','status','report_review_key'}}
    rows = [{'id':item['id'],'source_key':api.source_identity(context,item,None)} for item in items]
    result = api.finish_candidate(workflow,profile,context,items,document,prepared,False,None,receipt,rows,effective)
    need(result['status']=='pass', 'effective_source_retention_still_fails_protection')
    result['mode'] = MODE
    evidence = {'version':VERSION,'files':proofs,'original_mode':'live','original_status':'partial',
                'raw_visible_text_sha256':text_sha(diagnostic['visible_text']),
                'effective_source_ids':sorted(decisions),'decisions':deepcopy(plan['decisions']),
                'source_text_sha256':{name:text_sha(originals[name]['text']) for name in sorted(decisions)},
                'prepare_editor_version':payload_identity['editor_version'],
                'actual_identity_editor_version':version,'actual_wire_capture':'unknown',
                'new_api_calls':0,'original_receipt_unchanged':True,'other_slots_require_native_review':True}
    if origin:evidence['author_decision_origin']=origin
    evidence['key'] = api.digest(evidence)
    result['source_retention'] = evidence
    return result


def rebuild(api, workflow, current, evidence):
    need(isinstance(evidence,dict) and evidence.get('version')==VERSION, 'unknown_source_retention_version')
    proofs=evidence.get('files')
    need(isinstance(proofs,dict) and proofs.keys()==MEMBERS,'invalid_source_retention_members')
    paths={name:row['path'] for name,row in proofs.items()}
    values,actual=reassess_report.read_files(paths,members=MEMBERS)
    need(actual==proofs and values['request']==current,'source_retention_evidence_changed')
    receipt=build(api,workflow,paths)
    need(receipt['source_retention']==evidence,'source_retention_identity_changed')
    return receipt


def verify(api, workflow, current, receipt):
    expected=rebuild(api,workflow,current,receipt.get('source_retention'))
    need(expected==receipt,'source_retention_candidate_changed')
    return {row['id']:row for row in expected['source_retention']['decisions']}


def required_reviews(api, workflow, current, receipt):
    decisions=verify(api,workflow,current,receipt)
    candidates={r['id']:r for r in receipt['items']}
    return [dict(row,review_key=candidates[name]['review_key']) for name,row in decisions.items()]


def verify_checked(api, workflow, current, checked):
    candidate=rebuild(api,workflow,current,checked.get('source_retention'))
    rows=api.index_by_id(checked.get('items'))
    by_id={row['id']:row for row in candidate['items']}
    for name in candidate['source_retention']['effective_source_ids']:
        row=rows.get(name,{})
        need(row.get('status')=='ready' and row.get('decision')=='retain_source'
             and row.get('text')==by_id[name]['text'] and row.get('disposition')=='retained'
             and row.get('candidate_review_key')==by_id[name]['review_key'], 'checked_source_retention_changed')
    return candidate['source_retention']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True,type=Path)
    parser.add_argument('--required-reviews',action='store_true',help='Only explicit retained-source decisions; never approves other slots')
    args=parser.parse_args()
    import run as tool
    api=SimpleNamespace(**vars(tool))
    try:
        bundle=json.loads(args.bundle.read_text(encoding='utf8'))
        result=build(api,bundle['workflow'],bundle['inputs'])
        if args.required_reviews:
            request=json.loads(Path(bundle['inputs']['request']).read_text(encoding='utf8'))
            result={'status':'explicit_source_reviews_only','reviews':required_reviews(api,bundle['workflow'],request,result)}
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps({'status':'invalid','error':str(error)},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
