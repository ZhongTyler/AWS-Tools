"""Offline synthetic article/fallback contracts; optional extractor is never installed here."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import body_candidate as body

HTML = b'<html><title>Article</title><body><article><h1>Article</h1>' + b'<p>This is a sufficiently long paragraph with original evidence and a useful explanation.</p>' * 12 + b'</article></body></html>'

class BodyContracts(unittest.TestCase):
    def run_case(self, html=HTML, status=200, patches=()):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'input.html'; source.write_bytes(html)
            with contextlib.ExitStack() as stack:
                for target,value in patches:stack.enter_context(patch(target,value))
                with contextlib.redirect_stdout(io.StringIO()): code=body.propose(source,'https://example.org/article',root/'output',status)
            result=json.loads((root/'output/manifest.json').read_text(encoding='utf8'))
            self.assertEqual((root/'output/source.html').read_bytes(),html)
            self.assertEqual(result['source_sha256'],hashlib.sha256(html).hexdigest())
            return code,result

    def test_access_status_busy_shell_and_short_body_return_to_source(self):
        for html,status,reason in [(HTML,403,'http_status'),(b'<title>Log in</title><body><p>Sign in to continue</p></body>',200,'access_or_error_page'),(b'<body aria-busy="true"></body>',200,'dynamic_shell'),(b'<body><p>short</p></body>',200,'insufficient_visible_body')]:
            code,result=self.run_case(html,status)
            self.assertEqual(code,2);self.assertEqual(result['reason'],reason)

    def test_version_mismatch_preserves_input_and_has_no_candidate(self):
        code,result=self.run_case(patches=[('body_candidate.version',lambda _: 'different')])
        self.assertEqual(code,2);self.assertEqual(result['reason'],'extractor_version_mismatch');self.assertIsNone(result['candidate'])

    def test_missing_optional_dependency_preserves_source(self):
        def absent(_):raise ImportError('synthetic missing optional dependency')
        code,result=self.run_case(patches=[('body_candidate.version',absent)])
        self.assertEqual(code,2);self.assertEqual(result['reason'],'dependency_unavailable')

    def test_reject_credentials_empty_oversize_and_nonempty_output(self):
        self.assertFalse(body.valid_source_url('https://user:password@example.org/'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input.html';source.write_bytes(b'')
            with self.assertRaises(ValueError):body.propose(source,'https://example.org/',root/'output',None)
            source.write_bytes(HTML);target=root/'output';target.mkdir();(target/'keep').write_bytes(b'keep')
            with self.assertRaises(ValueError):body.propose(source,'https://example.org/',target,None)
            self.assertEqual((target/'keep').read_bytes(),b'keep')
            source.write_bytes(b'x'*(body.MAX_BYTES+1))
            with self.assertRaises(ValueError):body.propose(source,'https://example.org/',root/'large',None)

if __name__=='__main__':unittest.main()
