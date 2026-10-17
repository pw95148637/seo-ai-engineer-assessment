"""Regression: v0.7 HB2 could not read Chinese URLs (http.client sends the request line as ASCII)."""
import http.client, unittest
from urllib.parse import quote, urlsplit
from src.research_core import ascii_url, wire_url, Failure
from src.scoring import score_run
from tests.test_lessons import B, KW, MAIN, LessonFixture, page
from tests.test_offpage import EXT, ROBOTS_OPEN, search_listing

RAW_PATH = EXT + '/評測/娛樂城推薦'
RAW_QUERY = EXT + '/search?q=3A娛樂城&lang=中文'


class AsciiOnly:
    """A transport that fails like http.client when a URL is not ASCII."""
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def __call__(self, url, timeout, cap):
        url.encode('ascii')
        self.calls.append(url)
        return self.inner(url, timeout, cap)


class EncodingTests(LessonFixture):
    def setUp(self):
        super().setUp()
        self.t.data.update({
            EXT + '/robots.txt': ROBOTS_OPEN,
            EXT + '/' + quote('評測') + '/' + quote('娛樂城推薦'): page('評測', '評測', [(B + '/hub/', '品牌')]),
            EXT + '/search?q=' + quote('3A娛樂城') + '&lang=' + quote('中文'): page('搜尋', '搜尋'),
            B + '/hub/' + quote('新頁'): page('新頁', '新頁')})
        self.strict = AsciiOnly(self.t)

    def test_http_client_rejects_a_raw_chinese_path_and_accepts_the_encoded_one(self):
        conn = http.client.HTTPSConnection('example.tw')
        with self.assertRaises(UnicodeEncodeError):
            conn.putrequest('GET', '/評測/娛樂城')
        conn = http.client.HTTPSConnection('example.tw')
        conn.putrequest('GET', urlsplit(ascii_url(urlsplit('https://example.tw/評測/娛樂城'))).path)

    def test_fetch_encodes_a_chinese_path_and_keeps_encoded_urls_unchanged(self):
        r = self.engine(transport=self.strict)
        x = self.fetch(r, B + '/hub/新頁')
        self.assertEqual(x['status'], 200)
        self.assertEqual(x['url'], B + '/hub/' + quote('新頁'))
        self.assertEqual(r.url(MAIN), MAIN)  # the v0.6 ledger stores encoded URLs; they must not be encoded twice
        self.assertEqual(r.url(B + '/a b'), B + '/a%20b')

    def test_offpage_reads_chinese_urls_listed_by_search(self):
        r = self.engine(transport=self.strict, searcher=search_listing([RAW_PATH, RAW_QUERY]))
        r.call('research_search', {'query': '品牌'})
        for url in (RAW_PATH, RAW_QUERY):
            x = r.call('research_offpage', {'url': url, 'purpose': 'does it mention the target?'})
            self.assertEqual(x.get('status'), 200, x)
        self.assertTrue(all(u.isascii() for u in self.strict.calls))
        r.call('research_finish', {'report': {'claims': [{'kind': 'unknown', 'text': 'x'}], 'actions': [
            {'action': 'a', 'reason': 'b'}]}})
        self.assertEqual(score_run(self.root, r.id, KW)['offpage_policy_violations'], [])

    def test_non_ascii_host_goes_out_with_idna(self):
        host = '例子.tw'
        self.assertEqual(wire_url(f'https://{host}/a?b=1'), 'https://' + host.encode('idna').decode() + '/a?b=1')
        self.assertEqual(wire_url(MAIN), MAIN)
        with self.assertRaises(Failure):
            wire_url('https://' + 'a' * 70 + '例.tw/')


if __name__ == '__main__':
    unittest.main()
