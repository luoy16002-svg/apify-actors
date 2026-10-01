import asyncio
import copy
import json
from pathlib import Path
import pytest
from src.common import ResultSink,SchemaError,SourceError
from src.helpers import InputError
from src.main import normalize_input,collect,fetch_page,next_cursor,matches,uk_window,ENDPOINTS
from src.parser import parse_ocds,parse_ted,ted_deadlines,source_date
from test_common import FakeActor

FIX=Path(__file__).parent/'fixtures'
FTS=json.loads((FIX/'find-tender.json').read_text(encoding='utf-8'))
CF=json.loads((FIX/'contracts-finder.json').read_text(encoding='utf-8'))
TED=json.loads((FIX/'ted-fields.json').read_text(encoding='utf-8'))

def stats(sources):return {'pagesFetched':0,'filtered':0,'skippedMalformed':0,'sources':{s:{'pages':0,'items':0} for s in sources},'sourceErrors':[],'stopReason':'source_exhausted'}

def cfg(**kwargs):return normalize_input({'publishedFrom':'2026-09-30','publishedTo':'2026-10-01',**kwargs})

def test_real_uk_fixtures_preserve_identity_and_missing_estimate():
    ft=parse_ocds(FTS['releases'][0],'find-tender');cf=parse_ocds(CF['releases'][0],'contracts-finder')
    assert ft['sourceId']=='092612-2026' and ft['ocid']=='ocds-h6vhtk-0510f8'
    assert ft['estimatedValue'] is None and ft['noticeType']=='UK15'
    assert ft['publishedAt']=='2026-09-30T22:30:39Z'
    assert cf['estimatedValue']==153673.47 and cf['currency']=='GBP' and cf['cpvCodes']==['50700000']
    assert cf['officialUrl']=='https://www.contractsfinder.service.gov.uk/Notice/ea8722fc-4f04-4469-a469-04aa843d36c7'

def test_real_ted_estimate_publication_precision_and_deadline():
    row=parse_ted(TED['notices'][1])
    assert row['estimatedValue']==3243807.59 and row['currency']=='RON'
    assert row['publishedAt']=='2026-09-30' and row['buyerCountry']=='ROU'
    assert row['deadline']=='2026-10-15T12:00:00Z'
    assert len(row['cpvCodes'])==2 and row['sourceId']=='05863400-bed8-4225-9269-fbbf4d17236a'

def test_awards_and_lot_values_are_not_procedure_estimates():
    raw=copy.deepcopy(CF['releases'][0]);raw['tender'].pop('value');raw['awards']=[{'value':{'amount':999,'currency':'GBP'}}]
    row=parse_ocds(raw,'contracts-finder');assert row['estimatedValue'] is None
    ted=copy.deepcopy(TED['notices'][0]);ted['total-value']='888';ted['estimated-value-lot']=['99','100']
    assert parse_ted(ted)['estimatedValue'] is None

def test_multilot_deadlines_do_not_guess_array_pairings():
    raw={'deadline-receipt-tender-date-lot':['2026-10-15+02:00','2026-10-16+03:00'],'deadline-receipt-tender-time-lot':['09:00:00+03:00','17:00:00+02:00']}
    assert ted_deadlines(raw)==['2026-10-15','2026-10-16']

@pytest.mark.parametrize('data',[None,{'sources':[]},{'sources':['austender']},{'minimumValue':10},{'minimumValue':float('nan')},{'valueCurrency':'EURO'},{'cpvCodes':['abc']},{'cpvCodes':['123-4']},{'publishedFrom':'2026-02-30'},{'publishedFrom':'2026-10-02','publishedTo':'2026-10-01'},{'maxResults':True}])
def test_typed_errors(data):
    with pytest.raises(InputError):normalize_input(data)

def test_local_filters_and_currency():
    row=parse_ocds(CF['releases'][0],'contracts-finder')
    assert matches(row,cfg(keywords=['lift'],cpvCodes=['50'],minimumValue=100000,valueCurrency='GBP'))
    assert not matches(row,cfg(minimumValue=200000,valueCurrency='GBP'))
    assert not matches(row,cfg(valueCurrency='EUR'))
    assert not matches(parse_ocds(FTS['releases'][0],'find-tender'),cfg(minimumValue=1,valueCurrency='GBP'))

def test_fts_update_upper_bound_is_independent_of_publication_cutoff():
    config=cfg();config['scanAsOf']='2026-10-20T12:00:00Z'
    assert uk_window(config,'find-tender')['updatedTo'].startswith('2026-10-21')
    assert uk_window(config,'contracts-finder')['publishedTo'].startswith('2026-10-02')

def test_cursor_must_stay_on_official_endpoint():
    assert next_cursor(FTS,ENDPOINTS['find-tender'])
    with pytest.raises(SchemaError):next_cursor({'links':{'next':'https://other.example/?cursor=x'}},ENDPOINTS['find-tender'])
    with pytest.raises(SchemaError):next_cursor({'links':{'next':ENDPOINTS['find-tender']}},ENDPOINTS['find-tender'])

class Client:
    def __init__(self,fail=None):self.calls=[];self.fail=fail
    async def get_json(self,url,params=None,**kwargs):
        self.calls.append((url,params,kwargs))
        source=next(k for k,v in ENDPOINTS.items() if v==url)
        if source==self.fail:raise SourceError('Source unavailable.')
        data=copy.deepcopy({'find-tender':FTS,'contracts-finder':CF,'ted':TED}[source])
        data['links']={};data['iterationNextToken']=None
        if source=='ted':data['notices']=data['notices'][:1]
        return data

def test_all_sources_round_robin_budget_dedupe_and_attribution():
    config=cfg(maxResults=3,pageSize=1);client=Client();actor=FakeActor()
    result=asyncio.run(collect(config,client,ResultSink(actor,3),stats(config['sources'])))
    assert [r['source'] for r in actor.rows]==['find-tender','contracts-finder','ted']
    assert result['pagesFetched']==3 and all(r['licenseUrl'] and r['attribution'] for r in actor.rows)
    assert client.calls[-1][2]['method']=='POST'
    assert client.calls[-1][2]['json_body']['paginationMode']=='ITERATION'

def test_partial_failure_is_visible_and_all_failed_raises():
    config=cfg(maxResults=3);st=stats(config['sources']);actor=FakeActor()
    asyncio.run(collect(config,Client('ted'),ResultSink(actor,3),st))
    assert len(actor.rows)==2 and st['stopReason']=='partial_source_errors'
    config=cfg(sources=['ted'])
    with pytest.raises(SourceError):asyncio.run(collect(config,Client('ted'),ResultSink(FakeActor(),3),stats(config['sources'])))

def test_repeated_page_fails_and_zero_budget_is_quiet():
    config=cfg(sources=['find-tender']);state={'cursor':None,'seenCursors':set(),'seenPages':set()};client=Client()
    asyncio.run(fetch_page('find-tender',state,config,client,1))
    with pytest.raises(SchemaError,match='repeated a page'):asyncio.run(fetch_page('find-tender',state,config,client,1))
    client=Client();asyncio.run(collect(config,client,ResultSink(FakeActor(budget=0),3),stats(config['sources'])))
    assert client.calls==[]

def test_ocds_and_ted_cursors_are_forwarded_without_changing_queries():
    from src.main import fetch_page
    async def run(source,first,second):
        config=cfg(sources=[source]);state={'cursor':None,'seenCursors':set(),'seenPages':set()}
        class PagingClient:
            def __init__(self):self.calls=[]
            async def get_json(self,url,params=None,**kwargs):
                self.calls.append((params,kwargs))
                return first if len(self.calls)==1 else second
        client=PagingClient()
        rows,more=await fetch_page(source,state,config,client,1);assert rows and more
        await fetch_page(source,state,config,client,1)
        if source=='ted':
            assert client.calls[1][1]['json_body']['iterationNextToken']=='opaque-token'
            assert client.calls[0][1]['json_body']['query']==client.calls[1][1]['json_body']['query']
        else:assert client.calls[1][0]['cursor']==next_cursor(first,ENDPOINTS[source])
    second=copy.deepcopy(FTS);second['links']={};second['releases'][0]['id']='092613-2026'
    asyncio.run(run('find-tender',FTS,second))
    asyncio.run(run('ted',{'notices':[TED['notices'][0]],'iterationNextToken':'opaque-token'}, {'notices':[TED['notices'][1]],'iterationNextToken':None}))

def test_unbalanced_deadline_arrays_preserve_date_precision():
    raw={'deadline-receipt-tender-date-lot':['2026-10-15+02:00','2026-10-15+02:00'],'deadline-receipt-tender-time-lot':['09:00:00+02:00']}
    assert ted_deadlines(raw)==['2026-10-15']
