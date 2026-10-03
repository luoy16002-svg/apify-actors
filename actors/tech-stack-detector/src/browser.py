"""One bounded Chromium instance, isolated page contexts, public robots-aware routes."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from playwright.async_api import Error, async_playwright

from .net import FetchError, InputError

AD_DOMAINS = frozenset({'doubleclick.net', 'googlesyndication.com', 'google-analytics.com',
                       'googletagmanager.com', 'adservice.google.com', 'scorecardresearch.com',
                       'adsrvr.org', 'adnxs.com', 'taboola.com', 'outbrain.com', 'connect.facebook.net'})


def ad_domain(host):
    return any(host == suffix or host.endswith('.' + suffix) for suffix in AD_DOMAINS)


class BrowserPool:
    def __init__(self):
        self.pw = self.browser = None
        self.lock = asyncio.Lock()
        self.restarts = 0

    async def __aenter__(self):
        return self

    async def get(self):
        async with self.lock:
            if self.pw is None:
                self.pw = await async_playwright().start()
            if self.browser is None or not self.browser.is_connected():
                if self.browser is not None:
                    self.restarts += 1
                    try:
                        await self.browser.close()
                    except Error:
                        pass
                self.browser = await self.pw.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
            return self.browser

    async def __aexit__(self, *args):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self.pw:
                await self.pw.stop()


async def new_context(pool, client, options, block_ads=False):
    browser = await pool.get()
    context = await browser.new_context(**options, accept_downloads=False, service_workers='block')
    state = {'requests': 0, 'blocked': 0, 'blockedAds': 0, 'navigationError': None, 'reasons': {}}

    async def route_handler(route):
        request = route.request
        state['requests'] += 1
        is_document = request.is_navigation_request() and request.resource_type == 'document'
        try:
            if state['requests'] > 400:
                raise FetchError('resource_limit', 'Page requested more than 400 resources.')
            if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                raise FetchError('write_request_blocked', 'Non-read browser request blocked.')
            if request.resource_type == 'media':
                raise FetchError('media_blocked', 'Streaming media is not needed for a still capture.')
            if block_ads and ad_domain(urlsplit(request.url).hostname or ''):
                state['blockedAds'] += 1
                await route.abort()
                return
            await client.authorize(request.url, pace=is_document)
        except (FetchError, InputError) as exc:
            state['blocked'] += 1
            code = getattr(exc, 'code', 'invalid_url')
            state['reasons'][code] = state['reasons'].get(code, 0) + 1
            if is_document and request.frame == request.frame.page.main_frame:
                state['navigationError'] = exc
            await route.abort()
            return
        await route.continue_()

    await context.route('**/*', route_handler)
    # WebSockets bypass HTTP routing; a still image/DOM fingerprint does not require them.
    await context.route_web_socket('**/*', lambda ws: ws.close())
    return context, state
