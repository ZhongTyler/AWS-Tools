"""Propose a reviewable article body from HTML the caller already acquired."""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit


ROOT = Path(__file__).resolve().parent
MAX_BYTES = 8 * 1024 * 1024
EXTRACTOR_VERSION = '2.3.1'
ACCESS_PROMPT = re.compile(
    r'^(?:(?:please\s+)?(?:sign in|log in|subscribe|register)\s+(?:to|for)\b|'
    r'(?:sign in|log in|login|member access|access denied|forbidden|page not found|'
    r'verify (?:that )?you are human|just a moment)(?:[.!…]?\s*$)|'
    r'请(?:先)?(?:登录|订阅)|(?:登录|订阅)后(?:才可|方可|查看|继续)|访问受限|验证码)',
    re.IGNORECASE,
)


def valid_source_url(url):
    parts = urlsplit(url)
    return parts.scheme in {'http', 'https'} and parts.hostname and parts.username is None and parts.password is None


def check_page(html, url, http_status):
    from bs4 import BeautifulSoup

    page = BeautifulSoup(html, 'html.parser')
    canonical = page.select_one('link[rel="canonical"][href]')
    canonical_url = urljoin(url, canonical['href']) if canonical else url
    canonical_url = canonical_url if valid_source_url(canonical_url) else url
    title = page.title.get_text(' ', strip=True) if page.title else ''
    if http_status is not None and not 200 <= http_status < 300:
        return 'http_status', title, canonical_url
    for node in page.select('script,style,noscript,template,nav,footer,aside,[hidden],[aria-hidden="true"]'):
        node.decompose()
    body = page.select_one('main,[role="main"]') or page.find('article') or page.body or page
    if body.get('aria-busy') == 'true' or body.select_one('article[aria-busy="true"],[role="main"][aria-busy="true"]'):
        return 'dynamic_shell', title, canonical_url
    headings = [node.get_text(' ', strip=True) for node in body.find_all(['h1', 'h2'])]
    paragraphs = [node.get_text(' ', strip=True) for node in body.find_all('p')]
    paragraphs = [text for text in paragraphs if text]
    if (body.select_one('input[type="password"]') or ACCESS_PROMPT.search(title) or
            any(ACCESS_PROMPT.search(text) for text in headings[:1]) or
            (paragraphs and ACCESS_PROMPT.search(paragraphs[0]))):
        return 'access_or_error_page', title, canonical_url
    blocks = body.find_all(['p', 'li', 'td', 'pre', 'blockquote'])
    if sum(len(node.get_text(' ', strip=True)) for node in blocks) < 80:
        return 'insufficient_visible_body', title, canonical_url
    return None, title, canonical_url


def propose(input_path, url, output, http_status):
    if not valid_source_url(url):
        raise ValueError('Provide the original HTTP(S) URL without embedded credentials')
    with input_path.open('rb') as file:
        original = file.read(MAX_BYTES + 1)
    if not original or len(original) > MAX_BYTES:
        raise ValueError('Input HTML must be between 1 byte and 8 MiB')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Preserve existing output; choose an empty directory')
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'source.html').open('xb') as file:
        file.write(original)
    result = {
        'status': 'manual_source_check', 'source_url': url, 'http_status': http_status,
        'source_file': 'source.html', 'source_sha256': hashlib.sha256(original).hexdigest(),
        'recorded_at': datetime.now(timezone.utc).isoformat(), 'candidate': None,
        'source_review_required': ['page identity and visible body', 'figure captions and images',
                                   'tables and units', 'key links and source evidence'],
    }
    try:
        reason, title, canonical = check_page(original, url, http_status)
        result.update(title=title, canonical_url=canonical, reason=reason)
        if reason is None:
            actual = version('trafilatura')
            result['extractor_version'] = actual
            if actual != EXTRACTOR_VERSION:
                result['reason'] = 'extractor_version_mismatch'
            else:
                from trafilatura import extract
                text = extract(original, url=url, output_format='markdown', include_tables=True,
                               include_links=True, include_images=True, include_comments=False)
                if text and text.strip():
                    candidate = text.strip() + '\n'
                    (output / 'candidate.md').write_text(candidate, encoding='utf-8', newline='\n')
                    result.update(status='candidate_for_review', candidate='candidate.md',
                                  candidate_sha256=hashlib.sha256(candidate.encode('utf-8')).hexdigest())
                else:
                    result['reason'] = 'empty_extraction'
    except ImportError:
        result['reason'] = 'dependency_unavailable'
    except Exception as error:
        result.update(reason='extraction_failed', error_type=type(error).__name__)
    (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'reason': result['reason'], 'output': str(output)}, ensure_ascii=False))
    return 0 if result['status'] == 'candidate_for_review' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-html', type=Path, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--http-status', type=int, choices=range(100, 600), metavar='STATUS')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path[:0] = [str(ROOT / 'runtime' / 'body-candidate'), str(ROOT / 'runtime')]
    try:
        return propose(args.input_html, args.url, args.output, args.http_status)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
