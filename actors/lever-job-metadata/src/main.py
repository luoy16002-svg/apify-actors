from __future__ import annotations

import re

from .common import (LOG, PoliteClient, ResultSink, SchemaError, common_input,
                     proxy_url, require_string, utc_now)
from .parser import parse_job, parse_page


def normalize_input(data: dict) -> dict:
    common = common_input(data)
    boards = data.get('boards', ['spotify'])
    if not isinstance(boards, list) or not 1 <= len(boards) <= 25:
        raise ValueError('boards must be an array containing 1 to 25 Lever board slugs.')
    normalized = []
    for board in boards:
        if not isinstance(board, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', board):
            raise ValueError('Each board must be a plain Lever slug (letters, numbers, underscore, hyphen).')
        # Board names are normalized for cross-input deduplication.
        normalized.append(board.lower())
    region = require_string(data, 'region', 'global')
    workplace = require_string(data, 'workplaceType', 'any')
    if region not in {'global', 'eu'}:
        raise ValueError('region must be global or eu.')
    if workplace not in {'any', 'remote', 'hybrid', 'onsite'}:
        raise ValueError('workplaceType must be any, remote, hybrid, or onsite.')
    return {**common, 'boards': list(dict.fromkeys(normalized)), 'region': region,
            'titleContains': require_string(data, 'titleContains'),
            'locationContains': require_string(data, 'locationContains'), 'workplaceType': workplace}


def matches(job: dict, config: dict) -> bool:
    return (config['titleContains'].casefold() in job['title'].casefold()
            and config['locationContains'].casefold() in (job['allLocations'] or '').casefold()
            and (config['workplaceType'] == 'any' or job['workplaceType'] == config['workplaceType']))


async def collect(config: dict, client: PoliteClient, sink: ResultSink) -> dict:
    skipped = filtered = pages = 0
    reason = 'source_exhausted'
    page_size = min(config['pageSize'], config['maxItems'])
    for board in config['boards']:
        offset = 0
        seen_pages = set()
        while not sink.full:
            if pages >= config['maxPages']:
                LOG.warning('maxPages reached; filtered results or later boards may be incomplete.')
                return {'items': sink.count, 'duplicates': sink.duplicates, 'skippedMalformed': skipped,
                        'filtered': filtered, 'pagesFetched': pages, 'stopReason': 'page_limit'}
            rows = parse_page(await client.get_json(f'/v0/postings/{board}',
                              {'mode': 'json', 'skip': offset, 'limit': page_size}))
            pages += 1
            if not rows:
                LOG.info('Board %s returned no further public jobs.', board)
                break
            signature = tuple(str(row.get('id')) if isinstance(row, dict) else '?' for row in rows)
            if signature in seen_pages:
                raise SchemaError('Lever repeated a page; stopping to avoid incomplete silent results.')
            seen_pages.add(signature)
            LOG.info('Board %s offset %s: %s source jobs.', board, offset, len(rows))
            valid = 0
            fetched_at = utc_now()
            for raw in rows:
                try:
                    job = parse_job(raw, board=board, region=config['region'], fetched_at=fetched_at)
                except SchemaError as exc:
                    skipped += 1
                    LOG.warning('Skipping malformed job: %s', exc)
                    continue
                valid += 1
                if not matches(job, config):
                    filtered += 1
                    continue
                await sink.emit(job, f"{config['region']}:{job['jobId']}")
                if sink.full:
                    break
            if valid == 0:
                raise SchemaError('All jobs on a nonempty page were malformed.')
            offset += len(rows)
            if len(rows) < page_size:
                break
        if sink.full:
            reason = 'item_or_budget_limit'
            break
    return {'items': sink.count, 'duplicates': sink.duplicates, 'skippedMalformed': skipped,
            'filtered': filtered, 'pagesFetched': pages, 'stopReason': reason}


async def main(actor, supplied_input=None):
    async with actor:
        raw = supplied_input if supplied_input is not None else await actor.get_input()
        config = normalize_input({} if raw is None else raw)
        LOG.info('Starting %s Lever board(s); maxItems=%s, concurrency=1.', len(config['boards']), config['maxItems'])
        sink = ResultSink(actor, config['maxItems'])
        origin = 'https://api.eu.lever.co' if config['region'] == 'eu' else 'https://api.lever.co'
        async with PoliteClient(origin, '/v0/postings/', delay=config['requestDelaySeconds'],
                                proxy_url=await proxy_url(actor, config['proxyConfiguration'])) as client:
            stats = await collect(config, client, sink)
            stats.update(requests=client.request_count, retries=client.retry_count, finishedAt=utc_now())
        await actor.set_value('RUN_STATS', stats)
        await actor.set_status_message(f"Saved {sink.count} jobs ({stats['stopReason']}).")
        LOG.info('Finished: %s', stats)
