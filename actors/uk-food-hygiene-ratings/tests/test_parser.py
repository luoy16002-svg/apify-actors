import asyncio
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from src.common import ResultSink, SchemaError
from src.main import collect, normalize_input
from src.parser import parse_establishment, parse_page
from test_common import FakeActor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/live-page.json').read_text())
NOW = '2026-09-29T00:00:00Z'


def parse(raw):
    return parse_establishment(raw, fetched_at=NOW, extract_date=FIXTURE['meta']['extractDate'])


def test_live_fixture_matches_output_contract():
    schema = json.loads((ROOT / '.actor/dataset_schema.json').read_text())['fields']
    for raw in FIXTURE['establishments']:
        item = parse(raw)
        jsonschema.validate(item, schema, format_checker=jsonschema.FormatChecker())
        assert all(not isinstance(value, (dict, list)) for value in item.values())
        assert 'Phone' not in item and 'email' not in item
    item = parse(FIXTURE['establishments'][0])
    assert item['fhrsId'] == '902473'
    assert item['rating'] == '4'
    assert item['latitude'] is None
    assert item['ratingDate'] == '2026-03-24'


def test_missing_optional_fields_and_text_ratings():
    item = parse({'FHRSID': 1, 'BusinessName': 'Example', 'RatingValue': 'Pass', 'scores': {'Hygiene': 0},
                  'SchemeType': 'FHIS', 'NewRatingPending': 'false'})
    assert item['rating'] == 'Pass' and item['schemeType'] == 'FHIS'
    assert item['hygieneScore'] == 0 and item['managementScore'] is None
    assert item['newRatingPending'] is False and item['ratingDate'] is None


def test_bad_optional_types_are_null():
    item = parse({'FHRSID': 1, 'BusinessName': 'Example', 'RatingValue': 0,
                  'geocode': {'latitude': 'NaN', 'longitude': '999'},
                  'scores': [], 'RatingDate': 'not a date', 'NewRatingPending': 'maybe'})
    assert item['rating'] == '0'
    for key in ['latitude', 'longitude', 'ratingDate', 'newRatingPending', 'hygieneScore']:
        assert item[key] is None


@pytest.mark.parametrize('raw', [{}, {'FHRSID': -1, 'BusinessName': 'x'}, {'FHRSID': 1, 'BusinessName': None}, None])
def test_identity_change_is_detected(raw):
    with pytest.raises(SchemaError):
        parse(raw)


@pytest.mark.parametrize('payload', [[], {}, {'establishments': []}, {'establishments': [], 'meta': {'returncode': 'ERROR'}}])
def test_changed_envelope_fails(payload):
    with pytest.raises(SchemaError):
        parse_page(payload)


class Pages:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def get_json(self, path, params):
        self.calls.append(params)
        return {'establishments': self.rows[len(self.calls)-1],
                'meta': {'pageNumber': params['pageNumber'], 'totalPages': len(self.rows), 'returncode': 'OK'}}


def test_paging_uses_fixed_size_and_deduplicates():
    a, b, c = FIXTURE['establishments']
    client = Pages([[a, b], [b, c]])
    actor = FakeActor()
    sink = ResultSink(actor, 3)
    stats = asyncio.run(collect(normalize_input({'maxItems': 3, 'pageSize': 2}), client, sink))
    assert len(actor.rows) == 3 and stats['duplicates'] == 1
    assert [call['pageNumber'] for call in client.calls] == [1, 2]
    assert [call['pageSize'] for call in client.calls] == [2, 2]


def test_repeated_page_fails():
    a, b, _ = FIXTURE['establishments']
    client = Pages([[a, b], [a, b]])
    with pytest.raises(SchemaError, match='repeated'):
        asyncio.run(collect(normalize_input({'maxItems': 5, 'pageSize': 2}), client, ResultSink(FakeActor(), 5)))


def test_empty_is_success_and_all_malformed_fails():
    config = normalize_input({})
    assert asyncio.run(collect(config, Pages([[]]), ResultSink(FakeActor(), 20)))['items'] == 0
    with pytest.raises(SchemaError, match='All establishments'):
        asyncio.run(collect(config, Pages([[{}]]), ResultSink(FakeActor(), 20)))


def test_no_request_when_budget_zero():
    client = Pages([])
    stats = asyncio.run(collect(normalize_input({}), client, ResultSink(FakeActor(budget=0), 20)))
    assert client.calls == [] and stats['stopReason'] == 'item_or_budget_limit'


def test_runtime_defaults_match_schema():
    schema = json.loads((ROOT / '.actor/input_schema.json').read_text())
    # name and address have no schema default, so a cleared form field means 'any'.
    assert normalize_input({}) == {key: value.get('default', '') for key, value in schema['properties'].items()}
