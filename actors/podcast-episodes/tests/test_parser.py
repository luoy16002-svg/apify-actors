import asyncio
from pathlib import Path
import httpx
import pytest
from src.common import ResultSink,SchemaError,SourceError
from src.helpers import InputError
from src.main import normalize_input,collect
from src.parser import parse_feed,parse_episode,duration,explicit
from test_common import FakeActor

FEED=(Path(__file__).parent/'fixtures/synthetic-feed.xml').read_bytes()
URL='https://example.org/feed.xml'

def stats():return {'pagesFetched':0,'showsFetched':0,'filtered':0,'skippedMalformed':0,'feedsWithParseWarnings':0,'sourceErrors':[],'stopReason':'source_exhausted'}

def test_namespace_variants_and_nullable_fields():
    show,entries,bozo=parse_feed(FEED,URL,{'collectionId':123,'genres':['Science']})
    first=parse_episode(entries[0],show);second=parse_episode(entries[1],show)
    assert show['showTitle']=='Fixture Show' and show['showId']=='123'
    assert first['durationSeconds']==3723 and first['seasonNumber']==2 and first['episodeNumber']==10
    assert first['publishedAt']=='2026-09-30T19:30:00Z' and first['explicit'] is True
    assert first['description']=='Hello world.'
    assert second['publishedAt'] is None and second['explicit'] is False
    assert second['audioUrl']=='https://example.org/two.mp3'
    assert second['description']=='Second episode'

@pytest.mark.parametrize('value,expected',[('3:05',185),('1:02:03',3723),('00:99',None),('PT1H2M3S',3723),('93',93),(93.9,93),('bad',None),('-1',None),(True,None)])
def test_duration(value,expected):assert duration(value)==expected

@pytest.mark.parametrize('data',[None,{}, {'shows':['https://example.org/id123']},{'feedUrls':['http://localhost/feed']},{'shows':['123'],'maxEpisodesPerShow':0},{'shows':['123'],'publishedAfter':'yesterday'},{'shows':['123'],'country':'USA'}])
def test_typed_input(data):
    with pytest.raises(InputError):normalize_input(data)

def test_malformed_feed_recovers_entries_and_html_is_not_a_feed():
    broken=FEED.replace(b'Hello <b>world</b>.',b'Hello & world')
    show,entries,bozo=parse_feed(broken,URL)
    assert len(entries)==2
    with pytest.raises(SchemaError):parse_feed(b'<html>not RSS</html>',URL)
    with pytest.raises(SchemaError):parse_feed(b'<!DOCTYPE rss><rss/>',URL)

def test_atom_dates_and_fallback_identity():
    raw=b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><entry><title>One</title><updated>2026-09-30T01:00:00Z</updated><link rel="enclosure" href="https://example.org/a.mp3" type="audio/mpeg"/></entry></feed>'
    show,entries,_=parse_feed(raw,URL)
    row=parse_episode(entries[0],show)
    assert row['publishedAt']=='2026-09-30T01:00:00Z' and row['audioUrl'].endswith('a.mp3')
    assert row['episodeKey']==parse_episode(entries[0],show)['episodeKey']

class Client:
    def __init__(self,fail=False,content=FEED):self.requests=[];self.fail=fail;self.content=content
    async def get_json(self,url,params=None):
        self.requests.append(url)
        if '/search' in url and self.fail:raise SourceError('robots.txt disallows this source path.')
        return {'results':[{'kind':'podcast','collectionId':123,'feedUrl':URL}]}
    async def request(self,url):
        self.requests.append(url)
        return httpx.Response(200,content=self.content,request=httpx.Request('GET',url))

def test_filter_before_save_dedup_discovery_and_show_cap():
    cfg=normalize_input({'shows':['123'],'feedUrls':[URL],'maxShows':2,'publishedAfter':'2026-09-30','maxEpisodesPerShow':3})
    actor=FakeActor();client=Client();result=asyncio.run(collect(cfg,client,ResultSink(actor,6),stats()))
    assert len(actor.rows)==1 and result['filtered']==1 and client.requests.count(URL)==1

def test_duplicate_episodes_do_not_consume_per_show_limit():
    one=FEED[FEED.index(b'<item>'):FEED.index(b'</item>')+7]
    content=FEED.replace(one,one+one)
    actor=FakeActor();cfg=normalize_input({'feedUrls':[URL],'maxEpisodesPerShow':2})
    sink=ResultSink(actor,10);asyncio.run(collect(cfg,Client(content=content),sink,stats()))
    assert len(actor.rows)==2 and sink.duplicates==1

def test_mixed_search_failure_is_explicit_partial_result():
    actor=FakeActor();st=stats()
    cfg=normalize_input({'feedUrls':[URL],'searchTerms':['science'],'maxShows':2})
    asyncio.run(collect(cfg,Client(fail=True),ResultSink(actor,20),st))
    assert len(actor.rows)==2 and st['stopReason']=='partial_source_errors' and st['sourceErrors'][0]['stage']=='search'

def test_search_only_denial_fails_and_budget_zero_skips_network():
    cfg=normalize_input({'searchTerms':['science']})
    with pytest.raises(SourceError):asyncio.run(collect(cfg,Client(fail=True),ResultSink(FakeActor(),20),stats()))
    client=Client();asyncio.run(collect(cfg,client,ResultSink(FakeActor(budget=0),20),stats()))
    assert client.requests==[]

def test_published_after_is_exclusive():
    cfg=normalize_input({'feedUrls':[URL],'publishedAfter':'2026-09-30T19:30:00.000Z'})
    actor=FakeActor();asyncio.run(collect(cfg,Client(),ResultSink(actor,20),stats()))
    assert not actor.rows

def test_numeric_guids_remain_distinct_structured_identifiers():
    show,entries,_=parse_feed(FEED,URL)
    first=dict(entries[0]);second=dict(entries[0]);first['id']='1234567890';second['id']='1234567891'
    a,b=parse_episode(first,show),parse_episode(second,show)
    assert a['guid']=='1234567890' and a['episodeKey']!=b['episodeKey']
