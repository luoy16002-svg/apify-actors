from datetime import datetime
from .common import LOG,ResultSink,SchemaError,SourceError
from .helpers import (InputError,PublicClient,apple_id,common_input,country_code,date_input,finish,
                      in_range,public_url,output_url,require_int,require_string,rows_field,string_list)
from .parser import parse_feed,parse_episode

APPLE='https://itunes.apple.com'

def normalize_input(data):
    cfg=common_input(data,3.2)
    terms=string_list(data,'searchTerms')
    shows=list(dict.fromkeys(apple_id(x,podcast=True) for x in string_list(data,'shows')))
    feeds=list(dict.fromkeys(public_url(x) for x in string_list(data,'feedUrls')))
    if any(not output_url(url) for url in feeds):raise InputError('Feed URLs containing contact addresses are unsupported.')
    if not terms and not shows and not feeds:raise InputError('Provide shows or feedUrls.')
    cfg.update(searchTerms=terms,shows=shows,feedUrls=feeds,country=country_code(require_string(data,'country','us')),
               maxShows=require_int(data,'maxShows',5,1,50),maxEpisodesPerShow=require_int(data,'maxEpisodesPerShow',20,1,1000),
               publishedAfter=date_input(data,'publishedAfter'))
    return cfg

async def discover(cfg,client,stats):
    found={}
    def add(url,metadata):
        try: url=public_url(url)
        except InputError: raise SchemaError('Directory returned an unsafe feed URL.') from None
        if not output_url(url): raise SchemaError('Directory feed URL exposes a contact address.')
        # Prefer lookup metadata when the same feed is also supplied directly.
        if url not in found and len(found)<cfg['maxShows']:found[url]=metadata
    for index,show_id in enumerate(cfg['shows']):
        if len(found)>=cfg['maxShows']:break
        try:
            data=await client.get_json(APPLE+'/lookup',{'id':show_id,'country':cfg['country'],'media':'podcast','entity':'podcast'})
            for row in rows_field(data,'results'):
                if row.get('kind')=='podcast' and row.get('feedUrl'):add(row['feedUrl'],row)
        except SourceError as exc:
            stats['sourceErrors'].append({'stage':'lookup','inputIndex':index,'errorType':type(exc).__name__,'error':str(exc)})
    for url in cfg['feedUrls']:
        if len(found)>=cfg['maxShows']:break
        add(url,{})
    for index,term in enumerate(cfg['searchTerms']):
        if len(found)>=cfg['maxShows']:break
        try:
            data=await client.get_json(APPLE+'/search',{'term':term,'country':cfg['country'],'media':'podcast','entity':'podcast','limit':min(200,cfg['maxShows'])})
            for row in rows_field(data,'results'):
                if row.get('kind')=='podcast' and row.get('feedUrl'):add(row['feedUrl'],row)
        except SourceError as exc:
            stats['sourceErrors'].append({'stage':'search','inputIndex':index,'errorType':type(exc).__name__,'error':str(exc)})
    if not found and stats['sourceErrors']:raise SourceError('All podcast discovery sources failed; see RUN_STATS sourceErrors.')
    return found

async def collect(cfg,client,sink,stats):
    if sink.full:
        stats['stopReason']='item_or_budget_limit';return stats
    candidates=await discover(cfg,client,stats)
    seen_feeds=set()
    successes=0
    for feed_url,lookup in candidates.items():
        if sink.full:
            stats['stopReason']='item_or_budget_limit';break
        if stats['pagesFetched']>=cfg['maxPages']:
            stats['stopReason']='page_limit';break
        try:
            response=await client.request(feed_url)
            stats['pagesFetched']+=1
            final_url=str(response.url)
            if final_url in seen_feeds:continue
            seen_feeds.add(final_url)
            show,entries,bozo=parse_feed(response.content,final_url,lookup,response.headers.get('content-type'))
            stats['feedsWithParseWarnings']+=int(bozo)
            saved=valid=0
            for entry in entries:
                try:row=parse_episode(entry,show)
                except SchemaError:
                    stats['skippedMalformed']+=1;continue
                valid+=1
                # Strictly after the supplied instant; unknown dates cannot pass a date filter.
                if cfg['publishedAfter'] and (not in_range(row['publishedAt'],cfg['publishedAfter'],None) or datetime.fromisoformat(row['publishedAt'])==datetime.fromisoformat(cfg['publishedAfter'])):
                    stats['filtered']+=1;continue
                if await sink.emit(row,row['episodeKey']):saved+=1
                if saved>=cfg['maxEpisodesPerShow'] or sink.full:break
            if entries and not valid:raise SchemaError('All entries in a nonempty feed were malformed.')
            successes+=1;stats['showsFetched']+=1
        except SourceError as exc:
            stats['sourceErrors'].append({'stage':'feed','errorType':type(exc).__name__,'error':str(exc)})
            LOG.warning('A feed failed (%s); see RUN_STATS.',type(exc).__name__)
    if candidates and not successes and stats['sourceErrors']:raise SourceError('All podcast feeds failed; see RUN_STATS sourceErrors.')
    if stats['sourceErrors']:stats['stopReason']='partial_source_errors'
    elif sink.full:stats['stopReason']='item_or_budget_limit'
    return stats

async def main(actor,supplied_input=None):
    async with actor:
        # Open both local default stores so failed/empty runs cannot expose stale data.
        await actor.open_dataset()
        await actor.set_value('RUN_STATS', {'items': 0, 'stopReason': 'initializing'})
        raw=supplied_input if supplied_input is not None else await actor.get_input()
        cfg=normalize_input({} if raw is None else raw)
        sink=ResultSink(actor,cfg['maxShows']*cfg['maxEpisodesPerShow'])
        stats={'pagesFetched':0,'showsFetched':0,'filtered':0,'skippedMalformed':0,'feedsWithParseWarnings':0,'sourceErrors':[],'stopReason':'source_exhausted'}
        async with PublicClient(delay=cfg['requestDelaySeconds']) as client:
            try:await collect(cfg,client,sink,stats)
            except SourceError as exc:
                stats.update(stopReason='source_error',errorType=type(exc).__name__,error=str(exc))
                await finish(actor,client,sink,stats);raise
            await finish(actor,client,sink,stats)
