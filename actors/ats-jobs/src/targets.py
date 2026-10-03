from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .net import InputError, public_url

SYSTEMS = ('greenhouse', 'ashby', 'workable', 'smartrecruiters', 'recruitee', 'personio', 'lever')
SLUG = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')


@dataclass(frozen=True)
class Board:
    ats: str
    slug: str
    region: str = 'global'

    @property
    def identity(self):
        # Personio .de/.com are presentation hosts for the same company feed.
        # Only Lever's EU/global installations represent distinct source namespaces.
        namespace = self.region if self.ats == 'lever' else 'global'
        return f'{self.ats}:{namespace}:{self.slug.lower()}'

    @property
    def careers(self):
        bases = {'greenhouse': 'https://job-boards.greenhouse.io/', 'ashby': 'https://jobs.ashbyhq.com/',
                 'workable': 'https://apply.workable.com/', 'smartrecruiters': 'https://careers.smartrecruiters.com/',
                 'lever': 'https://jobs.eu.lever.co/' if self.region == 'eu' else 'https://jobs.lever.co/'}
        if self.ats == 'recruitee':
            return f'https://{self.slug}.recruitee.com/'
        if self.ats == 'personio':
            return f'https://{self.slug}.jobs.personio.{self.region if self.region in {"com", "de"} else "de"}/'
        return bases[self.ats] + self.slug


def from_url(value):
    p = urlsplit(public_url(value))
    host = p.hostname
    parts = [s for s in p.path.split('/') if s]
    first = parts[0] if parts else ''
    query = parse_qs(p.query)
    ats, slug, region = None, first, 'global'
    if host in {'boards.greenhouse.io', 'job-boards.greenhouse.io', 'boards.eu.greenhouse.io'}:
        ats = 'greenhouse'
        if first == 'embed':
            slug = query.get('for', [''])[0]
    elif host == 'boards-api.greenhouse.io' and len(parts) >= 3 and parts[:2] == ['v1', 'boards']:
        ats, slug = 'greenhouse', parts[2]
    elif host == 'jobs.ashbyhq.com':
        ats = 'ashby'
    elif host == 'api.ashbyhq.com' and parts[:2] == ['posting-api', 'job-board'] and len(parts) >= 3:
        ats, slug = 'ashby', parts[2]
    elif host == 'apply.workable.com':
        ats = 'workable'
        if parts[:4] == ['api', 'v1', 'widget', 'accounts'] and len(parts) >= 5:
            slug = parts[4]
    elif host in {'www.workable.com', 'workable.com'} and parts[:2] == ['api', 'accounts'] and len(parts) >= 3:
        ats, slug = 'workable', parts[2]
    elif host in {'jobs.smartrecruiters.com', 'careers.smartrecruiters.com'}:
        ats = 'smartrecruiters'
    elif host in {'jobs.lever.co', 'jobs.eu.lever.co'}:
        ats, region = 'lever', 'eu' if host == 'jobs.eu.lever.co' else 'global'
    elif re.fullmatch(r'[a-z0-9-]+\.recruitee\.com', host):
        ats, slug = 'recruitee', host.split('.')[0]
    elif re.fullmatch(r'[a-z0-9-]+\.jobs\.personio\.(de|com)', host):
        ats, slug, region = 'personio', host.split('.')[0], host.rsplit('.', 1)[1]
    if not ats or not SLUG.fullmatch(slug) or slug.lower() in {'api', 'embed', 'js', 'job_board'}:
        return None
    return Board(ats, slug, region)


def detect(page):
    # Only explicit ATS URLs embedded in links, iframes, or script/config text.
    page = html.unescape(page).replace('\\/', '/')
    found = {}
    for value in re.findall(r'(?:https?:)?//[^\s<>"\'`\\]+', page):
        try:
            board = from_url(('https:' + value) if value.startswith('//') else value)
        except ValueError:
            continue
        if board:
            found[board.identity] = board
    return list(found.values())


def company_input(item):
    if isinstance(item, str):
        return company_input({'url': item} if ('.' in item or '://' in item) else {'slug': item})
    if not isinstance(item, dict):
        raise InputError('Each company must be a URL/slug string or an object.')
    if not any(item.get(k) for k in ('url', 'slug', 'website')):
        raise InputError('Company needs url, slug, or website.')
    for key in ('url', 'slug', 'website', 'ats', 'name', 'region'):
        if key in item and (not isinstance(item[key], str) or len(item[key]) > 4096):
            raise InputError(f'Company {key} must be a string.')
    if item.get('ats') and item['ats'].lower() not in SYSTEMS:
        raise InputError('ATS hint must be one of: ' + ', '.join(SYSTEMS))
    if item.get('slug') and not SLUG.fullmatch(item['slug']):
        raise InputError('Company slug must contain only letters, digits, underscores, or hyphens.')
    if item.get('region', 'global') not in {'global', 'eu', 'de', 'com'}:
        raise InputError('region must be global, eu, de, or com.')
    ats, region = item.get('ats', '').lower(), item.get('region', 'global')
    allowed_regions = {'lever': {'global', 'eu'}, 'personio': {'global', 'de', 'com'}}
    if ats and region not in allowed_regions.get(ats, {'global'}):
        raise InputError('region does not apply to the selected ATS.')
    return item.copy()
