"""Transport grouping only; native Knowledge validation and adoption remain in run.py."""
from collections import Counter
from copy import deepcopy

FORMAT = 'knowledge-documents-v1'
EDITOR = ('以下 documents 是同一 profile 的独立文档，各自 context、简报和只读语境只作用于本篇。'
          '禁止跨文档移动、合并、借用事实或统一论点。document 是传输分组号；所有可编辑槽编号全组唯一。'
          '按原规则返回一份 items/retained_ids，保留文档与块边界。每项改动reason用不超过64个字符说明具体处理。')


def prepare(api, workflow, request):
    if (workflow != 'knowledge' or not isinstance(request, dict)
            or set(request) != {'profile', 'document'} or not isinstance(request['profile'], str) or request['profile'] not in api.knowledge.KINDS):
        raise api.Failed('invalid_knowledge_batch')
    doc = request['document']
    if (not isinstance(doc, dict) or set(doc) != {'format', 'documents'} or doc['format'] != FORMAT
            or not isinstance(doc['documents'], list) or not 1 <= len(doc['documents']) <= 64
            or len(api.json_bytes(request)) > api.report.LOCAL_LIMIT):
        raise api.Failed('invalid_knowledge_batch')
    documents, wire, slots, ids, identities = [], [], {}, set(), set()
    for ordinal, entry in enumerate(doc['documents'], 1):
        if (not isinstance(entry, dict) or set(entry) != {'id', 'request'}
                or not api.knowledge.key(entry['id']) or entry['id'] in ids):
            raise api.Failed('invalid_batch_document_identity')
        ids.add(entry['id'])
        native = entry['request']
        if (not isinstance(native, dict) or native.get('profile') != request['profile']
                or not isinstance(native.get('document'), dict)
                or native['document'].get('format') != api.knowledge.FORMAT):
            raise api.Failed('mixed_batch_profile_or_format')
        profile, context, items, identity, prepared = api.prepare_edit_request(native, workflow)
        if identity['document_revision'] in identities:
            raise api.Failed('duplicate_batch_document')
        identities.add(identity['document_revision'])
        layout = deepcopy(prepared[2])
        mapping = {}
        for local_id, item in enumerate(items, 1):
            global_id = str(len(slots) + 1)
            slots[global_id] = item
            mapping[str(local_id)] = global_id
        for section in layout['sections']:
            for block in section.get('blocks', []):
                if block[0] is not None:
                    block[0] = mapping[block[0]]
        wire.append({'document': str(ordinal), 'context': context, **layout})
        documents.append((entry['id'], native, mapping))
    payload = {'systemInstruction': {'parts': [{'text': api.knowledge.EDITOR + EDITOR}]},
               'contents': [{'role': 'user', 'parts': [{'text': api.json_bytes({'documents': wire}).decode('utf-8')}]}],
               'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': 16384}}
    if len(api.json_bytes(payload)) > api.MAX_REQUEST:
        raise api.Failed('report_payload_too_large')
    return payload, documents, slots


def plan(api, workflow, request):
    payload, documents, slots = prepare(api, workflow, request)
    # Projection, not a provider token guarantee. Includes full edits and reasons, never assumes retention.
    skeleton = {'items': [{'id': i, 'text': s['text'], 'reason': 'x' * 64} for i, s in slots.items()], 'retained_ids': []}
    visible_estimate = len(api.json_bytes(skeleton)) + sum(len(api.json_bytes(s['text'])) // 4 + 192 for s in slots.values())
    token_estimate = (visible_estimate + 1) // 2
    estimate = visible_estimate + 8192
    return {'payload_bytes': len(api.json_bytes(payload)), 'payload_sha256': api.digest(payload),
            'local_request_bytes': len(api.json_bytes(request)), 'documents': len(documents), 'editable_blocks': len(slots),
            'estimated_response_bytes': estimate, 'response_limit_bytes': api.MAX_RESPONSE,
            'estimated_response_fits': estimate <= api.MAX_RESPONSE, 'configured_max_output_tokens': 16384,
            'estimated_output_tokens': token_estimate, 'output_token_reserve': 2048,
            'token_density_bytes': 2, 'text_growth_factor': 1.25, 'max_reason_characters': 64,
            'estimated_output_tokens_fit': token_estimate <= 16384 - 2048,
            'actual_model_output_window': 'unknown', 'estimate': 'all blocks edited; text 1.25x, 64 four-byte reason characters per block; projected UTF8 bytes / 2 token estimate (two historical samples observed 3.88-4.10 bytes/token), reserve 2048 configured tokens and 8192 response envelope bytes; not a provider tokenizer or a hard worst-case guarantee'}


def group_key(api, request, documents):
    return api.digest([FORMAT, request, documents])


def candidate(api, workflow, request, transport, mode, diagnostic_output=None):
    if diagnostic_output is not None:
        diagnostic_output = api.diagnostic_destination(diagnostic_output)
    payload, documents, slots = prepare(api, workflow, request)
    projection = plan(api, workflow, request)
    if not projection['estimated_response_fits'] or not projection['estimated_output_tokens_fit']:
        raise api.Failed('estimated_batch_output_too_large')
    result = {'format': FORMAT, 'tool_version': api.VERSION, 'requested_model': api.MODEL,
              'workflow': workflow, 'profile': request['profile'], 'mode': mode, **api.metadata({})}
    visible_text = None
    key = api.os.environ.get(api.KEY_ENV) if mode == 'live' else None
    try:
        response = transport(payload)
        if not isinstance(response, dict):
            raise api.Failed('invalid_response')
        result.update(api.metadata(response))
        if len(api.json_bytes(response)) > api.MAX_RESPONSE:
            raise api.Failed('response_too_large')
        visible_text = api.response_visible_text(response)
        if key and key in visible_text:
            raise api.Failed('credential_in_response')
        rows = api.response_items(visible_text, report_slots=slots)
        if (any(not isinstance(r, dict) or not isinstance(r.get('id'), str) for r in rows)
                or Counter(r['id'] for r in rows) != Counter({i: 1 for i in slots})):
            raise api.Failed('batch_slot_coverage_mismatch')
        by_id = {r['id']: r for r in rows}
        if any('reason' in r and (not isinstance(r['reason'], str) or len(r['reason']) > 64) for r in rows):
            raise api.Failed('batch_reason_too_long')
        results = []
        for doc_id, native, mapping in documents:
            local_rows = [{**by_id[global_id], 'id': local_id} for local_id, global_id in mapping.items()]
            fixture = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': api.json_bytes({'items': local_rows}).decode('utf-8')}]}}]}
            receipt = api.candidate_receipt(workflow, native, lambda _: fixture, mode)
            results.append({'id': doc_id, 'receipt': receipt})
        status = 'pass' if all(d['receipt']['status'] == 'pass' for d in results) else 'failed'
        result.update(status=status, documents=results)
        if status == 'pass':
            result['group_review_key'] = group_key(api, request, results)
        return result
    except api.Failed as exc:
        recovered = api.recover_completed_failure(exc, result)
        if recovered is not None:
            visible_text = recovered
        result.update(status='failed', error=str(exc))
        for field in ('finish_reason', 'transport_error', 'candidate_structure_error'):
            value = getattr(exc, field, None)
            if value is not None:
                result[field] = value
        return result
    finally:
        if diagnostic_output is not None:
            result['diagnostic_output'] = (api.save_response_diagnostic(diagnostic_output, visible_text, result, key)
                                           if visible_text is not None else 'not_saved')


def check(api, workflow, request, receipt, reviews):
    planned_review = (isinstance(reviews, dict) and isinstance(reviews.get('group_review'), dict)
                      and reviews['group_review'].get('review_key') == api.digest(['batch-document-disposition-v1', request, receipt]))
    source_retention = (isinstance(reviews, dict) and isinstance(reviews.get('documents'), list)
                        and any(isinstance(d, dict) and d.get('decision') == 'retain_source' for d in reviews['documents']))
    if isinstance(receipt, dict) and (receipt.get('status') == 'failed' or planned_review or source_retention):
        return check_dispositions(api, workflow, request, receipt, reviews)
    _, documents, _ = prepare(api, workflow, request)
    if (not isinstance(receipt, dict) or receipt.get('status') != 'pass' or receipt.get('format') != FORMAT
            or receipt.get('tool_version') != api.VERSION or receipt.get('workflow') != workflow
            or receipt.get('profile') != request['profile'] or receipt.get('mode') not in ('fixture', 'live')
            or not isinstance(receipt.get('documents'), list)):
        raise api.Failed('batch_receipt_mismatch')
    entries = receipt['documents']
    expected = [d[0] for d in documents]
    if any(not isinstance(e, dict) or set(e) != {'id', 'receipt'} or not isinstance(e['receipt'], dict) for e in entries) or [e['id'] for e in entries] != expected:
        raise api.Failed('batch_document_coverage_mismatch')
    key = group_key(api, request, entries)
    if receipt.get('group_review_key') != key:
        raise api.Failed('batch_source_or_candidate_changed')
    if (not isinstance(reviews, dict) or set(reviews) != {'documents', 'group_review'}
            or not isinstance(reviews['documents'], list) or not isinstance(reviews['group_review'], dict)
            or not api.approved(reviews['group_review'], key)):
        raise api.Failed('batch_group_review_missing_or_stale')
    decisions = reviews['documents']
    if (any(not isinstance(d, dict) or set(d) != {'id', 'reviews'} for d in decisions)
            or [d['id'] for d in decisions] != expected):
        raise api.Failed('batch_review_document_mismatch')
    results = []
    for (_, native, _), entry, decision in zip(documents, entries, decisions):
        if entry['receipt'].get('mode') != receipt['mode']:
            raise api.Failed('batch_receipt_mode_mismatch')
        checked = api.adoption_check(workflow, native, entry['receipt'], decision['reviews'])
        if checked['status'] != 'pass':
            return {'status': 'failed', 'format': FORMAT, 'error': 'batch_document_not_ready'}
        results.append({'id': entry['id'], 'result': checked})
    return {'status': 'pass', 'format': FORMAT, 'mode': receipt['mode'], 'group_review_key': key, 'documents': results}


def disposition_plan(api, workflow, request, receipt):
    _, documents, _ = prepare(api, workflow, request)
    if (not isinstance(receipt, dict) or receipt.get('status') not in ('pass', 'failed')
            or receipt.get('format') != FORMAT or receipt.get('tool_version') != api.VERSION
            or receipt.get('workflow') != workflow or receipt.get('profile') != request['profile']
            or receipt.get('mode') not in ('fixture', 'live') or receipt.get('finish_reason') != 'STOP'
            or receipt.get('error') is not None or receipt.get('transport_error') is not None
            or not api.report.label(receipt.get('requested_model'), 160)
            or not api.report.label(receipt.get('returned_model'), 160)):
        raise api.Failed('batch_disposition_requires_complete_stop')
    entries = receipt.get('documents')
    if (not isinstance(entries, list) or len(entries) != len(documents)
            or any(not isinstance(e, dict) or set(e) != {'id', 'receipt'} for e in entries)
            or [e['id'] for e in entries] != [d[0] for d in documents]):
        raise api.Failed('batch_document_coverage_mismatch')
    key = api.digest(['batch-document-disposition-v1', request, receipt])
    planned = []
    for (doc_id, native, _), entry in zip(documents, entries):
        child = entry['receipt']
        profile, context, items, identity, _ = api.prepare_edit_request(native, workflow)
        if (not isinstance(child, dict) or child.get('tool_version') != api.VERSION
                or child.get('workflow') != workflow or child.get('profile') != profile
                or child.get('mode') != receipt['mode'] or child.get('finish_reason') != 'STOP'
                or child.get('requested_model') != receipt['requested_model'] or child.get('document') != identity
                or child.get('returned_model') not in (None, receipt['returned_model']) or child.get('usage') is not None
                or child.get('error') is not None or child.get('transport_error') is not None
                or child.get('unexpected_output_rows') != 0):
            raise api.Failed('batch_child_identity_or_completion_mismatch')
        rows = api.index_by_id(child.get('items'))
        if set(rows) != {i['id'] for i in items}:
            raise api.Failed('batch_child_slot_coverage_mismatch')
        for item in items:
            row = rows[item['id']]
            source_key = api.source_identity(context, item, None)
            if row.get('source_key') != source_key:
                raise api.Failed('batch_child_source_changed')
            if row.get('status') == 'protection_failed':
                if set(row) != {'id', 'source_key', 'status'}:
                    raise api.Failed('batch_invalid_protection_failure')
            elif (row.get('status') != 'pending_review' or not api.knowledge.valid_prose(row.get('text'))
                  or not api.report.label(row.get('reason'), 500) or row.get('moves_from')
                  or api.candidate_issue(item, row['text'], profile, prose=True)
                  or row.get('review_key') != api.review_identity(workflow, profile, source_key, row['text'], row['reason'], [])):
                raise api.Failed('batch_child_not_complete_content_result')
        expected_status = api.outcome(list(rows.values()), 'pending_review')
        if child.get('status') != expected_status:
            raise api.Failed('batch_child_status_mismatch')
        if expected_status == 'pass':
            if child.get('report_review_key') != api.report_review_identity(identity, [rows[i['id']] for i in items]):
                raise api.Failed('batch_child_report_key_mismatch')
        planned.append({'id': doc_id, 'original_candidate_status': expected_status,
                        'decision': 'native_review' if expected_status == 'pass' else 'retain_source',
                        'allowed_decisions': ['native_review', 'retain_source'] if expected_status == 'pass' else ['retain_source'],
                        'source_key': identity['document_key'],
                        'review_key': api.digest([key, doc_id, native, child])})
    all_pass = all(d['original_candidate_status'] == 'pass' for d in planned)
    if ((receipt['status'] == 'failed' and all_pass)
            or receipt['status'] == 'pass' and (not all_pass or receipt.get('group_review_key') != group_key(api, request, entries))):
        raise api.Failed('batch_parent_status_or_binding_mismatch')
    return {'format': FORMAT, 'parent_candidate_status': receipt['status'], 'group_review_key': key,
            'original_receipt_canonical_sha256': api.digest(receipt), 'documents': planned}


def check_dispositions(api, workflow, request, receipt, reviews):
    plan = disposition_plan(api, workflow, request, receipt)
    if (not isinstance(reviews, dict) or set(reviews) != {'documents', 'group_review'}
            or not isinstance(reviews.get('group_review'), dict)
            or not api.approved(reviews['group_review'], plan['group_review_key'])):
        raise api.Failed('batch_disposition_group_review_missing_or_stale')
    decisions = reviews['documents']
    if (not isinstance(decisions, list) or any(not isinstance(d, dict) for d in decisions)
            or [d.get('id') for d in decisions] != [d['id'] for d in plan['documents']]):
        raise api.Failed('batch_review_document_mismatch')
    results = []
    for native_entry, entry, expected, decision in zip(request['document']['documents'], receipt['documents'], plan['documents'], decisions):
        if expected['original_candidate_status'] == 'pass' and set(decision) == {'id', 'reviews'}:
            checked = api.adoption_check(workflow, native_entry['request'], entry['receipt'], decision['reviews'])
            if checked['status'] != 'pass':
                raise api.Failed('batch_document_not_ready')
        else:
            if (set(decision) != {'id', 'decision', 'review_key', 'source_key', 'reviewer', 'reason'}
                    or decision.get('decision') != 'retain_source'
                    or decision.get('review_key') != expected['review_key'] or decision.get('source_key') != expected['source_key']
                    or not api.report.label(decision.get('reviewer'), 500) or not api.report.label(decision.get('reason'), 500)):
                raise api.Failed('batch_failed_child_requires_exact_source_retention')
            checked = {'status': 'source_retained', 'mode': receipt['mode'], 'candidate_adopted': False,
                       'original_candidate_status': expected['original_candidate_status'], 'source_key': expected['source_key'],
                       'source_retention_review_key': expected['review_key'], 'reviewer': decision['reviewer'], 'reason': decision['reason']}
        results.append({'id': entry['id'], 'result': checked})
    return {'status': 'pass', 'format': FORMAT, 'mode': receipt['mode'], 'parent_candidate_status': receipt['status'],
            'adoption_disposition': 'documents_reviewed_or_exact_source_retained',
            'original_receipt_canonical_sha256': plan['original_receipt_canonical_sha256'], 'group_review_key': plan['group_review_key'], 'documents': results}
