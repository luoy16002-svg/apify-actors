"""Batch 2 input validation, contact minimization and public HTTP helpers."""
from __future__ import annotations
import asyncio
import ipaddress
import re
import socket
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, unquote
import httpx
from protego import Protego
from .common import LOG, USER_AGENT, PoliteClient, SourceError, SchemaError, number, integer, text, utc_now

class InputError(ValueError):
    """Invalid or incompatible actor input."""

class HttpError(SourceError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Public source returned HTTP {status}.')

def timestamp(value):
    if not isinstance(value, str) or not value.strip(): return None
    try: dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        try: dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError): return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    try: return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, OverflowError): return None

def require_int(data, key, default, low, high):
    value = data.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise InputError(f'{key} must be an integer between {low} and {high}.')
    return value

def require_bool(data, key, default=False):
    value = data.get(key, default)
    if type(value) is not bool: raise InputError(f'{key} must be a boolean.')
    return value

def require_string(data, key, default='', limit=1000):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise InputError(f'{key} must be a string of at most {limit} characters.')
    return value.strip()

def string_list(data, key, default=None, limit=25):
    value = data.get(key, default or [])
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, str) or not v.strip() or len(v) > 2000 for v in value):
        raise InputError(f'{key} must be an array of at most {limit} nonempty strings.')
    return list(dict.fromkeys(v.strip() for v in value))

def date_input(data, key, end=False):
    value = require_string(data, key)
    if not value: return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?', value):
        raise InputError(f'{key} must be YYYY-MM-DD or an ISO timestamp with timezone.')
    result = timestamp(value)
    if not result: raise InputError(f'{key} is not a valid date.')
    if end and len(value) == 10:
        try:
            result = (datetime.fromisoformat(result) + timedelta(days=1) - timedelta(microseconds=1)).isoformat().replace('+00:00', 'Z')
        except OverflowError: raise InputError(f'{key} is outside the supported date range.') from None
    return result

def date_range(data, start_key, end_key):
    start, end = date_input(data, start_key), date_input(data, end_key, end=True)
    if start and end and datetime.fromisoformat(start) > datetime.fromisoformat(end):
        raise InputError(f'{start_key} must not be later than {end_key}.')
    return start, end

def in_range(value, start, end):
    if not start and not end: return True
    parsed = timestamp(value)
    if not parsed: return False
    dt = datetime.fromisoformat(parsed)
    return (not start or dt >= datetime.fromisoformat(start)) and (not end or dt <= datetime.fromisoformat(end))

def common_input(data, minimum_delay=1.2):
    if not isinstance(data, dict): raise InputError('Input must be a JSON object.')
    delay = data.get('requestDelaySeconds', minimum_delay)
    if isinstance(delay, bool) or number(delay) is None or not isinstance(delay, (int, float)) or not minimum_delay <= delay <= 60:
        raise InputError(f'requestDelaySeconds must be between {minimum_delay} and 60.')
    return {'requestDelaySeconds': float(delay), 'maxPages': require_int(data, 'maxPages', 100, 1, 500)}

def country_code(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z]{2}', value):
        raise InputError('Country codes must contain two letters.')
    return value.lower()

def apple_id(value, podcast=False):
    if re.fullmatch(r'[1-9][0-9]{0,19}', value): return value
    try:
        parts = urlsplit(value)
        hosts = {'podcasts.apple.com', 'itunes.apple.com'} if podcast else {'apps.apple.com', 'itunes.apple.com'}
        match = re.search(r'/id([1-9][0-9]{0,19})(?:/|$)', parts.path)
        if parts.scheme == 'https' and parts.hostname in hosts and not parts.username and not parts.password and parts.port in {None,443} and match:
            return match.group(1)
    except ValueError: pass
    raise InputError('Expected an Apple numeric ID or an official HTTPS Apple URL containing /idNNN.')

EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', re.I)
PHONE = re.compile(r'(?<![\w])\+?\(?\d[\d ().-]{5,}\d(?![\w])')

def redact(value):
    value = text(value)
    def phone(match):
        candidate = match[0]
        digits = re.sub(r'\D', '', candidate)
        if 7 <= len(digits) <= 15 and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', candidate.strip()):
            return '[redacted phone]'
        return candidate
    return PHONE.sub(phone, EMAIL.sub('[redacted email]', value)) if value else value

class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script','style'}: self.hidden += 1
        if tag in {'br','p','div','li'}: self.parts.append(' ')
    def handle_endtag(self, tag):
        if tag in {'script','style'}: self.hidden = max(0, self.hidden - 1)
        if tag in {'p','div','li','br'}: self.parts.append(' ')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

def plain_text(value):
    if not isinstance(value, str): return None
    parser = _PlainText()
    parser.feed(value)
    return redact(unescape(''.join(parser.parts)))

def public_url(value):
    if not isinstance(value, str) or len(value) > 4000 or any(ord(c) < 32 for c in value):
        raise InputError('Expected a public HTTP(S) URL.')
    try:
        p = urlsplit(value)
        if p.scheme not in {'https','http'} or not p.hostname or p.username or p.password or p.port not in {None,80,443} or '\\' in value:
            raise ValueError
        host = p.hostname.lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost','.local','.internal')) or '.' not in host: raise ValueError
        try: address = ipaddress.ip_address(host)
        except ValueError: address = None
        if address is not None and not address.is_global: raise ValueError
        return p._replace(fragment='').geturl()
    except ValueError as exc:
        raise InputError('Only public HTTP(S) URLs on standard ports without credentials are supported.') from exc

def output_url(value):
    try: url = public_url(value)
    except InputError: return None
    if EMAIL.search(unquote(url)) or re.match(r'(?i)https?://(?:wa.me|api.whatsapp.com)/', url): return None
    return url

# Fixed service identities are controlled by this code, never by actor input.
# This also supports networks whose DNS maps internet hosts through a local proxy.
KNOWN_PUBLIC_ORIGINS = {
    'https://itunes.apple.com', 'https://public.api.bsky.app', 'https://bsky.social',
    'https://www.find-tender.service.gov.uk', 'https://www.contractsfinder.service.gov.uk',
    'https://api.ted.europa.eu', 'https://feeds.npr.org', 'https://feeds.bbci.co.uk', 'https://feeds.megaphone.fm',
}

class PublicClient(PoliteClient):
    """Serial requests, per-origin robots, public DNS and checked redirects."""
    def __init__(self, *, allowed_origins=None, **kwargs):
        super().__init__('', '/', **kwargs)
        self.allowed_origins = set(allowed_origins) if allowed_origins else None
        self.check_dns = kwargs.get('transport') is None
        self.robots_by_origin = {}
    async def _validate(self, url):
        p = urlsplit(public_url(url))
        origin = f'{p.scheme}://{p.netloc}'
        if self.allowed_origins is not None and origin not in self.allowed_origins:
            raise SourceError('Request left the configured official API origins.')
        if self.check_dns and origin not in KNOWN_PUBLIC_ORIGINS:
            try:
                addresses = await asyncio.get_running_loop().getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            except OSError: raise SourceError('Source hostname could not be resolved.') from None
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise SourceError('Source hostname must resolve exclusively to public addresses.')
        return origin
    async def _request(self, url, params=None, **kwargs):
        await self._validate(url)
        return await super()._request(url, params, **kwargs)
    async def _check_robots(self, url):
        origin = await self._validate(url)
        if origin not in self.robots_by_origin:
            robot_url, visited = origin + '/robots.txt', set()
            for _ in range(6):
                if robot_url in visited: raise SourceError('robots.txt redirect loop.')
                visited.add(robot_url)
                response = await self._request(robot_url)
                if response.status_code in {301,302,303,307,308} and response.headers.get('location'):
                    target = urljoin(robot_url, response.headers['location'])
                    if robot_url.startswith('https:') and not target.startswith('https:'):
                        raise SourceError('Refusing robots.txt HTTPS downgrade.')
                    robot_url = target
                    continue
                break
            else: raise SourceError('Too many robots.txt redirects.')
            robot = None
            if response.status_code == 200:
                if re.search(r'<(?:!doctype|html|body)\b', response.text[:1000], re.I):
                    raise SourceError('robots.txt returned HTML; cannot determine crawl policy.')
                robot = Protego.parse(response.text)
                self.delay = max(self.delay, float(robot.crawl_delay(USER_AGENT) or 0))
                rate = robot.request_rate(USER_AGENT)
                if rate: self.delay = max(self.delay, rate.seconds / rate.requests)
                if self.delay > 60: raise SourceError('robots.txt requests a delay above 60 seconds.')
            elif response.status_code not in {404,410}:
                raise SourceError(f'Cannot verify robots.txt (HTTP {response.status_code}).')
            self.robots_by_origin[origin] = robot
            LOG.info('robots.txt checked for %s (HTTP %s).', origin, response.status_code)
        robot = self.robots_by_origin[origin]
        if robot and not robot.can_fetch(url, USER_AGENT): raise SourceError('robots.txt disallows this source path.')
    async def request(self, url, *, params=None, method='GET', json_body=None, headers=None):
        url = str(httpx.URL(url, params=params)) if params else url
        async with self.lock:
            visited = set()
            for _ in range(6):
                if url in visited: raise SourceError('Source redirect loop.')
                visited.add(url)
                await self._check_robots(url)
                result = await self._request(url, method=method, json_body=json_body, headers=headers)
                if result.status_code in {301,302,303,307,308}:
                    if method != 'GET' or headers or not result.headers.get('location'):
                        raise SourceError('Refusing a redirect for this request.')
                    target = urljoin(url, result.headers['location'])
                    if url.startswith('https:') and not target.startswith('https:'):
                        raise SourceError('Refusing an HTTPS downgrade redirect.')
                    url = target
                    continue
                if result.status_code != 200: raise HttpError(result.status_code)
                return result
            raise SourceError('Too many source redirects.')
    async def get_json(self, url, params=None, **kwargs):
        result = await self.request(url, params=params, **kwargs)
        try: data = result.json()
        except ValueError: raise SchemaError('Expected JSON from source.') from None
        if not isinstance(data, dict): raise SchemaError('Expected a JSON object from source.')
        return data

def rows_field(data, key):
    rows = data.get(key)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SchemaError(f'Expected source array: {key}.')
    return rows

async def finish(actor, client, sink, stats):
    stats.update(items=sink.count, duplicates=sink.duplicates, requests=client.request_count,
                 retries=client.retry_count, finishedAt=utc_now())
    await actor.set_value('RUN_STATS', stats)
    await actor.set_status_message(f'Saved {sink.count} results.')
    LOG.info('Finished: %s', stats)
