import asyncio
import httpx
import pytest
from src.common import SourceError
from src.helpers import PublicClient, InputError, public_url, date_range, in_range, plain_text
from test_common import Clock

@pytest.mark.parametrize('url',['file:///etc/passwd','http://localhost/x','http://127.0.0.1/x','http://169.254.169.254/','http://user:pass@example.com/','https://example.com:22/','https://x.internal/'])
def test_invalid_feed_urls(url):
    with pytest.raises(InputError):public_url(url)

def test_redirect_checks_destination_robots_and_paces():
    clock=Clock();paths=[]
    def handler(request):
        paths.append(str(request.url))
        if request.url.path=='/robots.txt':return httpx.Response(200,text='User-agent: *\nDisallow: /blocked')
        return httpx.Response(302,headers={'Location':'https://other.example/blocked'})
    async def run():
        async with PublicClient(transport=httpx.MockTransport(handler),sleep=clock.sleep,monotonic=lambda:clock.now) as client:
            with pytest.raises(SourceError,match='disallows'):await client.request('https://source.example/feed')
    asyncio.run(run())
    assert paths==['https://source.example/robots.txt','https://source.example/feed','https://other.example/robots.txt']
    assert sum(clock.sleeps)>=2.4

def test_post_keeps_json_and_never_forwards_credentials_on_redirect():
    clock=Clock();requests=[]
    def handler(request):
        requests.append(request)
        if request.url.path=='/robots.txt':return httpx.Response(404)
        return httpx.Response(302,headers={'Location':'https://other.example/search'})
    async def run():
        async with PublicClient(transport=httpx.MockTransport(handler),sleep=clock.sleep,monotonic=lambda:clock.now) as client:
            with pytest.raises(SourceError,match='redirect'):
                await client.get_json('https://source.example/search',method='POST',json_body={'q':'test'},headers={'Authorization':'test secret'})
    asyncio.run(run())
    assert len(requests)==2 and requests[-1].method=='POST' and requests[-1].content==b'{"q":"test"}'
    assert 'authorization' not in requests[0].headers

def test_dates_timezone_and_end_of_day():
    start,end=date_range({'from':'2026-10-01','to':'2026-10-01'},'from','to')
    assert in_range('2026-10-01T23:59:59Z',start,end)
    assert not in_range('2026-10-02T00:00:00Z',start,end)
    assert not in_range(None,start,end)
    with pytest.raises(InputError):date_range({'from':'2026-02-30'},'from','to')

def test_html_stripped_and_contacts_removed():
    assert plain_text('<p>Hello <b>world</b></p><script>ignore()</script>')=='Hello world'
    assert 'example.org' not in plain_text('<p>person@example.org</p>')

@pytest.mark.parametrize('value',['020 1234 5678','0612345678','+44 20 1234 5678','06 12 34 56 78','202-555-0101'])
def test_contact_like_phone_text_is_removed(value):
    from src.helpers import redact
    assert redact('Call '+value)=='Call [redacted phone]'

def test_dates_are_preserved_in_text():
    from src.helpers import redact
    assert redact('Published 2026-10-01')=='Published 2026-10-01'
