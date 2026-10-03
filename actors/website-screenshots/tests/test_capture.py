import asyncio
import io

import pytest
from PIL import Image

from src.browser import BrowserPool, ad_domain
from src.capture import context_options, encode_image, stable_key
from src.cmp import CMP_SELECTORS, HIDE_BANNERS
from src.main import normalize_input
from src.net import InputError


@pytest.mark.parametrize('bad', [{}, {'urls': []}, {'urls': ['file:///etc/passwd']},
    {'urls': ['example.org'], 'maxConcurrency': 4}, {'urls': ['example.org'], 'css': 10},
    {'urls': ['example.org'], 'javascript': 'alert(1)'}, {'urls': ['example.org'], 'waitStrategy': 'selector'},
    {'urls': ['example.org'], 'quality': True}, {'urls': ['example.org'], 'waitDelaySeconds': float('nan')}])
def test_bad_input(bad):
    with pytest.raises(InputError):
        normalize_input(bad)


def test_presets_and_deduplication():
    cfg = normalize_input({'urls': ['example.org', 'https://example.org/'], 'viewport': 'mobile'})
    assert len(cfg['urls']) == 1
    options = context_options(cfg)
    assert options['viewport'] == {'width': 390, 'height': 844}
    assert options['device_scale_factor'] == 3 and 'Mobile' in options['user_agent']
    assert options['is_mobile'] and options['has_touch']


def test_domain_blocklist_uses_label_boundary():
    assert ad_domain('www.google-analytics.com')
    assert not ad_domain('notgoogle-analytics.com')


def test_stable_key_and_webp_is_real_webp():
    cfg = normalize_input({'urls': ['example.org']})
    a = stable_key('https://example.org/', cfg)
    assert a == stable_key('https://example.org/', {**cfg, 'maxConcurrency': 3})
    assert a != stable_key('https://example.org/', {**cfg, 'format': 'webp'})
    stream = io.BytesIO()
    Image.new('RGB', (80, 40), 'red').save(stream, format='PNG')
    data, w, h = encode_image(stream.getvalue(), 'webp', 80)
    assert (w, h) == (80, 40) and data[8:12] == b'WEBP'


def test_browser_cmp_heuristics_mobile_scale_pdf_and_restart():
    async def run():
        async with BrowserPool() as pool:
            browser = await pool.get()
            context = await browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=3, is_mobile=True)
            page = await context.new_page()
            families = ['onetrust-banner-sdk', 'CybotCookiebotDialog', 'didomi-host', 'qc-cmp2-container',
                        'truste-consent-track', 'usercentrics-root', 'osano-cm-dialog', 'wt-cck--container']
            html = '<meta name="viewport" content="width=device-width"><main id="cookie-article">A cookie recipe</main>'
            html += ''.join(f'<div id="{name}" class="{name}" style="position:fixed;bottom:0">Cookies <button>Accept</button></div>' for name in families)
            html += '<div id="cookie-choice" style="position:fixed;bottom:0">Cookie preferences <button>Reject</button></div>'
            await page.set_content(html)
            assert await page.evaluate(HIDE_BANNERS, CMP_SELECTORS) == 9
            assert await page.locator('#cookie-article').is_visible()
            assert not await page.locator('#cookie-choice').is_visible()
            for name in families:
                assert not await page.locator('#' + name).is_visible()
            image = await page.screenshot()
            assert Image.open(io.BytesIO(image)).size == (1170, 2532)
            assert (await page.pdf(format='A4', print_background=True)).startswith(b'%PDF-')
            await context.close()
            await browser.close()
            assert (await pool.get()).is_connected() and pool.restarts == 1
    asyncio.run(run())
