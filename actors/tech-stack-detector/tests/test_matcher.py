import asyncio
import json
from pathlib import Path

import pytest
import regex

from src.browser import BrowserPool
from src.main import READ_GLOBALS, normalize_input
from src.matcher import Matcher, convenience, extract_version, signals
from src.net import InputError


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures/matcher.json').read_text(encoding='utf-8'))


def test_fixture_meta_versions_confidence_dedup_cookies_requires_implies():
    f = fixture()
    matcher = Matcher(f['technologies'], f['categories'])
    rows, diagnostic = matcher.detect(signals(f['html'], {}, {'_analytics': 'value'}, 'https://example.org'))
    by_name = {r['name']: r for r in rows}
    assert set(by_name) == {'SyntheticCMS', 'Plugin', 'Analytics', 'Runtime'}
    assert by_name['SyntheticCMS']['version'] == '2.4.1'
    assert by_name['Analytics']['confidence'] == 100 and by_name['Runtime']['confidence'] == 50
    assert by_name['Runtime']['evidence'] == ['implied:SyntheticCMS']
    rows, _ = matcher.detect(signals(f['html'], {}, {}, 'https://example.org'))
    assert next(t for t in rows if t['name'] == 'Analytics')['confidence'] == 50


def test_filter_applied_after_dependency_resolution():
    f = fixture()
    rows, _ = Matcher(f['technologies'], f['categories']).detect(signals(f['html'], {}, {}, 'https://example.org'), {'27'})
    assert [t['name'] for t in rows] == ['Runtime']
    assert convenience(rows)['programmingLanguages'] == ['Runtime']


@pytest.mark.parametrize('text,expected', [('v2.3', '2.3'), ('v', 'unknown')])
def test_version_ternary_and_backreferences(text, expected):
    match = regex.search(r'v([0-9.]+)?', text)
    assert extract_version(r'\1?\1:unknown', match) == expected


def test_headers_inline_scripts_url_js_and_regex_compatibility():
    tech = {
        'Header': {'headers': {'X-Powered-By': r'Acme/([0-9.]+)\;version:\1'}},
        'Inline': {'scripts': r'const app = "yes"'}, 'Url': {'url': r'example\.org'},
        'JS': {'js': {'Example.version': r'^(.+)$\;version:\1'}},
        'AnyCharacter': {'html': r'hello[^]*world'},
    }
    rows, _ = Matcher(tech, {}).detect(signals('<p>hello\nworld</p><script>const app = "yes";</script>',
                   {'x-powered-by': 'Acme/1.2'}, {}, 'https://example.org/', {'Example.version': '3.0'}))
    assert {r['name'] for r in rows} == set(tech)
    assert next(r for r in rows if r['name'] == 'Header')['version'] == '1.2'
    assert next(r for r in rows if r['name'] == 'JS')['version'] == '3.0'


def test_missing_prerequisite_and_cycles_are_not_detected():
    tech = {'A': {'html': 'yes', 'requires': ['B']}, 'B': {'html': 'yes', 'requires': ['A']}}
    rows, _ = Matcher(tech, {}).detect(signals('yes', {}, {}, 'https://example.org'))
    assert rows == []


def test_inline_script_matching_ignores_json_and_article_text():
    matcher = Matcher({'Example': {'scripts': 'productEnabled'}, 'TextOnly': {'text': 'productEnabled'}}, {})
    data = signals('<script type="application/json">{"productEnabled":true}</script><p>productEnabled</p>', {}, {}, 'https://example.org')
    assert matcher.detect(data)[0] == []


def test_exclusion_removes_gated_dependants_and_orphan_implied_cycles():
    tech = {'Root': {'html': 'root', 'implies': ['B']}, 'B': {'implies': ['C']}, 'C': {'implies': ['B']},
            'Plugin': {'html': 'plugin', 'requires': ['Root']}, 'Winner': {'html': 'winner', 'excludes': ['Root']}}
    rows, _ = Matcher(tech, {}).detect(signals('root plugin winner', {}, {}, 'https://example.org'))
    assert [r['name'] for r in rows] == ['Winner']


def test_two_implication_roots_survive_removal_of_one():
    tech = {'A': {'html': 'yes', 'implies': ['B']}, 'D': {'html': 'yes', 'implies': ['B'], 'excludes': ['A']}, 'B': {}}
    rows, _ = Matcher(tech, {}).detect(signals('yes', {}, {}, 'https://example.org'))
    assert {r['name'] for r in rows} == {'D', 'B'}


def test_requires_category_and_bad_regex_are_honest():
    tech = {'CMS': {'html': 'cms', 'cats': [1]}, 'Plugin': {'html': ['plugin', '['], 'requiresCategory': [1]}}
    matcher = Matcher(tech, {'1': {'name': 'CMS'}})
    rows, result = matcher.detect(signals('plugin', {}, {}, 'https://example.org'))
    assert not rows and result['unsupportedPatterns'] == 1
    assert len(matcher.detect(signals('cms plugin', {}, {}, 'https://example.org'))[0]) == 2


@pytest.mark.parametrize('data', [{}, {'urls': []}, {'urls': ['127.0.0.1']}, {'urls': ['example.org'], 'renderJs': 'yes'},
                                {'urls': ['example.org'], 'maxConcurrency': True}, {'urls': ['example.org'], 'includeCategories': [1]}])
def test_input_errors(data):
    with pytest.raises(InputError):
        normalize_input(data)


def test_global_paths_read_without_eval_or_getter_execution():
    async def run():
        async with BrowserPool() as pool:
            browser = await pool.get()
            page = await browser.new_page()
            try:
                await page.set_content('<script>window.Example={version:"4.2"};window.getterCalled=false;Object.defineProperty(window,"Trap",{get(){window.getterCalled=true;return "bad"}});</script>')
                result = await page.evaluate(READ_GLOBALS, ['Example', 'Example.version', 'window.Example.version', 'Trap', 'alert(1)', '__proto__.x'])
                assert result == {'Example': '', 'Example.version': '4.2', 'window.Example.version': '4.2'}
                assert await page.evaluate('() => window.getterCalled') is False
            finally:
                await page.close()
    asyncio.run(run())
