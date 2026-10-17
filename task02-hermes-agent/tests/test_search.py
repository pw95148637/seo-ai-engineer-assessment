import tempfile,unittest
from pathlib import Path
from src.research_core import Research,Limits
class SearchTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
    def engine(self,**kw):
        r=Research(Path(self.tmp.name),limits=Limits(interval=0),**kw);self.addCleanup(r.db.close);return r
    def test_index_evidence_distinct_and_hash_verified(self):
        r=self.engine(searcher=lambda q,n:{'success':True,'data':{'web':[{'url':'https://example.com','title':'Example','description':'indexed summary'}]}})
        x=r.call('research_search',{'query':'neutral example query'});self.assertEqual(x['source_type'],'search_index');self.assertEqual(r.evidence(x['evidence_id'])['method'],'search_index');self.assertEqual(r.requests,0)
    def test_search_budget(self):
        r=self.engine(searcher=lambda q,n:{'success':True,'data':{'web':[]}})
        for _ in range(5):r.call('research_search',{'query':'neutral'})
        self.assertEqual(r.call('research_search',{'query':'neutral'})['error'],'search_budget')
    def test_failure_not_promoted_as_direct_evidence(self):
        r=self.engine(searcher=lambda q,n:{'success':False,'error':'rate limited'});x=r.call('research_search',{'query':'neutral'})
        self.assertFalse(x['success']);self.assertEqual(r.evidence(x['evidence_id'])['status'],503)
    def test_missing_provider_no_network(self):
        r=self.engine();self.assertEqual(r.call('research_search',{'query':'neutral'})['error'],'search_unavailable')
