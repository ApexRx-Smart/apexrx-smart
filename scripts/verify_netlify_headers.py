"""Verify FE-03 HTTP security headers on the real Netlify deployment.

Use after deployment:
    python scripts/verify_netlify_headers.py https://your-site.netlify.app
This script never changes the website.
"""
import argparse
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

EXPECTED = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    'X-Frame-Options': 'DENY',
}


def run(url):
    address = urlsplit(url)
    if address.scheme != 'https' or not address.hostname:
        print('ERROR: enter an HTTPS deployment URL, e.g. https://your-site.netlify.app')
        return 2
    root = address.scheme + '://' + address.netloc + '/'
    failures = 0
    for path in ('', 'pharmacies.html', 'patients.html'):
        target = urljoin(root, path)
        try:
            with urlopen(Request(target, method='HEAD', headers={'User-Agent':'ApexRx-FE03-Verification/1.0'}), timeout=12) as response:
                if response.status != 200:
                    print('FAIL', path or '/', 'status:', response.status)
                    failures += 1
                for key, required in EXPECTED.items():
                    actual = response.headers.get(key)
                    if actual != required:
                        print('FAIL', path or '/', key, 'expected', required, 'got', actual)
                        failures += 1
        except (HTTPError, URLError, TimeoutError) as error:
            print('FAIL', target, type(error).__name__)
            failures += 1
        else:
            if failures == 0: print('PASS', target)
    if failures:
        print('FAIL:', failures, 'checks need attention; never close FE-03 before rechecking the live site.')
        return 1
    print('PASS: all three deployed pages expose the FE-03 baseline headers.')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='HTTPS origin of the deployed static ApexRx site')
    sys.exit(run(parser.parse_args().url))
