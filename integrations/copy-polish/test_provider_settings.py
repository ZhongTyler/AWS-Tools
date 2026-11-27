"""Offline configuration and mocked transport; never a live provider check."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs,quote
import provider_settings
from test_contract import tool,request,response


class RecipientProvider(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='recipient-provider-config-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.package=self.root/'package';self.package.mkdir();self.diagnostic=self.root/'private';self.diagnostic.mkdir();self.path=self.root/'provider.json'
        self.value={'schema_version':1,'api_family':'gemini-generate-content','origin':'https://provider.example.test',
                    'model':'recipient/示例 model','key_env':'RECIPIENT_API_KEY','diagnostic_root':str(self.diagnostic)}

    def save(self,value=None):self.path.write_text(json.dumps(self.value if value is None else value),encoding='utf8')

    def test_explicit_settings_are_readonly_and_do_not_read_credentials(self):
        self.save();before=self.path.read_bytes()
        with patch.object(os.environ,'get',side_effect=AssertionError('No credential reads during config loading')):
            result=provider_settings.load(self.path,self.package)
        self.assertEqual(result,self.value);self.assertEqual(self.path.read_bytes(),before)

    def test_no_embedded_secrets_unknown_family_or_implicit_model(self):
        for change in [{'api_key':'do-not-store'},{'api_family':'other-protocol'},{'model':''},{'key_env':'PATH'},{'schema_version':True}]:
            with self.subTest(change=change):
                self.save(dict(self.value,**change))
                with self.assertRaises(ValueError):provider_settings.load(self.path,self.package)

    def test_provider_origin_rejects_paths_credentials_query_fragment_and_insecure_scheme(self):
        for origin in ['http://provider.test','https://user:secret@provider.test','https://provider.test/path',
                       'https://provider.test?key=x','https://provider.test#fragment',' https://provider.test',
                       'https://provider.test:0','https://provider.test:99999','https://bad%40provider.test']:
            with self.subTest(origin=origin):
                self.save(dict(self.value,origin=origin))
                with self.assertRaises(ValueError):provider_settings.load(self.path,self.package)

    def test_config_and_diagnostics_cannot_live_in_immutable_package(self):
        self.save();inside=self.package/'provider.json';inside.write_bytes(self.path.read_bytes())
        with self.assertRaises(ValueError):provider_settings.load(inside,self.package)
        self.save(dict(self.value,diagnostic_root=str(self.package)))
        with self.assertRaises(ValueError):provider_settings.load(self.path,self.package)

    def test_mocked_wire_uses_only_recipient_origin_model_and_key(self):
        self.save();value=provider_settings.load(self.path,self.package);secret='synthetic-secret-only';body=json.dumps(response([{'id':'1','text':'Still being made.'}])).encode()
        with patch.multiple(tool,MODEL=value['model'],RELAY=value['origin'],RELAYS={value['origin']},KEY_ENV=value['key_env']), \
                patch.dict(os.environ,{value['key_env']:secret}),patch.object(tool.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=contextlib.nullcontext(io.BytesIO(body))
            tool.generate({'contents':[]},4)
            self.assertEqual(opener.return_value.open.call_count,1)
            sent=opener.return_value.open.call_args.args[0];url=urlsplit(sent.full_url)
            self.assertEqual(url.netloc,'provider.example.test')
            self.assertEqual(url.path,'/v1beta/models/'+quote(value['model'],safe='')+':generateContent')
            self.assertEqual(parse_qs(url.query),{'key':[secret]});self.assertNotIn(secret.encode(),sent.data)

    def test_live_cli_rejects_missing_provider_before_transport(self):
        source=self.root/'request.json';source.write_text(json.dumps(request('website','Still in development.')))
        argv=['run.py','candidate','personal-site-copy','--request',str(source),'--live']
        with (patch.object(sys,'argv',argv),
              patch.object(tool,'generate',side_effect=AssertionError('No send')),
              contextlib.redirect_stdout(io.StringIO()) as output):
            code=tool.main()
        self.assertEqual(code,2);self.assertEqual(json.loads(output.getvalue())['error'],'provider_config_required')

    def test_saved_batch_model_identity_is_not_tied_to_current_live_configuration(self):
        from test_knowledge_batch import api,batch,mixed_receipt,disposition_reviews
        value=batch()
        with patch.object(api,'MODEL','gemini-fixture-model'):
            receipt=mixed_receipt(value)
        # A different or absent live configuration must not require a new call.
        with patch.object(api,'MODEL','offline-unconfigured'):
            reviews=disposition_reviews(value,receipt)
            checked=api.adoption_check('knowledge',value,receipt,reviews)
            self.assertEqual(checked['status'],'pass')
            changed=json.loads(json.dumps(receipt));changed['requested_model']='gemini-changed-after-review'
            with self.assertRaises(api.Failed):api.adoption_check('knowledge',value,changed,reviews)


if __name__=='__main__':unittest.main()
