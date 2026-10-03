"""Public HTTP only, robots per origin, redirects checked, paced bounded GETs."""
from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import socket
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from protego import Protego

from .common import SourceError


class InputError(ValueError):
    code = 'invalid_input'


class FetchError(SourceError):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code, self.status = code, status


def public_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise InputError('URL must be a nonempty string of at most 4096 characters.')
    value = value.strip()
    if '://' not in value:
        value = 'https://' + value
    try:
        p = urlsplit(value)
        port = p.port
    except ValueError as exc:
        raise InputError('Invalid URL or port.') from exc
    if (p.scheme not in {'http', 'https'} or not p.hostname or p.username is not None
            or p.password is not None or port not in {None, 80, 443}
            or any(ord(c) < 32 for c in value) or '\\' in value):
        raise InputError('Only public HTTP(S) URLs on ports 80/443 without credentials are supported.')
    host = p.hostname.encode('idna').decode().lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise InputError('Local or private network URLs are not supported.')
    try:
        ip = ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise InputError('Local or private network URLs are not supported.')
    authority = f'[{host}]' if ':' in host else host
    if port and port != (443 if p.scheme == 'https' else 80):
        authority += f':{port}'
    return urlunsplit((p.scheme, authority, p.path or '/', p.query, ''))


class PublicClient:
    def __init__(self, name, delay=1.2, timeout=30, max_bytes=20_000_000,
                 transport=None, check_dns=True, sleep=asyncio.sleep, accept=None):
        self.ua = name + '/1.0 (public pages; respects robots.txt)'
        self.delay, self.max_bytes = delay, max_bytes
        self.sleep, self.check_dns = sleep, check_dns
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False,
                                       transport=transport, headers={'User-Agent': self.ua, **({'Accept': accept} if accept else {})},
                                       limits=httpx.Limits(max_connections=10))
        self.robots, self.robots_errors, self.locks, self.last, self.delays = {}, {}, {}, {}, {}
        self.dns_cache = {}
        self.audit = []
        self.requests = self.retries = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    def lock(self, origin):
        return self.locks.setdefault(origin, asyncio.Lock())

    async def validate(self, url):
        url = public_url(url)
        p = urlsplit(url)
        # Explicit content-collection prohibition confirmed in source policy on 2026-10-03:
        # https://help.ko-fi.com/hc/en-us/articles/19789627403293-Ko-fi-s-stance-on-AI
        if p.hostname == 'ko-fi.com' or p.hostname.endswith('.ko-fi.com'):
            raise FetchError('terms_disallowed', 'Ko-fi explicitly prohibits automated content collection; source excluded.')
        if self.check_dns and self.dns_cache.get(p.hostname, 0) < time.monotonic():
            try:
                addresses = await asyncio.get_running_loop().getaddrinfo(p.hostname, p.port or 443,
                                                                         type=socket.SOCK_STREAM)
            except OSError as exc:
                raise FetchError('dns_error', 'Public hostname could not be resolved.') from exc
            # Local QA may run behind a DNS-based tunnel mapping public names to RFC 2544
            # benchmarking addresses. This explicit local-only switch never permits LAN,
            # loopback, link-local, literal IP input, or cloud Actor runs.
            tunnel = (os.environ.get('BATCH3_LOCAL_TUN_DNS') == '1' and
                      os.environ.get('APIFY_IS_AT_HOME', '').lower() not in {'1', 'true'})
            def allowed(address):
                ip = ipaddress.ip_address(address)
                return ip.is_global or (tunnel and ip in ipaddress.ip_network('198.18.0.0/15'))
            if not addresses or any(not allowed(a[4][0]) for a in addresses):
                raise FetchError('private_address', 'Hostname resolves to a private or non-global address.')
            self.dns_cache[p.hostname] = time.monotonic() + 30
        return url

    async def pace(self, origin):
        delay = self.delays.get(origin, self.delay)
        remaining = self.last.get(origin, 0) + delay - time.monotonic()
        if remaining > 0:
            await self.sleep(remaining)
        self.last[origin] = time.monotonic()

    async def _raw(self, url):
        origin = str(httpx.URL(url).copy_with(path='/', query=None)).rstrip('/')
        for attempt in range(3):
            await self.pace(origin)
            self.requests += 1
            retry_delay = 2 ** attempt
            try:
                async with self.client.stream('GET', url) as response:
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise FetchError('response_too_large', 'Response exceeds the supported size limit.')
                        chunks.append(chunk)
                    headers = [(k, v) for k, v in response.headers.raw
                               if k.lower() not in {b'content-encoding', b'content-length'}]
                    result = httpx.Response(response.status_code, headers=headers,
                                            content=b''.join(chunks), request=response.request)
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise FetchError('network_error', f'GET failed after 3 attempts ({type(exc).__name__}).') from exc
            else:
                self.audit.append({'url': url, 'status': result.status_code, 'bytes': len(result.content)})
                if result.status_code not in {429, 500, 502, 503, 504}:
                    return result
                if attempt == 2:
                    raise FetchError('http_error', f'HTTP {result.status_code} after 3 attempts.', result.status_code)
                retry_after = result.headers.get('retry-after')
                if retry_after:
                    try:
                        retry_delay = max(retry_delay, float(retry_after))
                    except ValueError:
                        try:
                            retry_delay = max(retry_delay, (parsedate_to_datetime(retry_after) -
                                                           datetime.now(timezone.utc)).total_seconds())
                        except (TypeError, ValueError, OverflowError):
                            pass
                if not math.isfinite(retry_delay) or retry_delay > 30:
                    raise FetchError('retry_later', 'Source requested a long Retry-After; stopped.', result.status_code)
            self.retries += 1
            await self.sleep(retry_delay)
        raise AssertionError('unreachable')

    async def _robots(self, origin):
        if origin in self.robots_errors:
            raise self.robots_errors[origin]
        if origin in self.robots:
            return
        try:
            robots_url = origin + '/robots.txt'
            for _ in range(4):
                await self.validate(robots_url)
                response = await self._raw(robots_url)
                if response.is_redirect and response.headers.get('location'):
                    robots_url = public_url(urljoin(robots_url, response.headers['location']))
                    continue
                break
            if 400 <= response.status_code < 500 and response.status_code != 429:
                # RFC 9309 2.3.1.3: a 4xx robots.txt is "unavailable" and crawlers may access the site.
                rules = None
            elif response.status_code == 200:
                if '<html' in response.text[:1000].lower() or '<!doctype' in response.text[:1000].lower():
                    raise FetchError('robots_unknown', 'robots.txt returned HTML; access policy is ambiguous.')
                rules = Protego.parse(response.text)
                self.delays[origin] = max(self.delay, float(rules.crawl_delay(self.ua) or 0))
                if self.delays[origin] > 30:
                    raise FetchError('robots_delay', 'robots.txt requires more than 30 seconds between requests.')
            else:
                raise FetchError('robots_unavailable', f'Cannot verify robots.txt (HTTP {response.status_code}).', response.status_code)
            self.robots[origin] = rules
            self.audit.append({'url': origin + '/robots.txt', 'policy': response.text if rules else 'absent',
                               'status': response.status_code})
        except FetchError as exc:
            self.robots_errors[origin] = exc
            raise

    async def authorize(self, url, pace=False):
        url = await self.validate(url)
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        async with self.lock(origin):
            await self._robots(origin)
            rules = self.robots[origin]
            if rules and not rules.can_fetch(url, self.ua):
                raise FetchError('robots_disallowed', 'robots.txt disallows this URL.')
            if pace:
                await self.pace(origin)
        return url

    async def get(self, url):
        for _ in range(6):
            url = await self.authorize(url)
            p = urlsplit(url)
            async with self.lock(f'{p.scheme}://{p.netloc}'):
                response = await self._raw(url)
            if response.is_redirect and response.headers.get('location'):
                url = urljoin(url, response.headers['location'])
                continue
            if response.status_code != 200:
                raise FetchError('http_error', f'HTTP {response.status_code}; no workaround attempted.', response.status_code)
            return response
        raise FetchError('redirect_limit', 'More than 5 redirects.')

    async def json(self, url):
        response = await self.get(url)
        try:
            return response.json()
        except ValueError as exc:
            raise FetchError('invalid_response', 'Expected a JSON response.') from exc


def error_record(exc):
    return {'code': getattr(exc, 'code', type(exc).__name__), 'message': str(exc)[:500],
            'statusCode': getattr(exc, 'status', None)}
