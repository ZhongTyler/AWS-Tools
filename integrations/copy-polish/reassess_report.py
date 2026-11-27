"""Reassess one saved STOP report response. No transport, fixture or source overwrite."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

VERSION = 'saved-report-response-v1'
MODE = 'live_response_reassessment'
MEMBERS = {'request','original_receipt','diagnostic','payload','host','execution','started','literal_inventory'}
LIMIT = 1024 * 1024

def need(value, code):
    if not value:
        raise ValueError(code)

def read_files(paths, *, members=MEMBERS):
    need(isinstance(paths, dict) and paths.keys() == members, 'invalid_reassessment_members')
    values, proofs = {}, {}
    for name, value in paths.items():
        need(isinstance(value, str), 'invalid_evidence_path')
        path = Path(value)
        need(path.is_absolute(), 'absolute_evidence_path_required')
        need(not any(p.is_symlink() or p.exists() and getattr(p.lstat(), 'st_file_attributes', 0) & 0x400 for p in [path,*path.parents]), 'linked_evidence_denied')
        need(path.is_file() and path.stat().st_size <= LIMIT, 'invalid_evidence_size')
        raw = path.read_bytes()
        values[name] = json.loads(raw.decode('utf-8'))
        proofs[name] = {'path':str(path.resolve()), 'sha256':hashlib.sha256(raw).hexdigest()}
    return values, proofs

def classify(api, workflow, request, original, diagnostic, *, literal_inventory=None):
    profile, context, items, document, prepared = api.prepare_edit_request(request, workflow, expected_document=original['document'])
    need(prepared is not None and document['format'] == api.report.FORMAT, 'report_reassessment_only')
    slots = {str(i):item for i,item in enumerate(items,1)}
    version = api.resolve_report_editor(request, document)[1]
    returned = api.response_items(diagnostic['visible_text'], report_slots=slots, allow_noop_edits=version=='1.2.0')
    receipt = {key:deepcopy(value) for key,value in original.items() if key not in {'items','status','report_review_key','reassessment'}}
    rows = [{'id':item['id'], 'source_key':api.source_identity(context,item,None)} for item in items]
    return api.finish_candidate(workflow,profile,context,items,document,prepared,False,None,receipt,rows,returned,literal_inventory=literal_inventory)

def bound_response(api, workflow, paths, *, members=MEMBERS):
    """Verify the original saved live response without changing its disposition."""
    values, proofs = read_files(paths, members=members)
    request, original, diagnostic = [values[k] for k in ['request','original_receipt','diagnostic']]
    host, execution, started = [values[k] for k in ['host','execution','started']]
    need(original.get('mode')=='live' and original.get('status')=='partial' and original.get('diagnostic_output')=='saved', 'original_partial_live_required')
    need(original.get('tool_version')==api.VERSION and original.get('workflow')==workflow, 'original_scope_mismatch')
    need(original.get('finish_reason')==diagnostic.get('finish_reason')=='STOP', 'complete_STOP_required')
    need(diagnostic.get('schema_version')==1 and diagnostic.get('returned_model')==original.get('returned_model'), 'diagnostic_identity_mismatch')
    need(diagnostic.get('transport_version')==original.get('transport_version')==api.TRANSPORT_VERSION, 'transport_identity_mismatch')
    need(all(original.get('usage',{}).get(k)==v for k,v in diagnostic.get('usage',{}).items()), 'usage_identity_mismatch')
    need(started.get('request_sha256')==proofs['request']['sha256'], 'call_request_identity_mismatch')
    need(execution.get('started_at')==started.get('started_at') and execution.get('status')==original['status'] and execution.get('exit_code')==1, 'call_execution_mismatch')
    need(execution.get('usage')==original.get('usage'), 'call_usage_mismatch')
    need(Path(execution.get('candidate','')).resolve()==Path(proofs['original_receipt']['path']), 'call_candidate_path_mismatch')
    need(Path(execution.get('export','')).resolve()==Path(proofs['host']['path']).parent==Path(proofs['payload']['path']).parent==Path(proofs['request']['path']).parent, 'call_export_path_mismatch')
    # Saved prepare payload identity and actual candidate identity remain separate.
    payload_identity = api.verify_report_payload(workflow,request,values['payload'],expected_document=host.get('document'))
    api.prepare_edit_request(request,workflow,expected_document=original['document'])
    old = classify(api,workflow,request,original,diagnostic)
    need(old==original, 'saved_response_does_not_reproduce_original_partial')
    return values, proofs, payload_identity


def build(api, workflow, paths):
    values, proofs, payload_identity = bound_response(api, workflow, paths)
    request, original, diagnostic = [values[k] for k in ['request','original_receipt','diagnostic']]
    result = classify(api,workflow,request,original,diagnostic,literal_inventory=values['literal_inventory'])
    result['mode'] = MODE
    evidence = {'version':VERSION, 'files':proofs, 'source_mode':'live', 'original_status':'partial',
                'raw_visible_text_sha256':hashlib.sha256(diagnostic['visible_text'].encode()).hexdigest(),
                'guard_contract_version':values['literal_inventory'].get('contract_version'),
                'prepare_editor_version':payload_identity['editor_version'],
                'actual_identity_editor_version':api.resolve_report_editor(request,original['document'])[1],
                'actual_wire_capture':'unknown', 'new_api_calls':0, 'original_receipt_unchanged':True}
    evidence['key'] = api.digest(evidence)
    result['reassessment'] = evidence
    return result

def verify(api, workflow, current, receipt):
    evidence = receipt.get('reassessment')
    need(isinstance(evidence,dict) and evidence.get('version')==VERSION, 'unknown_reassessment_version')
    proofs = evidence.get('files')
    need(isinstance(proofs,dict) and proofs.keys()==MEMBERS, 'invalid_reassessment_members')
    paths = {name:row['path'] for name,row in proofs.items()}
    values, actual = read_files(paths)
    need(actual==proofs and values['request']==current, 'reassessment_evidence_changed')
    need(build(api,workflow,paths)==receipt, 'reassessment_candidate_changed')
    return values['literal_inventory']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True,type=Path,help='Explicit local evidence paths, not a fixture response')
    args=parser.parse_args()
    import run as tool
    try:
        bundle=json.loads(args.bundle.read_text(encoding='utf-8'))
        result=build(SimpleNamespace(**vars(tool)),bundle['workflow'],bundle['inputs'])
    except (ValueError,OSError,KeyError,TypeError) as error:
        result={'status':'invalid','error':str(error)}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='pass' else 1 if result['status'] in ('partial','failed') else 2

if __name__=='__main__':raise SystemExit(main())
