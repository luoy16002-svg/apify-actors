from __future__ import annotations

import asyncio
import time

import psutil

from .browser import BrowserPool
from .capture import PRESETS, capture, stable_key
from .common import LOG, ResultSink, require_int, utc_now
from .net import FetchError, InputError, PublicClient, error_record, public_url


def normalize_input(data):
    if not isinstance(data, dict):
        raise InputError('Input must be an object.')
    urls = data.get('urls')
    if not isinstance(urls, list) or not 1 <= len(urls) <= 100:
        raise InputError('urls must contain 1 to 100 public URLs.')
    cfg = {'urls': list(dict.fromkeys(public_url(u) for u in urls))}
    for key, default in {'fullPage': True, 'pdf': False, 'printBackground': True, 'hideCookieBanners': True,
                         'blockAds': False, 'darkMode': False, 'scrollPage': True}.items():
        if not isinstance(data.get(key, default), bool):
            raise InputError(f'{key} must be boolean.')
        cfg[key] = data.get(key, default)
    for key, default, values in [('viewport', 'desktop', list(PRESETS) + ['custom']), ('format', 'png', ['png', 'jpeg', 'webp']),
                                  ('pdfFormat', 'A4', ['A4', 'Letter']), ('waitStrategy', 'load', ['load', 'networkidle', 'fixed', 'selector'])]:
        if data.get(key, default) not in values:
            raise InputError(f'{key} must be one of {values}.')
        cfg[key] = data.get(key, default)
    try:
        for key, default, low, high in [('width', 1440, 320, 3840), ('height', 900, 320, 2160),
                                       ('quality', 85, 1, 100), ('timeoutSeconds', 60, 5, 180), ('maxConcurrency', 2, 1, 3)]:
            cfg[key] = require_int(data, key, default, low, high)
    except ValueError as exc:
        raise InputError(str(exc)) from exc
    for key, limit in [('css', 20000), ('elementSelector', 1000), ('waitSelector', 1000)]:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise InputError(f'{key} must be a string of at most {limit} characters.')
        cfg[key] = value.strip()
    delay = data.get('waitDelaySeconds', 2)
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 0 <= delay <= 20:
        raise InputError('waitDelaySeconds must be between 0 and 20.')
    cfg['waitDelaySeconds'] = delay
    if cfg['waitStrategy'] == 'selector' and not cfg['waitSelector']:
        raise InputError('waitSelector is required for selector strategy.')
    if set(data) - set(cfg):
        raise InputError('Unknown input fields: ' + ', '.join(sorted(set(data) - set(cfg))))
    return cfg


async def memory_sample(done, result):
    process = psutil.Process()
    while not done.is_set():
        try:
            rss = sum(p.memory_info().rss for p in [process] + process.children(recursive=True) if p.is_running())
            result['peakProcessTreeRssMB'] = max(result.get('peakProcessTreeRssMB', 0), round(rss / 1048576, 1))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        try:
            await asyncio.wait_for(done.wait(), timeout=.2)
        except TimeoutError:
            pass


async def main(actor, supplied_input=None):
    async with actor:
        await actor.open_dataset()
        await actor.set_value('OUTPUT', {'items': 0, 'state': 'initializing'})
        cfg = normalize_input(supplied_input if supplied_input is not None else await actor.get_input() or {})
        store = await actor.open_key_value_store()
        sink = ResultSink(actor, len(cfg['urls']))
        sem = asyncio.Semaphore(cfg['maxConcurrency'])
        summaries = []
        async with PublicClient('WebsiteScreenshotsActor') as client, BrowserPool() as pool:
            async def work(url):
                async with sem:
                    if sink.full:
                        summaries.append({'url': url, 'error': {'code': 'budget_limit', 'message': 'Result budget reached.'}})
                        return
                    result = {'url': url}
                    start = time.monotonic()
                    done = asyncio.Event()
                    sampler = asyncio.create_task(memory_sample(done, result))
                    try:
                        row, image, pdf, metrics = await capture(pool, client, url, cfg)
                        key = stable_key(url, cfg)
                        image_key = key + '.' + cfg['format']
                        await store.set_value(image_key, image, content_type='image/' + cfg['format'])
                        async def link(k):
                            try:
                                value = await store.get_public_url(k)
                                return value if value.startswith('https://') else None
                            except (RuntimeError, ValueError):
                                return None  # local KVS has no hosted public URL
                        row.update(key=image_key, fileUrl=await link(image_key), pdfKey=None, pdfUrl=None, pdfByteSize=None)
                        if pdf is not None:
                            pdf_key = key + '.pdf'
                            await store.set_value(pdf_key, pdf, content_type='application/pdf')
                            row.update(pdfKey=pdf_key, pdfUrl=await link(pdf_key), pdfByteSize=len(pdf))
                        result.update(saved=await sink.emit(row, public_url(row['finalUrl'])), **metrics)
                    except (FetchError, InputError) as exc:
                        result['error'] = error_record(exc)
                    finally:
                        done.set()
                        await sampler
                        result['seconds'] = round(time.monotonic() - start, 3)
                        summaries.append(result)
                        LOG.info('Page result: %s', result)
            async with asyncio.TaskGroup() as group:
                for url in cfg['urls']:
                    group.create_task(work(url))
            output = {'items': sink.count, 'pages': summaries, 'browserRestarts': pool.restarts,
                      'memoryMeasurement': 'Sampled process-tree RSS; includes other concurrent pages and shared pages.',
                      'finishedAt': utc_now()}
            await actor.set_value('HTTP_AUDIT', client.audit)
        await actor.set_value('OUTPUT', output)
        await actor.set_status_message(f'Saved {sink.count} successful captures. Failures are in OUTPUT only.')
