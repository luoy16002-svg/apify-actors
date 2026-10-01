"""Serial round-robin collection from the three official reuse APIs."""
from collections import deque
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit,parse_qs
import math
import re
from .common import LOG,ResultSink,SchemaError,SourceError,number,utc_now
from .helpers import (InputError,PublicClient,common_input,date_range,finish,in_range,require_int,
                      require_string,rows_field,string_list)
from .parser import parse_ocds,parse_ted

ENDPOINTS={
    'find-tender':'https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages',
    'contracts-finder':'https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search',
    'ted':'https://api.ted.europa.eu/v3/notices/search',
}
TED_FIELDS=['publication-number','notice-identifier','notice-title','buyer-name','buyer-country',
            'organisation-country-buyer','publication-date','notice-type','classification-cpv','procedure-type',
            'estimated-value-proc','estimated-value-cur-proc','deadline-receipt-tender-date-lot',
            'deadline-receipt-tender-time-lot','description-proc','description-lot']

def normalize_input(data):
    cfg=common_input(data)
    sources=string_list(data,'sources',list(ENDPOINTS),limit=3)
    if not sources or any(s not in ENDPOINTS for s in sources):
        raise InputError('sources must contain find-tender, contracts-finder and/or ted.')
    dated=dict(data)
    today=datetime.now(timezone.utc).date()
    if not dated.get('publishedFrom'):dated['publishedFrom']=(today-timedelta(days=7)).isoformat()
    if not dated.get('publishedTo'):dated['publishedTo']=today.isoformat()
    for key in ['publishedFrom','publishedTo']:
        if not isinstance(dated[key],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',dated[key]):
            raise InputError(f'{key} must be a YYYY-MM-DD date.')
    start,end=date_range(dated,'publishedFrom','publishedTo')
    codes=[]
    for value in string_list(data,'cpvCodes',limit=50):
        if not re.fullmatch(r'\d{2,8}(?:-\d)?',value) or '-' in value and len(value)!=10:
            raise InputError('CPV filters must be 2-8 digit prefixes or an 8-digit CPV with check digit.')
        codes.append(value.split('-')[0])
    minimum=data.get('minimumValue',0)
    if isinstance(minimum,bool) or not isinstance(minimum,(int,float)) or number(minimum) is None or minimum<0:
        raise InputError('minimumValue must be a nonnegative finite number.')
    currency=require_string(data,'valueCurrency').upper()
    if currency and not re.fullmatch('[A-Z]{3}',currency):raise InputError('valueCurrency must be a three-letter currency code.')
    if minimum>0 and not currency:raise InputError('minimumValue requires valueCurrency; currencies are never converted or compared together.')
    cfg.update(sources=sources,keywords=string_list(data,'keywords'),cpvCodes=list(dict.fromkeys(codes)),
               publishedFrom=start,publishedTo=end,minimumValue=float(minimum),valueCurrency=currency,
               maxResults=require_int(data,'maxResults',100,1,10000),pageSize=require_int(data,'pageSize',50,1,100),
               scanAsOf=utc_now())
    return cfg

def matches(row,cfg):
    if not in_range(row['publishedAt'],cfg['publishedFrom'],cfg['publishedTo']):return False
    haystack=' '.join(row.get(k) or '' for k in ['title','description','buyerName']).casefold()
    if cfg['keywords'] and not any(word.casefold() in haystack for word in cfg['keywords']):return False
    if cfg['cpvCodes'] and not any(code.startswith(prefix) for code in row['cpvCodes'] for prefix in cfg['cpvCodes']):return False
    if cfg['valueCurrency'] and row['currency']!=cfg['valueCurrency']:return False
    if cfg['minimumValue']>0 and (row['estimatedValue'] is None or row['estimatedValue']<cfg['minimumValue']):return False
    return True

def next_cursor(data,endpoint):
    links=data.get('links',{})
    if not isinstance(links,dict):raise SchemaError('OCDS links must be an object.')
    link=links.get('next')
    if not link:return None
    if not isinstance(link,str):raise SchemaError('OCDS next link must be a URL.')
    target,base=urlsplit(link),urlsplit(endpoint)
    if target.scheme!=base.scheme or target.netloc!=base.netloc or target.path!=base.path:
        raise SchemaError('OCDS next link left its official endpoint.')
    values=parse_qs(target.query).get('cursor',[])
    if len(values)!=1 or not values[0] or len(values[0])>4096:raise SchemaError('OCDS next link lacks a valid cursor.')
    return values[0]

def uk_window(cfg,source):
    # The legacy UK API docs describe local UK datetimes. Widen by a day and
    # apply the requested UTC publication dates to each release before saving.
    lower=(datetime.fromisoformat(cfg['publishedFrom'])-timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
    upper=(datetime.fromisoformat(cfg['publishedTo'])+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
    if source=='contracts-finder':return {'publishedFrom':lower,'publishedTo':upper}
    # FTS filters last UPDATE time, not publication time. Do not use the user's
    # publishedTo as updatedTo: older releases may have been updated later.
    scan_end=(datetime.fromisoformat(cfg['scanAsOf'])+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
    return {'updatedFrom':lower,'updatedTo':scan_end}

async def fetch_page(source,state,cfg,client,page_size):
    endpoint=ENDPOINTS[source]
    if source=='ted':
        query=f"publication-date >= {cfg['publishedFrom'][:10].replace('-','')} AND publication-date <= {cfg['publishedTo'][:10].replace('-','')}"
        body={'query':query,'fields':TED_FIELDS,'limit':page_size,'scope':'ALL','paginationMode':'ITERATION'}
        if state['cursor']:body['iterationNextToken']=state['cursor']
        data=await client.get_json(endpoint,method='POST',json_body=body)
        if data.get('timedOut'):raise SourceError('TED reported a timed-out query; narrow the date range.')
        rows=rows_field(data,'notices')
        cursor=data.get('iterationNextToken') or None
        if cursor is not None and not isinstance(cursor,str):raise SchemaError('TED iteration token must be a string.')
    else:
        params={**uk_window(cfg,source),'limit':page_size}
        if state['cursor']:params['cursor']=state['cursor']
        data=await client.get_json(endpoint,params)
        rows=rows_field(data,'releases');cursor=next_cursor(data,endpoint)
    if cursor and cursor in state['seenCursors']:raise SchemaError('Source repeated a pagination cursor.')
    if cursor:state['seenCursors'].add(cursor)
    signature=tuple((str(r.get('publication-number')) if source=='ted' else str(r.get('ocid'))+':'+str(r.get('id'))) for r in rows)
    if signature and signature in state['seenPages']:raise SchemaError('Source repeated a page.')
    if signature:state['seenPages'].add(signature)
    state['cursor']=cursor
    return rows,bool(cursor and rows)

async def collect(cfg,client,sink,stats):
    states={s:{'cursor':None,'seenCursors':set(),'seenPages':set()} for s in cfg['sources']}
    pending=deque(cfg['sources']);successful=set()
    while pending and not sink.full and stats['pagesFetched']<cfg['maxPages']:
        source=pending.popleft()
        try:
            size=min(cfg['pageSize'],max(1,math.ceil((cfg['maxResults']-sink.count)/(len(pending)+1))))
            rows,more=await fetch_page(source,states[source],cfg,client,size)
            stats['pagesFetched']+=1;stats['sources'][source]['pages']+=1
            valid=0
            for raw in rows:
                try:row=parse_ted(raw) if source=='ted' else parse_ocds(raw,source)
                except SchemaError:
                    stats['skippedMalformed']+=1;continue
                valid+=1
                if not matches(row,cfg):stats['filtered']+=1;continue
                key=f"{source}:{row['ocid'] or ''}:{row['noticeId']}"
                if await sink.emit(row,key):stats['sources'][source]['items']+=1
                if sink.full:break
            if rows and not valid:raise SchemaError('All notices on a nonempty source page were malformed.')
            successful.add(source)
            if more:pending.append(source)
        except SourceError as exc:
            stats['sourceErrors'].append({'source':source,'errorType':type(exc).__name__,'error':str(exc)})
            LOG.warning('Source %s failed (%s).',source,type(exc).__name__)
    if not successful and stats['sourceErrors']:raise SourceError('All tender sources failed; see RUN_STATS sourceErrors.')
    stats['unexhaustedSources']=list(pending)
    if sink.full:stats['stopReason']='item_or_budget_limit'
    elif pending:stats['stopReason']='page_limit'
    if stats['sourceErrors']:stats['stopReason']='partial_source_errors'
    return stats

async def main(actor,supplied_input=None):
    async with actor:
        # Open both local default stores so failed/empty runs cannot expose stale data.
        await actor.open_dataset()
        await actor.set_value('RUN_STATS', {'items': 0, 'stopReason': 'initializing'})
        raw=supplied_input if supplied_input is not None else await actor.get_input()
        cfg=normalize_input({} if raw is None else raw)
        sink=ResultSink(actor,cfg['maxResults'])
        stats={'pagesFetched':0,'filtered':0,'skippedMalformed':0,'sources':{s:{'pages':0,'items':0} for s in cfg['sources']},
               'sourceErrors':[],'stopReason':'source_exhausted','scanAsOf':cfg['scanAsOf']}
        async with PublicClient(delay=cfg['requestDelaySeconds'],allowed_origins=[f'{urlsplit(u).scheme}://{urlsplit(u).netloc}' for u in ENDPOINTS.values()]) as client:
            try:await collect(cfg,client,sink,stats)
            except SourceError as exc:
                stats.update(stopReason='source_error',errorType=type(exc).__name__,error=str(exc))
                await finish(actor,client,sink,stats);raise
            await finish(actor,client,sink,stats)
