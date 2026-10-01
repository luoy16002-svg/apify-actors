from __future__ import annotations

from .common import (LOG, PoliteClient, ResultSink, SchemaError, common_input,
                     integer, proxy_url, require_int, require_string, utc_now)
from .parser import parse_establishment, parse_page


def normalize_input(data: dict) -> dict:
    common = common_input(data)
    return {
        **common, 'name': require_string(data, 'name', ''),
        'address': require_string(data, 'address', ''),
        'localAuthorityId': require_int(data, 'localAuthorityId', 0, 0, 10000),
        'businessTypeId': require_int(data, 'businessTypeId', 0, 0, 100000),
    }


async def collect(config: dict, client: PoliteClient, sink: ResultSink) -> dict:
    params = {k: config[k] for k in ('name', 'address', 'localAuthorityId', 'businessTypeId') if config[k]}
    # A fixed page size is essential: changing it mid-run shifts FSA offsets.
    # Pages must also be large: the FSA's order is not stable for ties (a chain's branches), so small pages
    # overlap and silently drop rows. One 5,000-row page avoids paging for most queries.
    page_size = min(config['pageSize'], config['maxItems'])
    params['pageSize'] = page_size
    seen_pages = set()
    skipped = 0
    reason = 'source_exhausted'
    pages = 0
    for page in range(1, config['maxPages'] + 1):
        if sink.full:
            reason = 'item_or_budget_limit'
            break
        rows, meta = parse_page(await client.get_json('/Establishments', {**params, 'pageNumber': page}))
        pages += 1
        reported_page = integer(meta.get('pageNumber'))
        if reported_page is not None and reported_page != page:
            raise SchemaError('FSA returned an unexpected page number.')
        if not rows:
            break
        signature = tuple(str(row.get('FHRSID')) if isinstance(row, dict) else '?' for row in rows)
        if signature in seen_pages:
            raise SchemaError('FSA repeated a page; stopping to avoid an incomplete silent result.')
        seen_pages.add(signature)
        LOG.info('Processing FSA page %s (%s source records).', page, len(rows))
        valid = 0
        fetched_at = utc_now()
        for row in rows:
            try:
                record = parse_establishment(row, fetched_at=fetched_at, extract_date=meta.get('extractDate'))
            except SchemaError as exc:
                skipped += 1
                LOG.warning('Skipping malformed establishment: %s', exc)
                continue
            valid += 1
            await sink.emit(record, record['fhrsId'])
            if sink.full:
                reason = 'item_or_budget_limit'
                break
        if valid == 0:
            raise SchemaError('All establishments on a nonempty page were malformed.')
        total_pages = integer(meta.get('totalPages'))
        if sink.full or len(rows) < page_size or (total_pages is not None and page >= total_pages):
            break
    else:
        reason = 'page_limit'
        LOG.warning('maxPages reached; results may be incomplete.')
    return {'items': sink.count, 'duplicates': sink.duplicates, 'skippedMalformed': skipped,
            'pagesFetched': pages, 'stopReason': reason}


async def main(actor, supplied_input=None):
    async with actor:
        raw = supplied_input if supplied_input is not None else await actor.get_input()
        config = normalize_input({} if raw is None else raw)
        LOG.info('Starting FSA search; maxItems=%s, concurrency=1.', config['maxItems'])
        sink = ResultSink(actor, config['maxItems'])
        async with PoliteClient('https://api.ratings.food.gov.uk', '/Establishments',
                                delay=config['requestDelaySeconds'],
                                proxy_url=await proxy_url(actor, config['proxyConfiguration']),
                                headers={'x-api-version': '2'}) as client:
            stats = await collect(config, client, sink)
            stats.update(requests=client.request_count, retries=client.retry_count, finishedAt=utc_now())
        await actor.set_value('RUN_STATS', stats)
        await actor.set_status_message(f"Saved {sink.count} businesses ({stats['stopReason']}).")
        LOG.info('Finished: %s', stats)
