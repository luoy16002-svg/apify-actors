import asyncio
import gzip
from types import SimpleNamespace

import httpx
import pytest

from src.common import ResultSink
from src.net import FetchError, InputError, PublicClient, public_url


@pytest.mark.parametrize('url', ['file:///x', 'http://localhost/', 'https://127.0.0.1/', 'http://169.254.169.254/',
                                 'https://user:pass@example.org/', 'https://example.org:8000/', 'http://[::1]/', 'http://198.18.0.1/'])
def test_reject_nonpublic_urls(url):
    with pytest.raises(InputError):
        public_url(url)


@pytest.mark.parametrize('status,body,code', [(403, '', 'robots_unavailable'), (401, '', 'robots_unavailable'),
    (200, '<!doctype html><html>x</html>', 'robots_unknown'), (200, 'User-agent: *\nDisallow: /', 'robots_disallowed')])
def test_no_page_fetched_if_robots_unclear_or_disallowed(status, body, code):
    calls = []
    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(status, text=body)
    async def run():
        async with PublicClient('Test', delay=0, check_dns=False, transport=httpx.MockTransport(handler)) as c:
            with pytest.raises(FetchError) as exc:
                await c.get('https://example.org/private')
            assert exc.value.code == code
    asyncio.run(run())
    assert calls == ['https://example.org/robots.txt']


def test_gzip_decompressed_exactly_once_and_redirect_robots_checked():
    calls = []
    def handler(req):
        calls.append(str(req.url))
        if req.url.path == '/robots.txt':
            return httpx.Response(404)
        if req.url.host == 'a.example':
            return httpx.Response(302, headers={'Location': 'https://b.example/page'})
        return httpx.Response(200, content=gzip.compress(b'{"ok":true}'),
                              headers=[(b'content-encoding', b'gzip'), (b'x-snowman', '\u26c4'.encode('utf-8'))])
    async def run():
        async with PublicClient('Test', delay=0, check_dns=False, transport=httpx.MockTransport(handler)) as c:
            assert await c.json('https://a.example/page') == {'ok': True}
    asyncio.run(run())
    assert calls == ['https://a.example/robots.txt', 'https://a.example/page', 'https://b.example/robots.txt', 'https://b.example/page']


def test_redirect_private_address_blocked_before_request():
    calls = []
    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(404) if req.url.path == '/robots.txt' else httpx.Response(302, headers={'location': 'http://127.0.0.1/'})
    async def run():
        async with PublicClient('Test', delay=0, check_dns=False, transport=httpx.MockTransport(handler)) as c:
            with pytest.raises(InputError):
                await c.get('https://example.org/')
    asyncio.run(run())
    assert len(calls) == 2


def test_retry_after_and_retry_limit():
    attempts, sleeps = [], []
    async def sleep(n):
        sleeps.append(n)
    def handler(req):
        if req.url.path == '/robots.txt':
            return httpx.Response(404)
        attempts.append(1)
        return httpx.Response(429, headers={'retry-after': '2'})
    async def run():
        async with PublicClient('Test', delay=0, check_dns=False, sleep=sleep, transport=httpx.MockTransport(handler)) as c:
            with pytest.raises(FetchError):
                await c.get('https://example.org/')
            assert c.retries == 2
    asyncio.run(run())
    assert len(attempts) == 3 and sleeps == [2, 2]


def test_parallel_sink_dedupe_and_budget_are_atomic():
    class Actor:
        rows = []
        def get_charging_manager(self):
            return self
        def is_event_charge_limit_reached(self, _):
            return len(self.rows) >= 2
        async def push_data(self, row):
            await asyncio.sleep(0)
            self.rows.append(row)
            return SimpleNamespace(event_charge_limit_reached=False, charged_count=0)
    async def run():
        actor = Actor()
        sink = ResultSink(actor, 5)
        await asyncio.gather(*(sink.emit({'id': i}, str(i)) for i in [1, 1, 2, 3]))
        assert len(actor.rows) == 2 and sink.count == 2 and sink.duplicates == 1
    asyncio.run(run())


def test_known_source_prohibition_stops_before_any_http():
    def handler(_):
        pytest.fail('A source with a known explicit prohibition must not be requested.')
    async def run():
        async with PublicClient('Test', check_dns=False, transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(FetchError) as error:
                await client.get('https://ko-fi.com/')
            assert error.value.code == 'terms_disallowed' and client.requests == 0
    asyncio.run(run())
