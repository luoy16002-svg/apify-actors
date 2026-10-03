from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re

from PIL import Image
from playwright.async_api import Error, TimeoutError as BrowserTimeout

from .browser import new_context
from .cmp import CMP_SELECTORS, HIDE_BANNERS
from .common import utc_now
from .net import FetchError

PRESETS = {'desktop': (1440, 900), 'laptop': (1280, 800), 'tablet': (820, 1180), 'mobile': (390, 844)}
MAX_PIXELS = 60_000_000


def context_options(config):
    preset = config['viewport']
    width, height = (config['width'], config['height']) if preset == 'custom' else PRESETS[preset]
    mobile = preset == 'mobile'
    ua = ('Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36'
          if mobile else 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
    return {'viewport': {'width': width, 'height': height}, 'device_scale_factor': 3 if mobile else 1,
            'is_mobile': mobile, 'has_touch': mobile or preset == 'tablet', 'user_agent': ua + ' WebsiteScreenshotsActor/1.0',
            'color_scheme': 'dark' if config['darkMode'] else 'light', 'locale': 'en-GB'}


def stable_key(url, config):
    relevant = {k: v for k, v in config.items() if k not in {'urls', 'maxConcurrency', 'timeoutSeconds'}}
    return 'capture-' + hashlib.sha256(json.dumps([url, relevant], sort_keys=True).encode()).hexdigest()[:24]


def encode_image(data, format, quality):
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if width * height > MAX_PIXELS:
            raise FetchError('image_too_large', 'Image exceeds 60 million pixels.')
        if format == 'webp':
            buffer = io.BytesIO()
            image.save(buffer, format='WEBP', quality=quality, method=4)
            data = buffer.getvalue()
    return data, width, height


async def scroll(page):
    async def visible_images():
        await page.wait_for_timeout(60)  # allow IntersectionObserver callbacks to assign src/srcset
        await page.evaluate('''async () => {
          const images = [...document.images].filter(img => {
            const r=img.getBoundingClientRect();
            return r.bottom>=0 && r.top<innerHeight && (img.currentSrc || img.src) && !img.complete;
          });
          await Promise.race([
            Promise.all(images.map(img => new Promise(resolve => {
              img.addEventListener('load',resolve,{once:true});
              img.addEventListener('error',resolve,{once:true});
            }))),
            new Promise(resolve => setTimeout(resolve,1000))
          ]);
        }''')
    steps = 0
    while steps < 40:
        await visible_images()
        at_end = await page.evaluate('''() => {
          const y = window.scrollY;
          window.scrollBy(0, Math.max(200, window.innerHeight * .8));
          return window.scrollY === y || window.scrollY + window.innerHeight >= document.documentElement.scrollHeight;
        }''')
        steps += 1
        if at_end:
            await visible_images()
            break
    await page.evaluate('() => window.scrollTo(0,0)')
    await page.wait_for_timeout(300)
    return steps == 40


async def capture(pool, client, url, config):
    for attempt in range(2):
        context = None
        try:
            async with asyncio.timeout(config['timeoutSeconds']):
                await client.authorize(url)
                options = context_options(config)
                context, state = await new_context(pool, client, options, config['blockAds'])
                page = await context.new_page()
                page.set_default_timeout(config['timeoutSeconds'] * 1000)
                page.on('dialog', lambda dialog: dialog.dismiss())
                page.on('download', lambda download: download.cancel())
                page.on('popup', lambda popup: popup.close())
                strategy = config['waitStrategy']
                try:
                    response = await page.goto(url, wait_until='load' if strategy == 'load' else 'domcontentloaded')
                except Error:
                    if state['navigationError']:
                        raise state['navigationError']
                    raise
                if response is None or response.status >= 400 or response.status == 204:
                    raise FetchError('http_error', f'Navigation returned HTTP {response.status if response else "unknown"}.', response.status if response else None)
                if strategy == 'networkidle':
                    await page.wait_for_load_state('networkidle')
                elif strategy == 'fixed':
                    await page.wait_for_timeout(config['waitDelaySeconds'] * 1000)
                elif strategy == 'selector':
                    await page.locator(config['waitSelector']).first.wait_for(state='visible')
                title = await page.title()
                if re.search(r'(?i)^(just a moment|access denied|attention required|verify you are human|robot or human)', title.strip()):
                    raise FetchError('access_blocked', 'Page displays an access challenge; capture stopped.')
                warnings = []
                hidden = await page.evaluate(HIDE_BANNERS, CMP_SELECTORS) if config['hideCookieBanners'] else 0
                if config['css']:
                    await page.add_style_tag(content=config['css'])
                if config['scrollPage'] and await scroll(page):
                    warnings.append('Lazy-load scrolling stopped at 40 steps; infinite/very long pages may be incomplete.')
                if config['hideCookieBanners']:
                    hidden += await page.evaluate(HIDE_BANNERS, CMP_SELECTORS)
                image_status = await page.evaluate('''() => ({
                  total:document.images.length,
                  pending:[...document.images].filter(i=>(i.currentSrc||i.src) && !i.complete).length,
                  broken:[...document.images].filter(i=>(i.currentSrc||i.src) && i.complete && !i.naturalWidth).length
                })''')
                if image_status['pending'] or image_status['broken']:
                    warnings.append(f"Images at capture: {image_status['pending']} pending, {image_status['broken']} failed to load.")
                selector = config['elementSelector']
                if selector:
                    target = page.locator(selector).first
                    await target.wait_for(state='visible')
                    await target.scroll_into_view_if_needed()
                    box = await target.bounding_box()
                    if not box:
                        raise FetchError('element_not_visible', 'Selected element has no visible box.')
                    width, height = box['width'], box['height']
                else:
                    target = page
                    if config['fullPage']:
                        dims = await page.evaluate('() => ({width: Math.max(document.documentElement.scrollWidth,innerWidth), height: Math.max(document.documentElement.scrollHeight,innerHeight)})')
                        width, height = dims['width'], dims['height']
                    else:
                        width, height = options['viewport'].values()
                if width * height * options['device_scale_factor'] ** 2 > MAX_PIXELS:
                    raise FetchError('image_too_large', 'Capture would exceed 60 million pixels; use viewport or element mode.')
                shot_args = {'type': 'jpeg' if config['format'] == 'jpeg' else 'png', 'animations': 'disabled'}
                if config['format'] == 'jpeg':
                    shot_args['quality'] = config['quality']
                if not selector:
                    shot_args['full_page'] = config['fullPage']
                data = await target.screenshot(**shot_args)
                data, width, height = await asyncio.to_thread(encode_image, data, config['format'], config['quality'])
                pdf = await page.pdf(format=config['pdfFormat'], print_background=config['printBackground']) if config['pdf'] else None
                if state['blocked']:
                    warnings.append('Some resources were blocked by policy: ' + json.dumps(state['reasons'], sort_keys=True))
                row = {'url': url, 'finalUrl': page.url, 'statusCode': response.status, 'title': title,
                       'viewport': {**options['viewport'], 'deviceScaleFactor': options['device_scale_factor'], 'preset': config['viewport']},
                       'fullPage': config['fullPage'] and not bool(selector), 'format': config['format'],
                       'byteSize': len(data), 'width': width, 'height': height, 'capturedAt': utc_now(),
                       'warnings': warnings}
                metrics = {'hiddenBanners': hidden, 'requests': state['requests'], 'blockedResources': state['blocked'],
                           'blockedAds': state['blockedAds'], 'crashRetries': attempt, 'images': image_status}
                return row, data, pdf, metrics
        except (TimeoutError, BrowserTimeout) as exc:
            raise FetchError('page_timeout', f'Page exceeded its {config["timeoutSeconds"]} second timeout.') from exc
        except Error as exc:
            crashed = pool.browser is not None and not pool.browser.is_connected()
            if attempt == 0 and crashed:
                continue
            raise FetchError('browser_error', str(exc).splitlines()[0][:300]) from exc
        finally:
            if context:
                try:
                    await context.close()
                except Error:
                    pass
    raise FetchError('browser_crash', 'Browser crashed twice.')
