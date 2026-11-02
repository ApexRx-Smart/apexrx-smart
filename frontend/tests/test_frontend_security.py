"""FE-01/02/03 security regression checks for the ApexRx static frontend.

Run from any directory: python frontend/tests/test_frontend_security.py
This is a local source audit; it cannot inspect deployed headers or Git history.
"""
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

FRONTEND = Path(__file__).resolve().parents[1]
ROOT = FRONTEND.parent
REQUIRED_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'X-Frame-Options': 'DENY',
}


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external_tabs = []
        self.inline_handlers = []
    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'a' and attributes.get('target') == '_blank':
            self.external_tabs.append(attributes)
        for k, v in attrs:
            if re.fullmatch(r'on[a-z]+', k or '', re.I):
                self.inline_handlers.append((tag, k))


class FrontendSecurityTests(unittest.TestCase):
    def test_netlify_publish_folder(self):
        self.assertRegex((ROOT / 'netlify.toml').read_text(), r'(?m)^\s*publish\s*=\s*"frontend"')
        self.assertTrue((FRONTEND / '_headers').is_file())

    def test_netlify_baseline_headers(self):
        lines = (FRONTEND / '_headers').read_text().splitlines()
        self.assertIn('/*', lines)
        headers = {}
        for line in lines:
            if ':' in line and not line.lstrip().startswith('#'):
                key, value = line.strip().split(':', 1)
                headers[key] = value.strip()
        for name, expected in REQUIRED_HEADERS.items():
            self.assertEqual(expected, headers.get(name), name)
        self.assertNotIn('Content-Security-Policy', headers)  # Defer CSP until dependencies are audited.

    def test_all_new_tabs_have_noopener_and_noreferrer(self):
        count = 0
        for path in FRONTEND.glob('*.html'):
            parser = HTMLLinks();parser.feed(path.read_text(encoding='utf-8'))
            self.assertFalse(parser.inline_handlers, str(path))
            for link in parser.external_tabs:
                count += 1
                self.assertTrue({'noopener', 'noreferrer'} <= set(link.get('rel', '').split()), (path, link))
        self.assertGreater(count, 0)

    def test_no_html_parsing_sinks_in_frontend_js(self):
        for path in (FRONTEND / 'js').glob('*.js'):
            text = path.read_text(encoding='utf-8')
            for suspicious in (r'\binnerHTML\b', r'\bouterHTML\b', r'\binsertAdjacentHTML\s*\(', r'\bdocument\.write\s*\(', r'\beval\s*\('):
                self.assertIsNone(re.search(suspicious, text), (path.name, suspicious))

    def test_no_high_confidence_credential_patterns_in_public_assets(self):
        patterns = [
            (r'AIza[0-9A-Za-z_-]{35}', 'Google API browser key'),
            (r'AKIA[0-9A-Z]{16}', 'AWS access key'),
            (r'gh[pousr]_[a-zA-Z0-9]{30,}', 'GitHub token'),
            (r'sk_(?:live|test)_[0-9A-Za-z]{20,}', 'Stripe secret'),
            (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', 'private key'),
        ]
        for path in FRONTEND.rglob('*'):
            if path.suffix not in ('.html', '.js', '.css', '.json') or '/tests/' in str(path):
                continue
            text = path.read_text(encoding='utf-8')
            for expression, kind in patterns:
                self.assertIsNone(re.search(expression, text), (path.relative_to(FRONTEND), kind))

    def test_no_prepopulated_google_maps_browser_key(self):
        for filename in ('google-maps-config.js', 'google-maps-local.js'):
            path = FRONTEND / 'js' / filename
            if filename == 'google-maps-local.js' and not path.exists():
                continue
            content = path.read_text(encoding='utf-8')
            # The deployed config and optional local override must contain no live value.
            self.assertNotRegex(content, r'APEXRX_GOOGLE_MAPS_API_KEY\s*=\s*["\'][^"\']{8,}["\']')


if __name__ == '__main__':
    unittest.main(verbosity=2)
