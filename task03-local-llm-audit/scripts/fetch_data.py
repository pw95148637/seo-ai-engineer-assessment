"""Restore the company's 20 SEO snippets and the 12/8 split when a copy of this repo omits the CSV files.

python scripts/fetch_data.py            (Windows: set PYTHONUTF8=1)
Files that already exist are only checked against their recorded sha256, never overwritten, and nothing is downloaded.
A missing source file is rebuilt from the company's public sheet (Sheet1 exported as CSV, plus the UTF-8 BOM and final
CRLF of the original download). The split is rebuilt with the seed in data/split-manifest.json, and the copies that the
offline comparison reads inside kaggle-retrieved/ are restored. Any hash mismatch stops the script.
"""
import csv
import hashlib
import io
import json
import random
import sys
import urllib.request
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
DATA = TASK / 'data'
EXPORT = 'https://docs.google.com/spreadsheets/d/198L8PDlajqKmSsz-ScUti7tYUnyTyUYBAa3nJWfyzCQ/export?format=csv&gid=0'
# Hashes of the files used in the Kaggle runs (holdout8 is also embedded in the eval notebook and compare_holdout.py).
SHA = {
    'train12.csv': '7dfa0c9f6008d827cde2287d93c5a08bf5037d7db4ae5f14a9fbc02a2b9958e2',
    'holdout8.csv': '818b491f19541c7703cc311afd498fe1169c223a1c03fb4902e275b46b7a9106',
    'bundle_train12.csv': '4193d94c59bd8b3d7bdde8583b40aef210d6f2a9825f582ca04094edfe1e0c2c',
}
EVAL_DATA = TASK / 'kaggle-retrieved' / 'soulo-work03-v3-eval' / 'work03' / 'data'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def need(path, data, expected):
    """Write data to path when absent; either way the bytes on disk must match the expected hash."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        state = 'restored'
    else:
        state = 'present'
    got = sha(path.read_bytes())
    if got != expected:
        sys.exit(f'{path.relative_to(TASK)}: sha256 {got[:16]} does not match the recorded {expected[:16]}; stop')
    print(f'{state}: {path.relative_to(TASK)} ({got[:12]})')


def main():
    manifest = json.loads((DATA / 'split-manifest.json').read_text(encoding='utf-8'))
    src_path = DATA / 'seo-diagnostic-samples.csv'
    if src_path.exists():
        src = src_path.read_bytes()
    else:
        with urllib.request.urlopen(EXPORT, timeout=30) as r:
            src = b'\xef\xbb\xbf' + r.read() + b'\r\n'
    need(src_path, src, manifest['source_sha256'])

    rows = list(csv.DictReader(io.StringIO(src_path.read_bytes().decode('utf-8-sig'))))
    shuffled = rows.copy()
    random.Random(manifest['seed']).shuffle(shuffled)

    def dump(part, as_in_bundle=False):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator='\n' if as_in_bundle else '\r\n')
        w.writeheader()
        w.writerows(part)
        return buf.getvalue().encode('utf-8' if as_in_bundle else 'utf-8-sig')

    train, holdout = shuffled[:12], shuffled[12:]
    assert [r['ID'] for r in train] == manifest['train_ids'] and [r['ID'] for r in holdout] == manifest['holdout_ids']
    need(DATA / 'train12.csv', dump(train), SHA['train12.csv'])
    need(DATA / 'holdout8.csv', dump(holdout), SHA['holdout8.csv'])
    # The eval kernel copied the private dataset file as is; the notebooks wrote train12 as text (no BOM, LF endings).
    need(EVAL_DATA / 'holdout8.csv', dump(holdout), SHA['holdout8.csv'])
    for d in sorted((TASK / 'kaggle-retrieved').glob('*/work03/data')):
        need(d / 'train12.csv', dump(train, as_in_bundle=True), SHA['bundle_train12.csv'])
    print('PASS: company data and the 12/8 split match the recorded hashes')


if __name__ == '__main__':
    main()
