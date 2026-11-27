"""Synthetic local saved-call contracts; fixtures are never actual live evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from test_contract import tool, report_request, approve
import reassess_report
import source_retention_report as retention


class SourceRetentionTests(unittest.TestCase):
    workflow='game-research'

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='synthetic-source-retention-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.api=SimpleNamespace(**vars(tool))
        self.request=report_request()
        profile,_,items,document,_=tool.prepare_edit_request(self.request,self.workflow,editor_version='1.2.0')
        self.items=items
        target=next((i,item) for i,item in enumerate(items,1) if item['role']=='p')
        self.target=target[1]['id']
        bad=target[1]['text'].replace('20','21')
        self.assertNotEqual(bad,target[1]['text'])
        raw={'items':[{'id':str(target[0]),'text':bad,'reason':'Synthetic rejected change'}],
             'retained_ids':[str(i) for i in range(1,len(items)+1) if i!=target[0]]}
        self.diagnostic={'schema_version':1,'finish_reason':'STOP','transport_version':tool.TRANSPORT_VERSION,
                         'returned_model':'synthetic-fixture-only','usage':{'totalTokenCount':0},
                         'visible_text':json.dumps(raw,ensure_ascii=False)}
        seed={'mode':'live','status':'partial','diagnostic_output':'saved','tool_version':tool.VERSION,
              'workflow':self.workflow,'profile':profile,'document':document,'finish_reason':'STOP',
              'returned_model':'synthetic-fixture-only','transport_version':tool.TRANSPORT_VERSION,
              'usage':{'totalTokenCount':0},'synthetic_test_fixture':True}
        self.original=reassess_report.classify(self.api,self.workflow,self.request,seed,self.diagnostic)
        self.assertEqual(self.original['status'],'partial')
        self.paths={}
        export=self.root/'export';export.mkdir()
        for name,value in [('request',self.request),('original_receipt',self.original),('diagnostic',self.diagnostic),
                           ('payload',tool.report_payload(self.workflow,self.request,editor_version='1.2.0')),
                           ('host',{'document':document})]:
            self.paths[name]=str((export if name in ('request','payload','host') else self.root)/(name+'.json'))
            self.save(name,value)
        self.paths['started']=str(self.root/'started.json');self.save('started',{'started_at':'synthetic-time','request_sha256':self.digest('request')})
        self.paths['execution']=str(self.root/'execution.json');self.save('execution',{'started_at':'synthetic-time','status':'partial','exit_code':1,'usage':{'totalTokenCount':0},'candidate':self.paths['original_receipt'],'export':str(export)})
        self.plan={'schema_version':1,'status':'explicit_source_retention_decisions','workflow':self.workflow,
                   'request_sha256':self.digest('request'),'original_receipt_sha256':self.digest('original_receipt'),
                   'diagnostic_sha256':self.digest('diagnostic'),'decisions':[
                       {'id':self.target,'source_key':next(r['source_key'] for r in self.original['items'] if r['id']==self.target),
                        'rejected_candidate_text_sha256':retention.text_sha(bad),'decision':'retain_source',
                        'reviewer':'synthetic-reviewer','reason':'Reject the changed number; retain source.'}]}
        self.paths['author_decisions']=str(self.root/'decisions.json');self.save('author_decisions',self.plan)

    def save(self,name,value):Path(self.paths[name]).write_bytes(tool.json_bytes(value))
    def digest(self,name):return hashlib.sha256(Path(self.paths[name]).read_bytes()).hexdigest()
    def build(self):return retention.build(self.api,self.workflow,self.paths)

    def test_source_disposition_preserves_original_partial_and_all_other_rows(self):
        before={name:Path(p).read_bytes() for name,p in self.paths.items()}
        result=self.build()
        self.assertEqual(result['mode'],retention.MODE)
        self.assertEqual(result['status'],'pass')
        self.assertEqual(retention.verify(self.api,self.workflow,self.request,result).keys(),{self.target})
        for row in result['items']:
            if row['id']==self.target:
                self.assertEqual(row['text'],next(i['text'] for i in self.items if i['id']==self.target))
            else:
                self.assertEqual(row,next(i for i in self.original['items'] if i['id']==row['id']))
        self.assertEqual(before,{name:Path(p).read_bytes() for name,p in self.paths.items()})

    def test_explicit_retention_does_not_approve_other_slots(self):
        receipt=self.build();reviews=retention.required_reviews(self.api,self.workflow,self.request,receipt)
        checked=tool.adoption_check(self.workflow,self.request,receipt,reviews)
        self.assertEqual(checked['status'],'failed')
        self.assertNotIn('revised_source',checked)

    def test_complete_synthetic_review_rebuilds_and_checked_identity_consumes_provenance(self):
        receipt=self.build();required=retention.required_reviews(self.api,self.workflow,self.request,receipt)
        reviews=[approve(row) for row in receipt['items'] if row['id']!=self.target]+required
        whole=approve({'id':'/report-review','review_key':receipt['report_review_key']})
        whole['retained_source_review_key']=tool.retained_source_review_key(self.workflow,self.request,receipt,reviews)
        checked=tool.adoption_check(self.workflow,self.request,receipt,reviews+[whole])
        self.assertEqual(checked['status'],'pass')
        identity=tool.checked_report_identity(self.workflow,self.request,checked,export_document=receipt['document'])
        self.assertEqual(identity['response_derivation'],receipt['source_retention'])
        checked['items'][next(i for i,r in enumerate(checked['items']) if r['id']==self.target)]['text']='Tampered'
        with self.assertRaises(ValueError):tool.checked_report_identity(self.workflow,self.request,checked,export_document=receipt['document'])

    def test_missing_or_reused_author_review_is_rejected(self):
        receipt=self.build();required=retention.required_reviews(self.api,self.workflow,self.request,receipt)
        for reviews in [[],[dict(required[0],reviewer='different')],[dict(required[0],decision='approve')]]:
            with self.subTest(reviews=reviews),self.assertRaisesRegex(tool.Failed,'source_retention_review_missing_or_stale'):
                tool.adoption_check(self.workflow,self.request,receipt,reviews)

    def test_evidence_and_derived_candidate_drift_rejected(self):
        receipt=self.build()
        for name in self.paths:
            p=Path(self.paths[name]);old=p.read_bytes();p.write_bytes(old+b'\n')
            with self.subTest(name=name),self.assertRaises(ValueError):retention.verify(self.api,self.workflow,self.request,receipt)
            p.write_bytes(old)
        changed=deepcopy(receipt);changed['items'][0]['text']='changed'
        with self.assertRaises(ValueError):retention.verify(self.api,self.workflow,self.request,changed)

    def test_unknown_extra_duplicate_and_unlisted_decisions_rejected(self):
        original=deepcopy(self.plan)
        for rows in [[],[dict(original['decisions'][0],id='/unknown')],original['decisions']*2,
                     [dict(original['decisions'][0],source_key='wrong')],
                     [dict(original['decisions'][0],rejected_candidate_text_sha256='wrong')],
                     [dict(original['decisions'][0],reviewer='')]]:
            with self.subTest(rows=rows):
                self.save('author_decisions',dict(original,decisions=rows))
                with self.assertRaises((ValueError,tool.Failed)):self.build()

    def test_bad_json_missing_duplicate_and_incomplete_stop_are_not_recovered(self):
        original=deepcopy(self.diagnostic)
        malformed=['{',json.dumps({'items':[],'retained_ids':[]}),
                   json.dumps({'items':[],'retained_ids':['1','1']})]
        for text in malformed:
            self.save('diagnostic',dict(original,visible_text=text))
            self.save('author_decisions',dict(self.plan,diagnostic_sha256=self.digest('diagnostic')))
            with self.subTest(text=text),self.assertRaises((ValueError,tool.Failed)):self.build()
        self.save('diagnostic',dict(original,finish_reason='MAX_TOKENS'))
        with self.assertRaises(ValueError):self.build()

    def test_fixture_cannot_enter_live_source_retention(self):
        self.save('original_receipt',dict(self.original,mode='fixture'))
        with self.assertRaisesRegex(ValueError,'original_partial_live_required'):self.build()


if __name__=='__main__':unittest.main()
