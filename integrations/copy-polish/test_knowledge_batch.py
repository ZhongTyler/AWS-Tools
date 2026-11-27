import copy
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import run as api
from test_contract import knowledge_request


def batch(profile='raw'):
    a=knowledge_request(profile);b=copy.deepcopy(a)
    b['document']['source_revision']='frozen-other'
    b['document']['source']['sections'][0]['blocks'][0]['text']='保留演练状态。\n\n这一规则适用于 3 次演练。'
    return {'profile':profile,'document':{'format':'knowledge-documents-v1','documents':[
        {'id':'host-a','request':a},{'id':'host-b','request':b}]}}


def fixture(request, mutate=None):
    wire=json.loads(api.report_payload('knowledge',request)['contents'][0]['parts'][0]['text'])
    slots=[b for d in wire['documents'] for s in d['sections'] for b in s.get('blocks',[]) if b[0]]
    content={'items':[],'retained_ids':[s[0] for s in slots]}
    if mutate:mutate(content,slots)
    return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(content)}]}}]}


def decisions(receipt):
    docs=[]
    for d in receipt['documents']:
        rows=[{'id':r['id'],'review_key':r['review_key'],'decision':'approve','reviewer':'offline-fixture'} for r in d['receipt']['items']]
        rows.append({'id':'/report-review','review_key':d['receipt']['report_review_key'],'decision':'approve','reviewer':'offline-fixture'})
        docs.append({'id':d['id'],'reviews':rows})
    return {'documents':docs,'group_review':{'review_key':receipt['group_review_key'],'decision':'approve','reviewer':'offline-fixture'}}


def mixed_receipt(request):
    def corrupt(c,slots):
        c['retained_ids'].remove(slots[0][0])
        c['items']=[{'id':slots[0][0],'text':slots[0][2].replace('2','4'),'reason':'合成保护失败'}]
    response=fixture(request,corrupt);response['modelVersion']='gemini-fixture-model'
    return api.candidate_receipt('knowledge',request,lambda _:response,'fixture')


def disposition_reviews(request,receipt):
    plan=api.knowledge_batch_review_plan('knowledge',request,receipt);docs=[]
    for expected,entry in zip(plan['documents'],receipt['documents']):
        if expected['decision']=='native_review':
            child=entry['receipt'];rows=[{'id':r['id'],'review_key':r['review_key'],'decision':'approve','reviewer':'engineering-fixture-only'} for r in child['items']]
            rows.append({'id':'/report-review','review_key':child['report_review_key'],'decision':'approve','reviewer':'engineering-fixture-only'})
            docs.append({'id':entry['id'],'reviews':rows})
        else:
            docs.append({'id':entry['id'],'decision':'retain_source','source_key':expected['source_key'],'review_key':expected['review_key'],
                         'reviewer':'engineering-fixture-only','reason':'整篇保留冻结原文，不采失败改写。'})
    return {'documents':docs,'group_review':{'review_key':plan['group_review_key'],'decision':'approve','reviewer':'engineering-fixture-only'}}


def retain_document(request, receipt, reviews, index):
    expected=api.knowledge_batch_review_plan('knowledge',request,receipt)['documents'][index]
    reviews['documents'][index]={'id':expected['id'],'decision':'retain_source','source_key':expected['source_key'],
                                 'review_key':expected['review_key'],'reviewer':'engineering-fixture-only',
                                 'reason':'候选无阅读收益，保留整篇冻结原文。'}


class BatchContract(unittest.TestCase):
    def candidate(self,r,change=None):
        transport=Mock(return_value=fixture(r,change))
        receipt=api.candidate_receipt('knowledge',r,transport,'fixture')
        transport.assert_called_once()
        return receipt

    def test_native_reuse_and_exact_payload_for_both_profiles(self):
        for profile in ('raw','wiki'):
            r=batch(profile);receipt=self.candidate(r);self.assertEqual(receipt['status'],'pass')
            result=api.adoption_check('knowledge',r,receipt,decisions(receipt))
            self.assertEqual(result['status'],'pass')
            for original,checked in zip(r['document']['documents'],result['documents']):
                self.assertEqual(checked['id'],original['id'])
                self.assertEqual(checked['result']['revised_blocks']['operation.body'],original['request']['document']['source']['sections'][0]['blocks'][0]['text'])
            p=api.knowledge_batch_plan('knowledge',r)
            self.assertEqual(p['payload_bytes'],len(api.json_bytes(api.report_payload('knowledge',r))))
            self.assertEqual(p['actual_model_output_window'],'unknown')
            self.assertNotIn('host-a',json.dumps(api.report_payload('knowledge',r)))
            self.assertNotIn('frozen-other',json.dumps(api.report_payload('knowledge',r)))

    def test_document_dispositions_preserve_original_failed_receipt(self):
        r=batch();receipt=mixed_receipt(r);before=api.json_bytes(receipt)
        reviews=disposition_reviews(r,receipt)
        checked=api.adoption_check('knowledge',r,receipt,reviews)
        self.assertEqual(checked['status'],'pass');self.assertEqual(checked['parent_candidate_status'],'failed')
        bad,good=checked['documents']
        self.assertEqual(bad['result']['status'],'source_retained');self.assertFalse(bad['result']['candidate_adopted'])
        self.assertNotIn('revised_blocks',bad['result'])
        self.assertEqual(good['result']['status'],'pass');self.assertIn('revised_blocks',good['result'])
        self.assertEqual(api.json_bytes(receipt),before)

    def test_technical_pass_can_explicitly_retain_source_in_failed_or_pass_parent(self):
        r=batch();good_response=fixture(r);good_response['modelVersion']='gemini-fixture-model'
        good=api.candidate_receipt('knowledge',r,lambda _:good_response,'fixture')
        for receipt in (mixed_receipt(r),good):
            original=api.json_bytes(receipt);reviews=disposition_reviews(r,receipt)
            retain_document(r,receipt,reviews,1)
            checked=api.adoption_check('knowledge',r,receipt,reviews)
            self.assertEqual(checked['parent_candidate_status'],receipt['status'])
            retained=checked['documents'][1]['result']
            self.assertEqual(retained['status'],'source_retained')
            self.assertEqual(retained['original_candidate_status'],'pass')
            self.assertFalse(retained['candidate_adopted'])
            # Technical pass parent: first document may still use its full native reviews.
            if receipt['status']=='pass':self.assertEqual(checked['documents'][0]['result']['status'],'pass')
            retain_document(r,receipt,reviews,0)
            checked=api.adoption_check('knowledge',r,receipt,reviews)
            self.assertTrue(all(d['result']['status']=='source_retained' for d in checked['documents']))
            self.assertEqual(api.json_bytes(receipt),original)
        self.assertEqual(api.adoption_check('knowledge',r,good,decisions(good))['status'],'pass')
        self.assertEqual(api.adoption_check('knowledge',r,good,disposition_reviews(r,good))['status'],'pass')

    def test_pass_parent_semantic_retention_rejects_stale_or_incomplete_reviews(self):
        r=batch();response=fixture(r);response['modelVersion']='gemini-fixture-model'
        receipt=api.candidate_receipt('knowledge',r,lambda _:response,'fixture')
        reviews=disposition_reviews(r,receipt);retain_document(r,receipt,reviews,1)
        for field in ('reason','source_key','review_key','reviewer'):
            wrong=copy.deepcopy(reviews);wrong['documents'][1].pop(field)
            with self.assertRaises(api.Failed):api.adoption_check('knowledge',r,receipt,wrong)
        wrong=copy.deepcopy(receipt);wrong['usage']={'totalTokenCount':99}
        with self.assertRaises(api.Failed):api.adoption_check('knowledge',r,wrong,reviews)
        wrong=copy.deepcopy(r);wrong['document']['documents'][1]['request']['document']['source_revision']+='changed'
        with self.assertRaises(api.Failed):api.adoption_check('knowledge',wrong,receipt,reviews)

    def test_mixed_dispositions_fail_closed_on_incomplete_or_changed_evidence(self):
        r=batch();receipt=mixed_receipt(r);reviews=disposition_reviews(r,receipt)
        for change in ('finish','model','timeout','missing','child_status','cross_document','parent_status','usage'):
            wrong=copy.deepcopy(receipt)
            if change=='finish':wrong['finish_reason']='MAX_TOKENS'
            elif change=='model':wrong['returned_model']='gemini-other'
            elif change=='timeout':wrong['transport_error']={'phase':'reading_sse'}
            elif change=='missing':wrong['documents'][0]['receipt']['items'].pop()
            elif change=='child_status':wrong['documents'][0]['receipt']['status']='pass'
            elif change=='cross_document':wrong['documents'].reverse()
            elif change=='parent_status':wrong['status']='pass'
            else:wrong['usage']={'totalTokenCount':999}
            with self.subTest(change=change),self.assertRaises(api.Failed):api.adoption_check('knowledge',r,wrong,reviews)
        changed=copy.deepcopy(r);changed['document']['documents'][0]['request']['document']['source_revision']+='new'
        with self.assertRaises(api.Failed):api.adoption_check('knowledge',changed,receipt,reviews)
        # A structurally invalid member cannot be turned into a retainable content failure.
        wrong=copy.deepcopy(receipt);wrong['documents'][0]['receipt']['items'][0]['status']='timeout'
        with self.assertRaises(api.Failed):api.knowledge_batch_review_plan('knowledge',r,wrong)

    def test_document_disposition_reviews_cannot_adopt_failed_child_or_skip_reviews(self):
        r=batch();receipt=mixed_receipt(r);reviews=disposition_reviews(r,receipt)
        for change in ('failed_as_approve','no_reason','no_source_key','no_member_key','no_group','no_native_whole'):
            wrong=copy.deepcopy(reviews)
            if change=='failed_as_approve':wrong['documents'][0]['decision']='approve'
            elif change=='no_reason':wrong['documents'][0].pop('reason')
            elif change=='no_source_key':wrong['documents'][0].pop('source_key')
            elif change=='no_member_key':wrong['documents'][0].pop('review_key')
            elif change=='no_group':wrong['group_review']['decision']='reject'
            else:wrong['documents'][1]['reviews'].pop()
            with self.subTest(change=change),self.assertRaises(api.Failed):api.adoption_check('knowledge',r,receipt,wrong)

    def test_mixing_duplicates_overlap_and_oversize_before_transport(self):
        cases=[]
        r=batch();r['document']['documents'][1]['request']=knowledge_request('wiki');cases.append(r)
        r=batch();r['document']['documents'][1]['id']='host-a';cases.append(r)
        r=batch();r['document']['documents'][1]['request']=copy.deepcopy(r['document']['documents'][0]['request']);cases.append(r)
        r=batch();r['document']['documents'][0]['request']['document']['source']['opening']='长'*30000;cases.append(r)
        for r in cases:
            transport=Mock()
            with self.assertRaises(api.Failed):api.candidate_receipt('knowledge',r,transport,'fixture')
            transport.assert_not_called()

    def test_missing_duplicate_and_protected_number_quote(self):
        r=batch()
        for change in [lambda c,s:c['retained_ids'].pop(),lambda c,s:c['retained_ids'].append(c['retained_ids'][0])]:
            self.assertEqual(self.candidate(r,change)['status'],'failed')
        def corrupt(c,s):
            c['retained_ids'].remove(s[0][0]);c['items']=[{'id':s[0][0],'text':s[0][2].replace('2','4'),'reason':'改写'}]
        self.assertEqual(self.candidate(r,corrupt)['status'],'failed')
        r['document']['documents'][0]['request']['document']['source']['sections'][0]['blocks'][0]['text']+=' “原话保留”。'
        def quote(c,s):
            c['retained_ids'].remove(s[0][0]);c['items']=[{'id':s[0][0],'text':s[0][2].replace('原话保留','原话删除'),'reason':'改写'}]
        self.assertEqual(self.candidate(r,quote)['status'],'failed')

    def test_source_normalization_revision_and_document_swaps_stale(self):
        r=batch();receipt=self.candidate(r);reviews=decisions(receipt)
        for field in ('revision','source','normalization'):
            changed=copy.deepcopy(r);doc=changed['document']['documents'][0]['request']['document']
            if field=='revision':doc['source_revision']+='changed'
            elif field=='source':doc['source']['opening']+='新条件'
            else:doc['source']['sections'][0]['blocks'][0]['text']=doc['source']['sections'][0]['blocks'][0]['text'].replace('\n','\r\n')
            with self.assertRaises(api.Failed):api.adoption_check('knowledge',changed,receipt,reviews)
        changed=copy.deepcopy(receipt);changed['documents'][0]['receipt'],changed['documents'][1]['receipt']=changed['documents'][1]['receipt'],changed['documents'][0]['receipt']
        with self.assertRaises(api.Failed):api.adoption_check('knowledge',r,changed,reviews)
        # Even with a recomputed group hash, native per-document source binding still rejects the swap.
        changed['group_review_key']=api.knowledge_batch.group_key(api,r,changed['documents'])
        bad=decisions(changed)
        with self.assertRaises(api.Failed):api.adoption_check('knowledge',r,changed,bad)

    def test_group_and_document_reviews_are_both_required(self):
        r=batch();receipt=self.candidate(r);reviews=decisions(receipt)
        missing=copy.deepcopy(reviews);missing['group_review']['decision']='reject'
        with self.assertRaises(api.Failed):api.adoption_check('knowledge',r,receipt,missing)
        missing=copy.deepcopy(reviews);missing['documents'][0]['reviews']=[]
        result=api.adoption_check('knowledge',r,receipt,missing)
        self.assertEqual(result['status'],'failed');self.assertNotIn('documents',result)
        truncated=fixture(r);truncated['candidates'][0]['finishReason']='MAX_TOKENS'
        self.assertEqual(api.candidate_receipt('knowledge',r,lambda _:truncated,'fixture')['status'],'failed')

    def test_output_guard_and_reason_cap(self):
        r=batch();blocks=r['document']['documents'][0]['request']['document']['source']['sections'][0]['blocks']
        for i in range(110):blocks.append({'id':'extra-'+str(i),'role':'prose','text':'原有说明。'})
        plan=api.knowledge_batch_plan('knowledge',r)
        self.assertLess(plan['payload_bytes'],api.MAX_REQUEST)
        self.assertFalse(plan['estimated_output_tokens_fit'])
        transport=Mock()
        with self.assertRaisesRegex(api.Failed,'estimated_batch_output_too_large'):
            api.candidate_receipt('knowledge',r,transport,'fixture')
        transport.assert_not_called()
        r=batch()
        def long_reason(c,s):
            c['retained_ids'].remove(s[0][0]);c['items']=[{'id':s[0][0],'text':s[0][2]+'保留含义。','reason':'改'*65}]
        self.assertEqual(self.candidate(r,long_reason)['error'],'batch_reason_too_long')
        self.assertEqual(api.candidate_receipt('knowledge',r,lambda _:{'padding':'x'*api.MAX_RESPONSE},'fixture')['error'],'response_too_large')


    def test_group_failure_preserves_stop_metadata_and_native_diagnostic(self):
        r=batch()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'.local';task=root/'case';task.mkdir(parents=True)
            for i,text in enumerate(('not-json','{"items":[],"retained_ids":[]}')):
                response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}],
                          'modelVersion':'gemini-fixture-model','usageMetadata':{'candidatesTokenCount':17,'thoughtsTokenCount':4}}
                output=task/f'case-{i}.json'
                with patch.object(api,'DIAGNOSTIC_ROOT',root),patch.dict(api.os.environ,{api.KEY_ENV:'synthetic-key-only'}):
                    result=api.candidate_receipt('knowledge',r,lambda _:response,'live',diagnostic_output=output)
                self.assertEqual(result['status'],'failed');self.assertEqual(result['finish_reason'],'STOP')
                self.assertEqual(result['returned_model'],'gemini-fixture-model')
                self.assertEqual(result['usage']['candidatesTokenCount'],17)
                self.assertEqual(result['diagnostic_output'],'saved')
                saved=json.loads(output.read_bytes());self.assertEqual(saved['visible_text'],text)
                self.assertNotIn('thoughtsTokenCount',saved['usage'])
            response=fixture(r);response['usageMetadata']={'totalTokenCount':27}
            good=api.candidate_receipt('knowledge',r,lambda _:response,'fixture')
            self.assertEqual(good['usage'],{'totalTokenCount':27})
            self.assertTrue(all(d['receipt']['usage'] is None for d in good['documents']))

    def test_group_diagnostic_withholds_truncation_and_sensitive_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'.local';task=root/'case';task.mkdir(parents=True)
            for i,(text,finish) in enumerate((('partial','MAX_TOKENS'),('synthetic-key-only','STOP'),('invalid \\u0073ynthetic-key-only','STOP'))):
                response={'candidates':[{'finishReason':finish,'content':{'parts':[{'text':text}]}}],'usageMetadata':{'candidatesTokenCount':9}}
                output=task/f'case-{i}.json'
                with patch.object(api,'DIAGNOSTIC_ROOT',root),patch.dict(api.os.environ,{api.KEY_ENV:'synthetic-key-only'}):
                    result=api.candidate_receipt('knowledge',batch(),lambda _:response,'live',diagnostic_output=output)
                self.assertEqual(result['status'],'failed');self.assertFalse(output.exists())
                self.assertEqual(result['usage'],{'candidatesTokenCount':9})
                self.assertEqual(result['finish_reason'],finish)
                self.assertNotIn('synthetic-key-only',json.dumps(result))


if __name__=='__main__':unittest.main()
