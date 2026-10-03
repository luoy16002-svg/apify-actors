from urllib.parse import quote

from defusedxml import ElementTree as ET

from .common import SchemaError
from .net import FetchError


def endpoint(board, offset=0, page_size=100):
    s = quote(board.slug, safe='')
    if board.ats == 'greenhouse':
        return f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=true'
    if board.ats == 'ashby':
        return f'https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true'
    if board.ats == 'workable':
        return f'https://apply.workable.com/api/v1/widget/accounts/{s}?details=true'
    if board.ats == 'smartrecruiters':
        return f'https://api.smartrecruiters.com/v1/companies/{s}/postings?limit={page_size}&offset={offset}'
    if board.ats == 'recruitee':
        return f'https://{s}.recruitee.com/api/offers/'
    if board.ats == 'personio':
        return board.careers + 'xml'
    host = 'api.eu.lever.co' if board.region == 'eu' else 'api.lever.co'
    return f'https://{host}/v0/postings/{s}?mode=json&limit={page_size}&skip={offset}'


def parse_xml(body):
    try:
        root = ET.fromstring(body)
    except Exception as exc:
        raise SchemaError('Invalid or unsafe Personio XML feed.') from exc
    if root.tag != 'workzag-jobs':
        raise SchemaError('Expected Personio workzag-jobs XML root.')
    rows = []
    for node in root.findall('position'):
        row = {child.tag: child.text for child in node if child.tag != 'jobDescriptions'}
        row['description'] = '\n'.join((entry.findtext('name') or '') + '\n' +
                                      (entry.findtext('value') or '') for entry in node.findall('jobDescriptions/jobDescription'))
        rows.append(row)
    return rows


async def page(client, board, offset=0, page_size=100):
    url = endpoint(board, offset, page_size)
    if board.ats == 'personio':
        rows = parse_xml((await client.get(url)).content)
        return rows, len(rows)
    payload = await client.json(url)
    key = {'greenhouse': 'jobs', 'ashby': 'jobs', 'workable': 'jobs',
           'smartrecruiters': 'content', 'recruitee': 'offers'}.get(board.ats)
    rows = payload.get(key) if key and isinstance(payload, dict) else payload if key is None else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SchemaError(f'{board.ats} public API response shape changed.')
    if board.ats == 'smartrecruiters':
        total = payload.get('totalFound')
        try:
            total = int(total)
        except (TypeError, ValueError) as exc:
            raise SchemaError('SmartRecruiters totalFound missing.') from exc
        if total < 0:
            raise SchemaError('Negative totalFound.')
    elif board.ats == 'lever':
        total = None
    else:
        total = len(rows)
    return rows, total


async def detail(client, board, raw):
    if board.ats != 'smartrecruiters':
        return raw
    job_id = str(raw.get('id', ''))
    if not job_id or not job_id.replace('-', '').isalnum():
        raise SchemaError('Invalid SmartRecruiters posting id.')
    url = f'https://api.smartrecruiters.com/v1/companies/{quote(board.slug, safe="")}/postings/{quote(job_id, safe="")}'
    result = await client.json(url)
    if not isinstance(result, dict) or str(result.get('id')) != job_id:
        raise SchemaError('SmartRecruiters details do not match listing.')
    return result
