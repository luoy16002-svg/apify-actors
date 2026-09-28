import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import jsonschema
import pytest

from src.common import PoliteClient, ResultSink, SchemaError, SourceError, common_input


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    async def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


class FakeActor:
    def __init__(self, budget=None):
        self.rows = []
        self.budget = budget

    def get_charging_manager(self):
        return self

    def is_event_charge_limit_reached(self, event):
        assert event == 'apify-default-dataset-item'
        return self.budget is not None and len(self.rows) >= self.budget

    async def push_data(self, row):
        self.rows.append(row)
        return SimpleNamespace(event_charge_limit_reached=self.is_event_charge_limit_reached('apify-default-dataset-item'),
                               charged_count=1 if self.budget is not None else 0)


def client_for(handler):
    clock = Clock()
    client = PoliteClient('https://source.example', '/records', delay=1.2,
                          transport=httpx.MockTransport(handler), sleep=clock.sleep,
                          monotonic=lambda: clock.now)
    return client, clock


def test_robots_delay_and_429_retry_after():
    paths = []
    attempts = 0
    def handler(request):
        nonlocal attempts
        paths.append(request.url.path)
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nAllow: /records\nCrawl-delay: 3\n')
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={'Retry-After': '5'})
        return httpx.Response(200, json={'ok': True})
    client, clock = client_for(handler)
    async def run():
        async with client:
            assert await client.get_json('/records') == {'ok': True}
            assert await client.get_json('/records') == {'ok': True}
    asyncio.run(run())
    assert paths.count('/robots.txt') == 1
    assert clock.sleeps == [3.0, 5.0, 3.0]
    assert client.retry_count == 1


@pytest.mark.parametrize('status,body', [
    (200, 'User-agent: *\nDisallow: /records'), (401, 'unauthorized'),
    (403, 'forbidden'), (302, ''), (200, '<!doctype html><html>wrong page</html>'),
])
def test_robots_fail_closed(status, body):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(status, text=body)
    client, _ = client_for(handler)
    async def run():
        async with client:
            with pytest.raises(SourceError):
                await client.get_json('/records')
    asyncio.run(run())
    assert paths == ['/robots.txt']


def test_robots_wildcards_allow_precedence_and_query():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nDisallow: /records*\nAllow: /records/public$')
        return httpx.Response(200, json=[])
    client, _ = client_for(handler)
    async def run():
        async with client:
            assert await client.get_json('/records/public') == []
            with pytest.raises(SourceError):
                await client.get_json('/records/public', {'secret': '1'})
    asyncio.run(run())
    assert paths == ['/robots.txt', '/records/public']


@pytest.mark.parametrize('status', [401, 403, 404, 302])
def test_permanent_http_errors_not_retried(status):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(404 if request.url.path == '/robots.txt' else status)
    client, _ = client_for(handler)
    async def run():
        async with client:
            with pytest.raises(SourceError):
                await client.get_json('/records')
    asyncio.run(run())
    assert paths == ['/robots.txt', '/records']


def test_transient_failures_bounded():
    def handler(request):
        return httpx.Response(404 if request.url.path == '/robots.txt' else 503)
    client, clock = client_for(handler)
    async def run():
        async with client:
            with pytest.raises(SourceError, match='4 attempts'):
                await client.get_json('/records')
    asyncio.run(run())
    assert client.request_count == 5
    assert client.retry_count == 3
    assert sum(clock.sleeps) >= 7


def test_network_errors_are_retried():
    attempts = 0
    def handler(request):
        nonlocal attempts
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout('test timeout', request=request)
        return httpx.Response(200, json=[])
    client, _ = client_for(handler)
    async def run():
        async with client:
            assert await client.get_json('/records') == []
    asyncio.run(run())
    assert attempts == 2


def test_long_retry_after_stops_without_early_retry():
    client, clock = client_for(lambda request: httpx.Response(404) if request.url.path == '/robots.txt'
                               else httpx.Response(429, headers={'Retry-After': '120'}))
    async def run():
        async with client:
            with pytest.raises(SourceError, match='long Retry-After'):
                await client.get_json('/records')
    asyncio.run(run())
    assert client.request_count == 2


def test_wrong_response_shape_fails():
    client, _ = client_for(lambda request: httpx.Response(404) if request.url.path == '/robots.txt'
                           else httpx.Response(200, text='<html>changed</html>'))
    async def run():
        async with client:
            with pytest.raises(SchemaError):
                await client.get_json('/records')
    asyncio.run(run())


@pytest.mark.parametrize('path', ['https://example.org/records', '//example.org/records', '/private', '/records/../private', '/records/%2e'])
def test_only_configured_api_paths(path):
    def handler(request):
        pytest.fail('Invalid paths must not make a network request.')
    client, _ = client_for(handler)
    async def run():
        async with client:
            with pytest.raises(ValueError):
                await client.get_json(path)
    asyncio.run(run())


def test_output_dedup_limit_and_no_double_billing():
    actor = FakeActor()
    sink = ResultSink(actor, 2)
    async def run():
        assert await sink.emit({'id': 'a'}, 'a')
        assert not await sink.emit({'id': 'a'}, 'a')
        assert await sink.emit({'id': 'b'}, 'b')
        assert not await sink.emit({'id': 'c'}, 'c')
    asyncio.run(run())
    assert actor.rows == [{'id': 'a'}, {'id': 'b'}]
    assert sink.count == 2 and sink.duplicates == 1 and sink.full


@pytest.mark.parametrize('budget', [0, 1, 2])
def test_paid_budget_never_exceeded(budget):
    actor = FakeActor(budget=budget)
    sink = ResultSink(actor, 10)
    async def run():
        for i in range(3):
            await sink.emit({'id': i}, str(i))
    asyncio.run(run())
    assert len(actor.rows) == sink.count == budget


@pytest.mark.parametrize('data', [[], {'maxItems': True}, {'maxItems': 0}, {'pageSize': 101},
                                {'maxPages': 0}, {'requestDelaySeconds': float('nan')},
                                {'requestDelaySeconds': .5}, {'proxyConfiguration': []}])
def test_invalid_common_input(data):
    with pytest.raises(ValueError):
        common_input(data)


def test_metadata_and_default_input():
    root = Path(__file__).resolve().parents[1]
    actor = json.loads((root / '.actor/actor.json').read_text())
    for key in ['input', 'output', 'readme', 'dockerfile']:
        assert (root / '.actor' / actor[key]).resolve().is_file()
    assert (root / '.actor' / actor['dockerContextDir']).resolve() == root
    schema = json.loads((root / '.actor/input_schema.json').read_text())
    jsonschema.Draft7Validator.check_schema(schema)
    defaults = {key: value['default'] for key, value in schema['properties'].items()}
    jsonschema.validate(defaults, schema)
    assert defaults['proxyConfiguration']['useApifyProxy'] is False
    dataset = json.loads((root / '.actor/dataset_schema.json').read_text())
    jsonschema.Draft7Validator.check_schema(dataset['fields'])
    for view in dataset['views'].values():
        assert set(view['transformation']['fields']) <= dataset['fields']['properties'].keys()
