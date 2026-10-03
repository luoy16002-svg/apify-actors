"""Normalize published business postings; never guess salary currency or country."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .common import SchemaError, number, text, utc_now


def plain(value):
    if not isinstance(value, str) or not value:
        return None
    # Greenhouse can encode its entire HTML fragment, sometimes twice.
    for _ in range(2):
        if '&lt;' in value and '<p' not in value:
            value = html.unescape(value)
    soup = BeautifulSoup(value, 'html.parser')
    for node in soup(['script', 'style']):
        node.decompose()
    for node in soup.find_all(['p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'section']):
        node.insert_before('\n')
        node.insert_after('\n')
    value = soup.get_text(' ', strip=False)
    value = '\n\n'.join(' '.join(line.split()) for line in value.splitlines() if line.strip())
    # Contact data is unnecessary for these outputs. Never redact bare numeric IDs or amounts.
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email removed]', value)
    value = re.sub(r'(?<!\w)\+\d[\d ().-]{6,}\d', '[phone removed]', value)
    value = re.sub(r'(?i)\b(phone|telephone|tel|call|telefon)\s*[:.]?\s*\d[\d ().-]{6,}\d',
                   r'\1 [phone removed]', value)
    return value.strip() or None


def date(value, milliseconds=False):
    try:
        if milliseconds and number(value) is not None:
            return datetime.fromtimestamp(float(value) / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')
        if not isinstance(value, str) or not value:
            return None
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # A date without timezone is preserved as a date, not assigned a fictional timezone.
        return dt.isoformat().replace('+00:00', 'Z') if dt.tzinfo else dt.date().isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def obj(value):
    return value if isinstance(value, dict) else {}


def label(value):
    return text(value.get('label') or value.get('name')) if isinstance(value, dict) else text(value)


def salary(row, minimum, maximum, currency, interval):
    low, high = number(minimum), number(maximum)
    low = low if low is not None and low >= 0 else None
    high = high if high is not None and high >= 0 else None
    if low is not None and high is not None and low > high:
        low = high = None
    row.update(salaryMin=low, salaryMax=high, salaryCurrency=text(currency), salaryInterval=text(interval))


def parse_job(raw, board, company=None):
    if not isinstance(raw, dict):
        raise SchemaError('Job is not an object.')
    ats, slug = board.ats, board.slug
    row = dict.fromkeys(['company', 'jobId', 'title', 'department', 'team', 'location', 'allLocations',
                         'city', 'country', 'countryCode', 'isRemote', 'workplaceType', 'employmentType',
                         'createdAt', 'updatedAt', 'sourceUrl', 'applyUrl', 'description', 'salaryMin',
                         'salaryMax', 'salaryCurrency', 'salaryInterval'])
    row.update(ats=ats, board=slug, region=board.region, company=company or slug, fetchedAt=utc_now())
    explicit_remote = None
    if ats == 'greenhouse':
        row.update(jobId=raw.get('id'), title=raw.get('title'), location=label(raw.get('location')),
                   department='; '.join(filter(None, (label(x) for x in raw.get('departments', [])))) or None,
                   sourceUrl=raw.get('absolute_url'), applyUrl=raw.get('absolute_url'),
                   description=plain(raw.get('content')), updatedAt=date(raw.get('updated_at')),
                   createdAt=date(raw.get('first_published')))
        # Only explicit structured ranges; no regex extraction from free-text salary prose.
        ranges = list(raw.get('pay_input_ranges') or [])
        for metadata in raw.get('metadata') or []:
            val = obj(metadata.get('value'))
            if metadata.get('value_type') == 'currency_range' and val:
                ranges.append(val)
        if len(ranges) == 1:
            s = ranges[0]
            salary(row, s.get('min', s.get('min_value', number(s.get('min_cents')) / 100 if number(s.get('min_cents')) is not None else None)),
                   s.get('max', s.get('max_value', number(s.get('max_cents')) / 100 if number(s.get('max_cents')) is not None else None)),
                   s.get('currency_type') or s.get('currency') or s.get('unit'), s.get('period') or s.get('interval'))
    elif ats == 'ashby':
        addr = obj(obj(raw.get('address')).get('postalAddress'))
        row.update(jobId=raw.get('id') or urlsplit(raw.get('jobUrl', '')).path.rstrip('/').split('/')[-1],
                   title=raw.get('title'), location=raw.get('location'), department=raw.get('department'),
                   team=raw.get('team'), city=addr.get('addressLocality'), country=addr.get('addressCountry'),
                   employmentType=raw.get('employmentType'), createdAt=date(raw.get('publishedAt')),
                   sourceUrl=raw.get('jobUrl'), applyUrl=raw.get('applyUrl'),
                   description=plain(raw.get('descriptionHtml') or raw.get('descriptionPlain')),
                   workplaceType=raw.get('workplaceType'))
        explicit_remote = raw.get('isRemote')
        row['allLocations'] = '; '.join(dict.fromkeys(filter(None, [text(row['location'])] +
                                      [text(x.get('location')) for x in raw.get('secondaryLocations', [])]))) or None
        components = obj(raw.get('compensation')).get('summaryComponents') or []
        components = [x for x in components if x.get('compensationType') == 'Salary']
        if len(components) == 1:
            s = components[0]
            salary(row, s.get('minValue'), s.get('maxValue'), s.get('currencyCode'), s.get('interval'))
    elif ats == 'workable':
        locations = [x for x in raw.get('locations', []) if isinstance(x, dict) and not x.get('hidden')]
        loc = obj(raw.get('location')) or (locations[0] if locations else {})
        city, country = raw.get('city') or loc.get('city'), raw.get('country') or loc.get('country')
        region = raw.get('state') or loc.get('region')
        row.update(jobId=raw.get('shortcode') or raw.get('id'), title=raw.get('title'),
                   department=raw.get('department'), city=city, country=country,
                   countryCode=loc.get('country_code') or loc.get('countryCode'), location=', '.join(filter(None,
                   [text(city), text(region), text(country)])) or None,
                   sourceUrl=raw.get('url') or raw.get('shortlink'), applyUrl=raw.get('application_url'),
                   createdAt=date(raw.get('published_on') or raw.get('created_at')),
                   employmentType=raw.get('employment_type'), workplaceType=raw.get('workplace_type'),
                   description=plain('\n'.join(x for x in [raw.get('description'), raw.get('requirements'),
                                                          raw.get('benefits')] if isinstance(x, str))))
        row['allLocations'] = '; '.join(dict.fromkeys(', '.join(filter(None, [text(x.get(k)) for k in ['city', 'region', 'country']])) for x in locations)) or None
        explicit_remote = raw.get('telecommuting', loc.get('telecommuting', raw.get('remote')))
        s = obj(raw.get('salary'))
        salary(row, s.get('salary_from'), s.get('salary_to'), s.get('salary_currency'), s.get('period'))
    elif ats == 'smartrecruiters':
        loc = obj(raw.get('location'))
        sections = obj(obj(raw.get('jobAd')).get('sections'))
        desc = []
        for key in ['companyDescription', 'jobDescription', 'qualifications', 'additionalInformation']:
            s = obj(sections.get(key))
            if s.get('text'):
                desc += [s.get('title') or key, s['text']]
        row.update(jobId=raw.get('id'), title=raw.get('name'), company=company or label(raw.get('company')) or slug,
                   department=label(raw.get('department')), employmentType=label(raw.get('typeOfEmployment')),
                   location=', '.join(filter(None, [text(loc.get(k)) for k in ['city', 'region', 'country']])) or None,
                   city=loc.get('city'), countryCode=loc.get('country'), createdAt=date(raw.get('releasedDate')),
                   sourceUrl=raw.get('postingUrl'), applyUrl=raw.get('applyUrl'), description=plain('\n'.join(desc)))
        explicit_remote = loc.get('remote')
    elif ats == 'recruitee':
        locations = raw.get('locations') or []
        loc = obj(locations[0]) if locations else {}
        row.update(jobId=raw.get('id'), title=raw.get('title'), department=raw.get('department'),
                   location=raw.get('location') or loc.get('location'), city=raw.get('city') or loc.get('city'),
                   country=raw.get('country') or loc.get('country'), countryCode=raw.get('country_code') or loc.get('country_code'),
                   employmentType=raw.get('employment_type_code'), sourceUrl=raw.get('careers_url'),
                   applyUrl=raw.get('careers_apply_url'), createdAt=date(raw.get('published_at') or raw.get('created_at')),
                   updatedAt=date(raw.get('updated_at')), description=plain('\n'.join(x for x in
                        [raw.get('description'), raw.get('requirements')] if isinstance(x, str))))
        explicit_remote = raw.get('remote')
        s = obj(raw.get('salary'))
        salary(row, s.get('min'), s.get('max'), s.get('currency'), s.get('period'))
    elif ats == 'personio':
        job_id = str(raw.get('id') or '')
        row.update(jobId=job_id, title=raw.get('name'), department=raw.get('department'),
                   location=raw.get('office'), employmentType=raw.get('employmentType'),
                   createdAt=date(raw.get('createdAt')), sourceUrl=board.careers + 'job/' + job_id,
                   applyUrl=board.careers + 'job/' + job_id + '#apply', description=plain(raw.get('description')))
    elif ats == 'lever':
        cat = obj(raw.get('categories'))
        row.update(jobId=raw.get('id'), title=raw.get('text'), department=cat.get('department'), team=cat.get('team'),
                   location=cat.get('location'), allLocations='; '.join(cat.get('allLocations') or []) or None,
                   countryCode=raw.get('country'), employmentType=cat.get('commitment'),
                   workplaceType=raw.get('workplaceType'), createdAt=date(raw.get('createdAt'), True),
                   sourceUrl=raw.get('hostedUrl'), applyUrl=raw.get('applyUrl'))
        desc = [raw.get('description') or raw.get('descriptionPlain') or '']
        for section in raw.get('lists') or []:
            desc.extend([section.get('text') or '', section.get('content') or ''])
        desc.append(raw.get('additional') or raw.get('additionalPlain') or '')
        row['description'] = plain('\n'.join(desc))
        s = obj(raw.get('salaryRange'))
        salary(row, s.get('min'), s.get('max'), s.get('currency'), s.get('interval'))
    if not row['jobId'] or not text(row['title']):
        raise SchemaError('Job is missing id or title.')
    row['jobId'] = str(row['jobId'])
    row['title'] = text(row['title'])
    if not row['sourceUrl']:
        if ats == 'smartrecruiters':
            row['sourceUrl'] = f'https://jobs.smartrecruiters.com/{slug}/{row["jobId"]}'
        elif ats == 'workable':
            row['sourceUrl'] = f'https://apply.workable.com/{slug}/j/{row["jobId"]}/'
        elif ats == 'lever':
            row['sourceUrl'] = board.careers + '/' + row['jobId']
        else:
            raise SchemaError('Job is missing its public URL.')
    row['applyUrl'] = row['applyUrl'] or row['sourceUrl']
    for key in ['sourceUrl', 'applyUrl']:
        if urlsplit(row[key]).scheme not in {'http', 'https'}:
            raise SchemaError('Job contains an invalid public URL.')
    workplace = (text(row['workplaceType']) or '').lower().replace('-', '').replace(' ', '').replace('_', '')
    row['workplaceType'] = workplace if workplace in {'remote', 'hybrid', 'onsite'} else None
    if row['workplaceType']:
        row['isRemote'] = row['workplaceType'] == 'remote'
    elif isinstance(explicit_remote, bool):
        row['isRemote'] = explicit_remote
    elif (re.search(r'(?i)(?:^|[\s,;/()-])remote(?:$|[\s,;/()-])', row['location'] or '')
          and not re.search(r'(?i)\b(?:not|no|non)[ -]?remote|\bhybrid\b', row['location'] or '')):
        row['isRemote'], row['workplaceType'] = True, 'remote'
    row['allLocations'] = row['allLocations'] or row['location']
    row['sourceId'] = board.identity + ':' + row['jobId']
    return row
