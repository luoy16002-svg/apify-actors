import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.common import ResultSink
from src.main import collect, matches, normalize_input
from src.net import FetchError, InputError
from src.parser import parse_job, plain
from src.providers import parse_xml
from src.targets import Board, company_input, detect, from_url


class FakeActor:
    def __init__(self, limit=999):
        self.rows, self.limit = [], limit
    def get_charging_manager(self):
        return self
    def is_event_charge_limit_reached(self, event):
        return len(self.rows) >= self.limit
    async def push_data(self, row):
        self.rows.append(row)
        return SimpleNamespace(event_charge_limit_reached=False, charged_count=0)


@pytest.mark.parametrize('url,ats,slug,region', [
    ('https://boards.greenhouse.io/acme', 'greenhouse', 'acme', 'global'),
    ('https://job-boards.greenhouse.io/acme/jobs/123', 'greenhouse', 'acme', 'global'),
    ('https://boards.greenhouse.io/embed/job_board?for=acme', 'greenhouse', 'acme', 'global'),
    ('jobs.ashbyhq.com/Acme', 'ashby', 'Acme', 'global'),
    ('https://apply.workable.com/acme/', 'workable', 'acme', 'global'),
    ('https://jobs.smartrecruiters.com/Acme/123', 'smartrecruiters', 'Acme', 'global'),
    ('https://acme.recruitee.com/o/example', 'recruitee', 'acme', 'global'),
    ('https://acme.jobs.personio.com/job/1', 'personio', 'acme', 'com'),
    ('https://jobs.eu.lever.co/acme/123', 'lever', 'acme', 'eu'),
])
def test_board_urls(url, ats, slug, region):
    assert from_url(url) == Board(ats, slug, region)


def test_detection_links_iframes_and_script_urls_are_bounded_to_known_hosts():
    assert detect('<iframe src="//boards.greenhouse.io/embed/job_board?for=acme"></iframe>') == [Board('greenhouse', 'acme')]
    assert detect('<script>var url="https:\\/\\/jobs.ashbyhq.com/Acme"</script>') == [Board('ashby', 'Acme')]
    assert detect('<a href="https://jobs.lever.co.attacker.example/acme">x</a>') == []


def test_personio_host_aliases_dedupe_but_lever_regions_do_not():
    assert Board('personio', 'acme').identity == Board('personio', 'acme', 'de').identity == Board('personio', 'acme', 'com').identity
    assert Board('lever', 'acme').identity != Board('lever', 'acme', 'eu').identity
    with pytest.raises(InputError):
        company_input({'ats': 'greenhouse', 'slug': 'acme', 'region': 'eu'})


@pytest.mark.parametrize('bad', [{}, [], {'companies': []}, {'companies': [5]}, {'companies': [{'slug': '../a'}]},
                                 {'companies': ['x'], 'remoteOnly': 'false'}, {'companies': ['x'], 'maxItems': True},
                                 {'companies': ['x'], 'postedAfter': 'tomorrow'}, {'companies': ['x'], 'requestDelaySeconds': float('nan')}])
def test_typed_input_errors(bad):
    with pytest.raises(InputError):
        normalize_input(bad)


def test_plain_paragraphs_and_conservative_contact_removal():
    body = plain('&lt;p&gt;ID 123456789 and salary 1234567&lt;/p&gt;&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt; test@example.org +44 1234 567890&lt;/p&gt;')
    assert '123456789' in body and '1234567' in body and '\n\n' in body
    assert 'Hello world' in body and 'example.org' not in body and '+44' not in body


@pytest.mark.parametrize('file', ['greenhouse', 'workable', 'recruitee', 'personio', 'lever'])
def test_real_source_fixture(file):
    raw = json.loads((Path(__file__).parent / 'fixtures' / (file + '.json')).read_text(encoding='utf-8'))
    job = parse_job(raw, Board(file, 'fixture'))
    assert job['title'] and job['sourceUrl'].startswith('https://') and job['sourceId']
    if file == 'workable':
        assert job['city'] == 'Miami' and job['countryCode'] == 'US' and job['isRemote'] is False


def test_ashby_structured_salary_not_equity_or_free_text():
    raw = {'title': 'Engineer', 'jobUrl': 'https://jobs.ashbyhq.com/acme/123', 'isRemote': False,
           'location': 'Remote', 'compensation': {'summaryComponents': [
               {'compensationType': 'EquityPercentage', 'minValue': 1, 'maxValue': 2},
               {'compensationType': 'Salary', 'minValue': 100000, 'maxValue': 150000, 'currencyCode': 'USD', 'interval': '1 YEAR'}]}}
    row = parse_job(raw, Board('ashby', 'acme'))
    assert row['salaryMin'] == 100000 and row['salaryInterval'] == '1 YEAR'
    assert row['isRemote'] is False
    raw['compensation']['summaryComponents'].append({'compensationType': 'Salary', 'currencyCode': 'EUR'})
    assert parse_job(raw, Board('ashby', 'acme'))['salaryMin'] is None


def test_smartrecruiters_details_normalize_without_contact_fields():
    raw = {'id': '123', 'name': 'Engineer', 'company': {'name': 'Example'},
           'location': {'city': 'Paris', 'country': 'FR', 'remote': False},
           'typeOfEmployment': {'label': 'Full-time'}, 'department': {'label': 'Engineering'},
           'releasedDate': '2026-01-01T00:00:00Z',
           'jobAd': {'sections': {'jobDescription': {'title': 'Role', 'text': '<p>Build software.</p><p>email person@example.org</p>'}}}}
    row = parse_job(raw, Board('smartrecruiters', 'Example'))
    assert row['company'] == 'Example' and row['countryCode'] == 'FR'
    assert row['employmentType'] == 'Full-time' and row['isRemote'] is False
    assert 'Build software.' in row['description'] and 'person@example.org' not in row['description']


def test_greenhouse_structured_salary_only_and_not_mutating_fixture():
    raw = {'id': 1, 'title': 'Job', 'absolute_url': 'https://example.org/job',
           'content': '<p>Salary $100 - $200</p>',
           'metadata': [{'value_type': 'currency_range', 'value': {'min_value': 100, 'max_value': 200, 'unit': 'CAD'}}]}
    job = parse_job(raw, Board('greenhouse', 'acme'))
    assert job['salaryMin'] == 100 and job['salaryCurrency'] == 'CAD'
    del raw['metadata']
    assert parse_job(raw, Board('greenhouse', 'acme'))['salaryMin'] is None


@pytest.mark.parametrize('location,expected', [('Remote - Europe', True), ('Not remote', None), ('Hybrid / Remote', None), ('Remoteville', None)])
def test_no_remote_guess_from_ambiguous_location(location, expected):
    row = parse_job({'id': 1, 'title': 'Job', 'location': {'name': location}, 'absolute_url': 'https://example.org/job'}, Board('greenhouse', 'acme'))
    assert row['isRemote'] is expected


def test_filters_exclude_unknown_dates_and_remote():
    cfg = normalize_input({'companies': ['acme'], 'postedAfter': '2026-01-01', 'remoteOnly': True})
    job = {'title': 'Engineer', 'allLocations': 'Paris', 'department': None, 'createdAt': None, 'isRemote': True}
    assert not matches(job, cfg)
    job['createdAt'] = '2026-02-01'
    assert matches(job, cfg)
    job['isRemote'] = None
    assert not matches(job, cfg)


def test_xml_rejects_entities():
    with pytest.raises(Exception, match='Invalid or unsafe'):
        parse_xml(b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><workzag-jobs>&y;</workzag-jobs>')


def test_pagination_duplicates_failures_and_filter_before_billing(monkeypatch):
    def raw(i):
        return {'id': str(i), 'text': f'Job {i}', 'hostedUrl': f'https://jobs.lever.co/acme/{i}'}
    calls = []
    async def pages(client, board, offset=0, page_size=100):
        calls.append((board.slug, offset))
        if board.slug == 'bad':
            raise FetchError('http_error', '404', 404)
        return ({0: [raw(1), raw(2)], 2: [raw(2), raw(3)], 4: []}[offset], None)
    monkeypatch.setattr('src.main.page', pages)
    actor = FakeActor()
    cfg = normalize_input({'companies': [{'slug': 'bad', 'ats': 'lever'}, {'slug': 'acme', 'ats': 'lever'},
                                         'https://jobs.lever.co/acme'], 'pageSize': 2, 'titleContains': '3'})
    out = asyncio.run(collect(cfg, None, ResultSink(actor, 100)))
    assert len(actor.rows) == 1 and actor.rows[0]['jobId'] == '3'
    assert out[0]['error']['code'] == 'http_error' and out[1]['duplicates'] == 1
    assert out[2]['stopReason'] == 'duplicate_company'


def test_repeated_page_never_silently_complete(monkeypatch):
    async def pages(*args, **kwargs):
        return ([{'id': '1', 'text': 'Job', 'hostedUrl': 'https://jobs.lever.co/acme/1'}], None)
    monkeypatch.setattr('src.main.page', pages)
    cfg = normalize_input({'companies': [{'slug': 'acme', 'ats': 'lever'}], 'pageSize': 1})
    actor = FakeActor()
    out = asyncio.run(collect(cfg, None, ResultSink(actor, 100)))
    assert len(actor.rows) == 1 and out[0]['error']['code'] == 'repeated_page' and not out[0]['complete']
