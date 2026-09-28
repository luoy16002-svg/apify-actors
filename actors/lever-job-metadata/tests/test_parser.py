import asyncio
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from src.common import ResultSink, SchemaError
from src.main import collect, matches, normalize_input
from src.parser import parse_job, parse_page
from test_common import FakeActor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/live-page.json').read_text())
NOW = '2026-09-29T00:00:00Z'


def parse(raw, region='global'):
    return parse_job(raw, board='spotify', region=region, fetched_at=NOW)


def test_live_fixture_matches_output_contract():
    schema = json.loads((ROOT / '.actor/dataset_schema.json').read_text())['fields']
    for raw in FIXTURE:
        item = parse(raw)
        jsonschema.validate(item, schema, format_checker=jsonschema.FormatChecker())
        assert all(not isinstance(value, (dict, list)) for value in item.values())
        assert 'description' not in item and 'email' not in item and 'phone' not in item
    assert parse(FIXTURE[0])['title'] == 'Android Engineer - Experience'
    assert parse(FIXTURE[0])['allLocations'] == 'London; Stockholm'
    assert parse(FIXTURE[0])['workplaceType'] == 'hybrid'


def test_salary_types_remote_unknown_and_zero():
    raw = copy.deepcopy(FIXTURE[0])
    raw.update(salaryRange={'min': '0', 'max': '100000', 'currency': 'GBP', 'interval': 'per-year'},
               workplaceType='unspecified')
    item = parse(raw)
    assert item['salaryMin'] == 0.0 and item['salaryMax'] == 100000.0
    assert item['salaryCurrency'] == 'GBP' and item['isRemote'] is None
    raw['workplaceType'] = 'on-site'
    assert parse(raw)['workplaceType'] == 'onsite'
    assert parse(raw)['isRemote'] is False
    raw['workplaceType'] = 'remote'
    assert parse(raw)['isRemote'] is True


def test_absent_optional_values_never_invented():
    item = parse({'id': FIXTURE[0]['id'], 'text': 'Example', 'categories': None,
                  'createdAt': 1e30, 'salaryRange': [], 'workplaceType': 'unexpected'})
    assert item['isRemote'] is None and item['createdAt'] is None
    assert item['salaryMin'] is None and item['salaryMax'] is None
    assert item['allLocations'] is None and item['department'] is None


def test_contradictory_salary_is_null():
    raw = copy.deepcopy(FIXTURE[0])
    raw['salaryRange'] = {'min': 200000, 'max': 100000}
    assert parse(raw)['salaryMin'] is None and parse(raw)['salaryMax'] is None


def test_untrusted_source_urls_not_reused_and_eu_link():
    raw = copy.deepcopy(FIXTURE[0])
    raw['hostedUrl'] = 'javascript:alert(1)'
    item = parse(raw, region='eu')
    assert item['sourceUrl'].startswith('https://jobs.eu.lever.co/spotify/')
    assert item['applyUrl'] == item['sourceUrl'] + '/apply'


@pytest.mark.parametrize('raw', [{}, None, {'id': 'not-an-id', 'text': 'Example'}, {'id': FIXTURE[0]['id'], 'text': ''}])
def test_malformed_identity_fails(raw):
    with pytest.raises(SchemaError):
        parse(raw)


@pytest.mark.parametrize('value', [{}, {'jobs': []}, None])
def test_changed_envelope_fails(value):
    with pytest.raises(SchemaError):
        parse_page(value)


def test_literal_filters_and_unknown_remote():
    item = parse(FIXTURE[0])
    assert matches(item, normalize_input({'titleContains': 'ANDROID', 'locationContains': 'stockholm', 'workplaceType': 'hybrid'}))
    assert not matches(item, normalize_input({'titleContains': '.*'}))
    item['workplaceType'] = None
    assert not matches(item, normalize_input({'workplaceType': 'remote'}))


class Pages:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def get_json(self, path, params):
        self.calls.append((path, params))
        return self.pages[len(self.calls)-1]


def test_pagination_dedup_maxitems():
    a, b, c = FIXTURE
    client = Pages([[a, b], [b, c]])
    actor = FakeActor()
    stats = asyncio.run(collect(normalize_input({'maxItems': 3, 'pageSize': 2}), client, ResultSink(actor, 3)))
    assert stats['items'] == 3 and stats['duplicates'] == 1
    assert [call[1]['skip'] for call in client.calls] == [0, 2]


def test_filters_continue_until_output_limit_not_input_limit():
    a, b, c = copy.deepcopy(FIXTURE)
    a['text'] = 'No match'
    b['text'] = c['text'] = 'Wanted'
    client = Pages([[a, b], [c]])
    actor = FakeActor()
    stats = asyncio.run(collect(normalize_input({'maxItems': 2, 'pageSize': 2, 'titleContains': 'Wanted'}), client, ResultSink(actor, 2)))
    assert stats['items'] == 2 and stats['filtered'] == 1
    assert len(client.calls) == 2


def test_scan_cap_is_reported():
    client = Pages([FIXTURE[:2]])
    stats = asyncio.run(collect(normalize_input({'maxItems': 3, 'pageSize': 2, 'maxPages': 1, 'titleContains': 'absent'}), client, ResultSink(FakeActor(), 3)))
    assert stats['stopReason'] == 'page_limit' and stats['items'] == 0


def test_repeated_page_fails():
    client = Pages([FIXTURE[:2], FIXTURE[:2]])
    with pytest.raises(SchemaError, match='repeated'):
        asyncio.run(collect(normalize_input({'maxItems': 5, 'pageSize': 2}), client, ResultSink(FakeActor(), 5)))


def test_empty_and_all_malformed():
    config = normalize_input({})
    assert asyncio.run(collect(config, Pages([[]]), ResultSink(FakeActor(), 20)))['items'] == 0
    with pytest.raises(SchemaError, match='All jobs'):
        asyncio.run(collect(config, Pages([[{}]]), ResultSink(FakeActor(), 20)))


def test_budget_zero_does_not_fetch():
    client = Pages([])
    stats = asyncio.run(collect(normalize_input({}), client, ResultSink(FakeActor(budget=0), 20)))
    assert stats['items'] == 0 and client.calls == []


@pytest.mark.parametrize('data', [{'boards': []}, {'boards': ['https://jobs.lever.co/spotify']},
                                {'boards': ['../other']}, {'region': 'invalid'}, {'workplaceType': 'maybe'}])
def test_invalid_input(data):
    with pytest.raises(ValueError):
        normalize_input(data)


def test_runtime_defaults_and_board_dedup():
    schema = json.loads((ROOT / '.actor/input_schema.json').read_text())
    assert normalize_input({}) == {key: value['default'] for key, value in schema['properties'].items()}
    assert normalize_input({'boards': ['Spotify', 'spotify']})['boards'] == ['spotify']
