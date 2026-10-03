from __future__ import annotations

import time
from datetime import datetime

from .common import LOG, ResultSink, SchemaError, require_int, require_string, utc_now
from .net import FetchError, InputError, PublicClient, error_record
from .parser import parse_job
from .providers import detail, page
from .targets import Board, SYSTEMS, company_input, detect, from_url


def normalize_input(data):
    if not isinstance(data, dict):
        raise InputError('Input must be an object.')
    companies = data.get('companies')
    if not isinstance(companies, list) or not 1 <= len(companies) <= 50:
        raise InputError('companies must contain 1 to 50 companies.')
    try:
        config = {k: require_string(data, k) for k in ['titleContains', 'locationContains', 'department', 'postedAfter']}
        config.update(maxJobsPerCompany=require_int(data, 'maxJobsPerCompany', 1000, 1, 10000),
                      maxItems=require_int(data, 'maxItems', 10000, 1, 50000),
                      pageSize=require_int(data, 'pageSize', 100, 1, 100),
                      maxPages=require_int(data, 'maxPages', 100, 1, 500))
        if config['postedAfter']:
            datetime.strptime(config['postedAfter'], '%Y-%m-%d')
    except ValueError as exc:
        raise InputError(str(exc)) from exc
    if not isinstance(data.get('remoteOnly', False), bool):
        raise InputError('remoteOnly must be boolean.')
    delay = data.get('requestDelaySeconds', 1.2)
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 1 <= delay <= 30:
        raise InputError('requestDelaySeconds must be between 1 and 30.')
    config.update(companies=[company_input(x) for x in companies], remoteOnly=data.get('remoteOnly', False),
                  requestDelaySeconds=delay)
    return config


def matches(job, config):
    return (config['titleContains'].casefold() in job['title'].casefold()
            and config['locationContains'].casefold() in (job['allLocations'] or '').casefold()
            and config['department'].casefold() in (job['department'] or '').casefold()
            and (not config['remoteOnly'] or job['isRemote'] is True)
            and (not config['postedAfter'] or bool(job['createdAt'] and job['createdAt'][:10] > config['postedAfter'])))


async def resolve(item, client, config):
    url = item.get('url') or item.get('website')
    if url:
        board = from_url(url)
        if board:
            return board, None
    if item.get('slug') and item.get('ats'):
        return Board(item['ats'].lower(), item['slug'], item.get('region', 'global')), None
    if url:
        response = await client.get(url)  # one company page, no recursive crawling
        boards = detect(response.text)
        if item.get('ats'):
            boards = [b for b in boards if b.ats == item['ats'].lower()]
        if len(boards) == 1:
            return boards[0], None
        raise FetchError('ats_ambiguous' if boards else 'ats_not_detected',
                         'Multiple ATS boards linked; use a specific board URL.' if boards else 'No supported ATS URL found in the page HTML.')
    # A hintless slug is ambiguous across systems. Probe each documented public board once;
    # never guess between multiple successful systems and never retry a blocked origin via another endpoint.
    candidates = []
    for ats in SYSTEMS:
        board = Board(ats, item['slug'])
        try:
            first = await page(client, board, page_size=config['pageSize'])
            candidates.append((board, first))
        except (FetchError, SchemaError):
            continue
    if len(candidates) == 1:
        return candidates[0]
    raise FetchError('ats_ambiguous' if candidates else 'unknown_slug',
                     'Slug resolved to several systems; provide an ATS hint.' if candidates else 'No accessible public board found; provide an ATS hint or careers URL.')


async def collect(config, client, sink):
    summaries, boards_seen = [], set()
    for item in config['companies']:
        start = time.monotonic()
        stats = {'input': item, 'saved': 0, 'sourceRows': 0, 'sourceTotal': None, 'filtered': 0,
                 'duplicates': 0, 'pages': 0, 'malformed': 0, 'detailErrors': [], 'complete': False}
        try:
            if sink.full:
                stats['stopReason'] = 'item_or_budget_limit'
                continue
            board, first = await resolve(item, client, config)
            stats.update(ats=board.ats, board=board.slug, careersUrl=board.careers)
            if board.identity in boards_seen:
                stats['stopReason'] = 'duplicate_company'
                continue
            boards_seen.add(board.identity)
            seen, signatures, offset = set(), set(), 0
            for index in range(config['maxPages']):
                rows, total = first if index == 0 and first is not None else await page(client, board, offset, config['pageSize'])
                stats['sourceTotal'] = total
                stats['pages'] += 1
                signature = tuple(str(r.get('id') or r.get('shortcode') or r.get('jobUrl')) for r in rows)
                if rows and signature in signatures:
                    raise FetchError('repeated_page', 'Source repeated a page; results are incomplete.')
                signatures.add(signature)
                stats['sourceRows'] += len(rows)
                for raw in rows:
                    if raw.get('isListed') is False or raw.get('visibility') == 'INTERNAL':
                        stats['filtered'] += 1
                        continue
                    try:
                        job = parse_job(raw, board, item.get('name'))
                        if job['sourceId'] in seen:
                            stats['duplicates'] += 1
                            continue
                        seen.add(job['sourceId'])
                        if not matches(job, config):
                            stats['filtered'] += 1
                            continue
                        if board.ats == 'smartrecruiters':
                            job = parse_job(await detail(client, board, raw), board, item.get('name'))
                            if not matches(job, config):
                                stats['filtered'] += 1
                                continue
                        if await sink.emit(job, job['sourceId']):
                            stats['saved'] += 1
                    except FetchError as exc:
                        stats['detailErrors'].append(error_record(exc))
                    except (SchemaError, ValueError, TypeError, AttributeError, KeyError) as exc:
                        stats['malformed'] += 1
                        LOG.warning('Skipping malformed %s record (%s).', board.ats, type(exc).__name__)
                    if stats['saved'] >= config['maxJobsPerCompany'] or sink.full:
                        break
                offset += len(rows)
                paginated = board.ats in {'smartrecruiters', 'lever'}
                exhausted = not paginated or not rows or (total is not None and offset >= total) or (board.ats == 'lever' and len(rows) < config['pageSize'])
                if exhausted and stats['saved'] < config['maxJobsPerCompany'] and not sink.full:
                    stats.update(complete=not stats['malformed'] and not stats['detailErrors'], stopReason='source_exhausted')
                    break
                if stats['saved'] >= config['maxJobsPerCompany'] or sink.full:
                    stats['stopReason'] = 'item_or_budget_limit'
                    break
            else:
                stats['stopReason'] = 'page_limit'
        except (FetchError, SchemaError, InputError, ValueError, TypeError) as exc:
            stats.update(error=error_record(exc), stopReason='company_error')
        finally:
            stats['seconds'] = round(time.monotonic() - start, 3)
            summaries.append(stats)
            LOG.info('Company result: %s', stats)
    return summaries


async def main(actor, supplied_input=None):
    async with actor:
        await actor.open_dataset()
        await actor.set_value('OUTPUT', {'items': 0, 'state': 'initializing'})
        data = supplied_input if supplied_input is not None else await actor.get_input()
        config = normalize_input(data or {})
        sink = ResultSink(actor, config['maxItems'])
        async with PublicClient('ATSJobsActor', delay=config['requestDelaySeconds']) as client:
            summaries = await collect(config, client, sink)
            output = {'items': sink.count, 'duplicates': sink.duplicates, 'companies': summaries,
                      'requests': client.requests, 'retries': client.retries, 'finishedAt': utc_now()}
            await actor.set_value('HTTP_AUDIT', client.audit)
        await actor.set_value('OUTPUT', output)
        await actor.set_status_message(f'Saved {sink.count} jobs; company diagnostics in OUTPUT.')
