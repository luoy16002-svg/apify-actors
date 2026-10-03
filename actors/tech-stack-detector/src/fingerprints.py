"""Download pinned GPL-3.0 data at runtime; no upstream data is vendored."""
import hashlib
import json
import string

from .net import FetchError, PublicClient

COMMIT = 'eea872af449e207e055398f7369d11ee48c8ea03'
BASE = f'https://raw.githubusercontent.com/enthec/webappanalyzer/{COMMIT}/'
LICENSE = 'GPL-3.0'
FILES = ['src/categories.json', 'src/groups.json'] + [f'src/technologies/{c}.json' for c in '_' + string.ascii_lowercase]


def valid_cache(data):
    return (isinstance(data, dict) and data.get('commit') == COMMIT and data.get('license') == LICENSE
            and isinstance(data.get('technologies'), dict) and len(data['technologies']) > 1000
            and isinstance(data.get('categories'), dict) and isinstance(data.get('groups'), dict)
            and isinstance(data.get('licenseText'), str) and 'GNU GENERAL PUBLIC LICENSE' in data['licenseText']
            and len(data.get('sha256', {})) == len(FILES) + 1)


async def load(actor):
    store = await actor.open_key_value_store(name='webappanalyzer-fingerprints')
    key = 'database-' + COMMIT
    cached = await store.get_value(key)
    if valid_cache(cached):
        return cached, {'cacheHit': True, 'requests': 0, 'commit': COMMIT}
    data = {'commit': COMMIT, 'license': LICENSE, 'technologies': {}, 'sha256': {}}
    async with PublicClient('TechStackDetectorActor') as client:
        for path in FILES + ['LICENSE']:
            response = await client.get(BASE + path)
            data['sha256'][path] = hashlib.sha256(response.content).hexdigest()
            if path == 'LICENSE':
                data['licenseText'] = response.text
                continue
            try:
                parsed = response.json()
            except ValueError as exc:
                raise FetchError('fingerprint_download', 'Pinned fingerprint file is not JSON.') from exc
            if not isinstance(parsed, dict):
                raise FetchError('fingerprint_download', 'Invalid fingerprint database structure.')
            if path.startswith('src/technologies/'):
                data['technologies'].update(parsed)
            else:
                data[path.removeprefix('src/').removesuffix('.json')] = parsed
        if not valid_cache(data):
            raise FetchError('fingerprint_download', 'Incomplete fingerprint download; no partial cache saved.')
        await store.set_value(key, data)
        return data, {'cacheHit': False, 'requests': client.requests, 'commit': COMMIT, 'sha256': data['sha256']}
