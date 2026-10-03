from __future__ import annotations

import asyncio
import re
import time
from http.cookies import SimpleCookie

from bs4 import BeautifulSoup

from playwright.async_api import Error as BrowserError

from .browser import BrowserPool, new_context
from .common import LOG, ResultSink, require_int, utc_now
from .fingerprints import COMMIT, LICENSE, load
from .matcher import Matcher, convenience, signals
from .net import FetchError, InputError, PublicClient, error_record, public_url

# Paths are fingerprint data, not executable code. Getters/functions are never called.
READ_GLOBALS = r"""(paths) => {
  const out = {};
  for (const path of paths) {
    const parts = path.split('.');
    if (['window','globalThis'].includes(parts[0])) parts.shift();
    let value = window, ok = true;
    for (const key of parts) {
      if (['__proto__','prototype','constructor'].includes(key)) { ok=false; break; }
      if (value === null || !['object','function'].includes(typeof value)) { ok=false; break; }
      let desc;
      try { desc = Object.getOwnPropertyDescriptor(value,key); } catch (_) { ok=false; break; }
      if (!desc || !('value' in desc)) { ok=false; break; }
      value = desc.value;
    }
    if (ok && value !== undefined && value !== null) {
      out[path] = ['string','number','boolean'].includes(typeof value) ? String(value).slice(0,500) : '';
    }
  }
  return out;
}"""


def normalize_input(data):
    if not isinstance(data, dict):
        raise InputError('Input must be an object.')
    if not isinstance(data.get('urls'), list) or not 1 <= len(data['urls']) <= 100:
        raise InputError('urls must contain 1 to 100 URLs or domains.')
    if not isinstance(data.get('renderJs', False), bool):
        raise InputError('renderJs must be boolean.')
    categories = data.get('includeCategories', [])
    if not isinstance(categories, list) or any(not isinstance(c, str) or not c.strip() for c in categories):
        raise InputError('includeCategories must be an array of category names or IDs as strings.')
    try:
        config = {'urls': list(dict.fromkeys(public_url(u) for u in data['urls'])), 'renderJs': data.get('renderJs', False),
                  'includeCategories': sorted({c.strip().casefold() for c in categories}),
                  'maxConcurrency': require_int(data, 'maxConcurrency', 5, 1, 10),
                  'timeoutSeconds': require_int(data, 'timeoutSeconds', 45, 5, 180)}
    except ValueError as exc:
        raise InputError(str(exc)) from exc
    if set(data) - set(config):
        raise InputError('Unknown input fields: ' + ', '.join(sorted(set(data) - set(config))))
    return config


def observations(html, headers):
    """Small, independent and non-contact QA markers; not a second fingerprint database."""
    markers = {'wordpressAssets': r'wp-(?:content|includes)/', 'shopifyAssets': r'(?:cdn\.shopify\.com|Shopify\.shop)',
               'wixGenerator': r'Wix\.com Website Builder', 'squarespaceAssets': r'(?:static[0-9]?\.squarespace\.com|squarespace-cdn\.com)',
               'webflowAttribute': r'data-wf-(?:page|site)', 'nextAssets': r'/_next/', 'ga4Tag': r'(?:gtag/js\?id=G-|["\']G-[A-Z0-9]{6,}["\'])',
               'hubspotScript': r'js\.hs(?:-scripts|forms|collectedforms)\.(?:com|net)', 'stripeJs': r'js\.stripe\.com',
               'drupalAssets': r'(?:sites/default/files|Drupal\.settings|drupalSettings)', 'nuxtAssets': r'/_nuxt/',
               'gatsbyMarker': r'(?:___gatsby|gatsby-focus-wrapper)', 'bootstrapAssets': r'bootstrap(?:\.min)?\.(?:css|js)'}
    evidence = {name: match.group(0)[:100] for name, pattern in markers.items() if (match := re.search(pattern, html, re.I))}
    soup = BeautifulSoup(html, 'html.parser')
    generators = [m.get('content', '')[:100] for m in soup.find_all('meta') if (m.get('name') or '').lower() == 'generator']
    if generators:
        evidence['meta:generator'] = generators
    asset_hints = []
    for node in soup.find_all(['script', 'link']):
        source = node.get('src') or node.get('href') or ''
        if re.search(r'jquery|bootstrap|plausible|matomo|posthog|hs-scripts|stripe|wp-content|_nuxt|_next|wixstatic|squarespace|shopify|webflow|htmx', source, re.I):
            asset_hints.append(source.split('?')[0][:160])
    if asset_hints:
        evidence['assetHints'] = list(dict.fromkeys(asset_hints))[:8]
    for name in ['server', 'x-powered-by', 'x-generator']:
        if name in headers:
            evidence['header:' + name] = headers[name][:100]
    for name in ['x-vercel-id', 'x-shopid', 'x-wix-request-id', 'x-drupal-cache', 'x-hs-hub-id']:
        if name in headers:
            evidence['header:' + name] = 'present'
    return evidence


async def inspect_site(url, cfg, client, matcher, pool):
    response = await client.get(url)
    if not any(t in response.headers.get('content-type', '').lower() for t in ['text/html', 'application/xhtml+xml']):
        raise FetchError('not_html', 'Homepage did not return HTML.', response.status_code)
    html, final_url = response.text, str(response.url)
    cookies = {}
    for header in response.headers.get_list('set-cookie'):
        cookie = SimpleCookie()
        try:
            cookie.load(header)
        except Exception:
            continue
        cookies.update({k: v.value for k, v in cookie.items()})
    js, warnings = {}, []
    if cfg['renderJs']:
        # Plain HTTP is always first. Rendering is explicit and does not bypass a failed fetch.
        for attempt in range(2):
            context = None
            state = {}
            try:
                context, state = await new_context(pool, client, {'viewport': {'width': 1440, 'height': 900},
                                    'user_agent': 'TechStackDetectorActor/1.0 (Chromium; respects robots.txt)'})
                page = await context.new_page()
                page.on('download', lambda d: d.cancel())
                page.on('dialog', lambda d: d.dismiss())
                page.on('popup', lambda p: p.close())
                nav = await page.goto(final_url, wait_until='domcontentloaded', timeout=cfg['timeoutSeconds'] * 1000)
                if not nav or nav.status >= 400:
                    raise FetchError('render_http_error', f'Render navigation failed (HTTP {nav.status if nav else "unknown"}).')
                await page.wait_for_timeout(750)
                title = await page.title()
                if re.search(r'(?i)^(just a moment|access denied|attention required|verify you are human|robot or human)', title.strip()):
                    raise FetchError('access_blocked', 'Page displays an access challenge; stopped.')
                html = await page.content()
                final_url = page.url
                js = await page.evaluate(READ_GLOBALS, matcher.js_paths)
                cookies.update({c['name']: c['value'] for c in await context.cookies([final_url])})
                if state['blocked']:
                    warnings.append('Some render resources were blocked by policy: ' + str(state['reasons']))
                break
            except BrowserError as exc:
                if state.get('navigationError'):
                    raise state['navigationError']
                if attempt == 0 and pool.browser is not None and not pool.browser.is_connected():
                    continue
                raise FetchError('render_error', str(exc).splitlines()[0][:300]) from exc
            finally:
                if context:
                    try:
                        await context.close()
                    except BrowserError:
                        pass
    if len(html) > 3_000_000:
        raise FetchError('html_too_large', 'Homepage exceeds 3 million characters; stopped before regex matching.')
    headers = {key: response.headers.get_list(key) for key in response.headers.keys()}
    data = await asyncio.to_thread(signals, html, headers, cookies, final_url, js)
    technologies, diagnostics = await asyncio.to_thread(matcher.detect, data, set(cfg['includeCategories']))
    if diagnostics['regexTimeouts'] or diagnostics['unsupportedPatterns']:
        warnings.append(f"Matcher skipped {diagnostics['regexTimeouts']} timed-out matches; {diagnostics['unsupportedPatterns']} unsupported patterns.")
    row = {'url': url, 'finalUrl': final_url, 'statusCode': response.status_code, 'status': 'partial' if warnings else 'ok',
           'technologies': technologies, **convenience(technologies), 'fingerprintCommit': COMMIT,
           'fingerprintLicense': LICENSE, 'rendered': cfg['renderJs'], 'fetchedAt': utc_now(), 'warnings': warnings}
    return row, {**diagnostics, 'observations': observations(html, response.headers), 'jsGlobalsObserved': len(js)}


async def main(actor, supplied_input=None):
    async with actor:
        await actor.open_dataset()
        await actor.set_value('OUTPUT', {'items': 0, 'state': 'initializing'})
        cfg = normalize_input(supplied_input if supplied_input is not None else await actor.get_input() or {})
        database, db_info = await load(actor)
        matcher = await asyncio.to_thread(Matcher, database['technologies'], database['categories'])
        valid_categories = {str(c).casefold() for c in database['categories']} | {c['name'].casefold() for c in database['categories'].values()}
        if set(cfg['includeCategories']) - valid_categories:
            raise InputError('Unknown category filter: ' + ', '.join(set(cfg['includeCategories']) - valid_categories))
        sink, summaries = ResultSink(actor, len(cfg['urls'])), []
        sem = asyncio.Semaphore(min(cfg['maxConcurrency'], 2) if cfg['renderJs'] else cfg['maxConcurrency'])
        async with PublicClient('TechStackDetectorActor', max_bytes=4_000_000,
                                accept='text/html,application/xhtml+xml;q=0.9,*/*;q=0.8') as client, BrowserPool() as pool:
            async def work(url):
                async with sem:
                    start = time.monotonic()
                    result = {'url': url}
                    try:
                        if sink.full:
                            raise FetchError('budget_limit', 'Result budget reached.')
                        async with asyncio.timeout(cfg['timeoutSeconds']):
                            row, diagnostic = await inspect_site(url, cfg, client, matcher, pool)
                        result.update(saved=await sink.emit(row, public_url(row['finalUrl'])), technologies=len(row['technologies']), **diagnostic)
                    except TimeoutError:
                        result['error'] = {'code': 'site_timeout', 'message': f'Site exceeded {cfg["timeoutSeconds"]} seconds.'}
                    except (FetchError, InputError) as exc:
                        result['error'] = error_record(exc)
                    finally:
                        result['seconds'] = round(time.monotonic() - start, 3)
                        summaries.append(result)
                        LOG.info('Site result: %s', result)
            async with asyncio.TaskGroup() as group:
                for url in cfg['urls']:
                    group.create_task(work(url))
            await actor.set_value('HTTP_AUDIT', client.audit)
        await actor.set_value('OUTPUT', {'items': sink.count, 'sites': summaries, 'fingerprints': db_info,
                                        'databaseTechnologies': len(database['technologies']), 'finishedAt': utc_now()})
        await actor.set_status_message(f'Saved {sink.count} site results; failures in OUTPUT only.')
