"""Conservative HTTP, normalization, and paid-output helpers.

This file is intentionally copied into each standalone Actor.
"""
from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from protego import Protego

LOG = logging.getLogger('apify.public_data')
USER_AGENT = 'PublicBusinessDataActor/1.0'
ITEM_EVENT = 'apify-default-dataset-item'


class SourceError(RuntimeError):
    """An unavailable, forbidden, or unexpectedly changed source."""


class SchemaError(SourceError):
    """The source no longer has the documented response shape."""


def text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return ' '.join(value.split()) or None


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or isinstance(value, (dict, list)):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def integer(value: Any) -> int | None:
    result = number(value)
    return int(result) if result is not None and result.is_integer() else None


def boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {'true', 'false'}:
        return value.lower() == 'true'
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        return None


def require_int(data: dict, key: str, default: int, low: int, high: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{key} must be an integer between {low} and {high}.')
    return value


def require_string(data: dict, key: str, default: str = '') -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError(f'{key} must be a string of at most 300 characters.')
    return value.strip()


def common_input(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError('Input must be a JSON object.')
    delay = data.get('requestDelaySeconds', 1.2)
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 1 <= delay <= 60:
        raise ValueError('requestDelaySeconds must be a number between 1 and 60.')
    proxy = data.get('proxyConfiguration', {'useApifyProxy': False})
    if not isinstance(proxy, dict) or not isinstance(proxy.get('useApifyProxy', False), bool):
        raise ValueError('proxyConfiguration must be an Apify proxy configuration object.')
    return {
        'maxItems': require_int(data, 'maxItems', 20, 1, 10000),
        'pageSize': require_int(data, 'pageSize', 5000, 1, 5000),
        'maxPages': require_int(data, 'maxPages', 100, 1, 500),
        'requestDelaySeconds': float(delay),
        'proxyConfiguration': proxy,
    }


class PoliteClient:
    """Serial GET requests to an explicit origin/path, with robots and backoff."""

    def __init__(self, origin: str, path_prefix: str, *, delay: float = 1.2,
                 proxy_url: str | None = None, headers: dict | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 sleep=asyncio.sleep, monotonic=time.monotonic):
        self.origin = origin.rstrip('/')
        self.path_prefix = path_prefix
        self.delay = delay
        self.sleep = sleep
        self.monotonic = monotonic
        self.last_request: float | None = None
        self.robots: Protego | None = None
        self.robots_checked = False
        self.lock = asyncio.Lock()
        self.request_count = 0
        self.retry_count = 0
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30), follow_redirects=False, trust_env=False,
            proxy=proxy_url, transport=transport,
            headers={'User-Agent': USER_AGENT, 'Accept': 'application/json', **(headers or {})},
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def _request(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(4):
            if self.last_request is not None:
                remaining = self.delay - (self.monotonic() - self.last_request)
                if remaining > 0:
                    await self.sleep(remaining)
            self.last_request = self.monotonic()
            self.request_count += 1
            try:
                # Stream with a size ceiling so a changed endpoint cannot exhaust memory.
                async with self.client.stream('GET', url, params=params) as response:
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 20_000_000:
                            raise SourceError('Source response exceeds 20 MB; reduce pageSize.')
                        chunks.append(chunk)
                    result = httpx.Response(response.status_code, headers=response.headers,
                                            content=b''.join(chunks), request=response.request)
            except httpx.TransportError as exc:
                if attempt == 3:
                    raise SourceError(f'Network request failed after 4 attempts ({type(exc).__name__}).') from exc
                retry_delay = 2 ** attempt + random.uniform(0, 0.25)
            else:
                if result.status_code not in {429, 500, 502, 503, 504}:
                    return result
                if attempt == 3:
                    raise SourceError(f'Source returned HTTP {result.status_code} after 4 attempts.')
                retry_delay = 2 ** attempt + random.uniform(0, 0.25)
                retry_after = result.headers.get('Retry-After')
                if retry_after:
                    try:
                        retry_delay = max(retry_delay, float(retry_after))
                    except ValueError:
                        try:
                            deadline = parsedate_to_datetime(retry_after)
                            retry_delay = max(retry_delay, (deadline - datetime.now(timezone.utc)).total_seconds())
                        except (TypeError, ValueError, OverflowError):
                            pass
                if not math.isfinite(retry_delay) or retry_delay > 60:
                    raise SourceError('Source requests a long Retry-After; stop and try again later.')
            self.retry_count += 1
            LOG.warning('Transient source failure; retry %s/3 in %.2f seconds.', attempt + 1, retry_delay)
            await self.sleep(retry_delay)
        raise AssertionError('Unreachable')

    async def _check_robots(self, url: str) -> None:
        if not self.robots_checked:
            response = await self._request(self.origin + '/robots.txt')
            if response.status_code in {404, 410}:
                LOG.info('robots.txt absent (HTTP %s); using documented public API.', response.status_code)
            elif response.status_code == 200:
                if '<html' in response.text[:500].lower() or '<!doctype html' in response.text[:500].lower():
                    raise SourceError('robots.txt returned HTML; refusing ambiguous crawling policy.')
                self.robots = Protego.parse(response.text)
                crawl_delay = self.robots.crawl_delay(USER_AGENT)
                if crawl_delay is not None:
                    self.delay = max(self.delay, float(crawl_delay))
                if self.delay > 60:
                    raise SourceError('robots.txt requires a delay above the supported 60 seconds.')
                LOG.info('robots.txt checked; minimum request interval %.2f seconds.', self.delay)
            else:
                raise SourceError(f'Cannot verify robots.txt (HTTP {response.status_code}); stopping.')
            self.robots_checked = True
        if self.robots is not None and not self.robots.can_fetch(url, USER_AGENT):
            raise SourceError('robots.txt disallows the requested API path; stopping.')

    async def get_json(self, path: str, params: dict | None = None) -> Any:
        parts = urlsplit(path)
        if (parts.scheme or parts.netloc or parts.query or parts.fragment
                or not path.startswith(self.path_prefix) or '..' in path or '%' in path or '\\' in path):
            raise ValueError('Only the configured public API path is allowed.')
        url = self.origin + path
        async with self.lock:
            full_url = str(httpx.URL(url, params=params)) if params else url
            await self._check_robots(full_url)
            response = await self._request(url, params)
        if response.status_code != 200:
            raise SourceError(f'Public API returned HTTP {response.status_code}; no access workaround attempted.')
        try:
            return response.json()
        except ValueError as exc:
            raise SchemaError('Expected JSON but the source returned another format.') from exc


class ResultSink:
    """Deduplicate and cap output, respecting Apify's synthetic item budget."""

    def __init__(self, actor, max_items: int):
        self.actor = actor
        self.max_items = max_items
        self.seen: set[str] = set()
        self.count = 0
        self.duplicates = 0

    @property
    def full(self) -> bool:
        return (self.count >= self.max_items or
                self.actor.get_charging_manager().is_event_charge_limit_reached(ITEM_EVENT))

    async def emit(self, item: dict, key: str) -> bool:
        if key in self.seen:
            self.duplicates += 1
            return False
        if self.full:
            return False
        # Synthetic billing is configured in Console, never charged manually here.
        result = await self.actor.push_data(item)
        if result.event_charge_limit_reached and result.charged_count == 0:
            return False
        self.seen.add(key)
        self.count += 1
        return True


async def proxy_url(actor, config: dict) -> str | None:
    if not config.get('useApifyProxy') and not config.get('proxyUrls'):
        return None
    proxy = await actor.create_proxy_configuration(actor_proxy_input=config)
    if proxy is None:
        raise ValueError('Requested proxy configuration could not be created.')
    # One stable session; never rotate to avoid a restriction.
    return await proxy.new_url(session_id='public-business-data')
