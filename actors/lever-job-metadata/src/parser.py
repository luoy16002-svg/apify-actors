"""Normalize employer-supplied job metadata; no personal contact fields."""
from datetime import datetime, timezone
from uuid import UUID

from .common import SchemaError, number, text


def parse_job(raw: dict, *, board: str, region: str, fetched_at: str) -> dict:
    if not isinstance(raw, dict):
        raise SchemaError('Job record is not an object.')
    try:
        job_id = str(UUID(raw.get('id', '')))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SchemaError('Job is missing a valid UUID.') from exc
    title = text(raw.get('text'))
    if not title:
        raise SchemaError('Job is missing its title.')
    categories = raw.get('categories') if isinstance(raw.get('categories'), dict) else {}
    salary = raw.get('salaryRange') if isinstance(raw.get('salaryRange'), dict) else {}
    minimum, maximum = number(salary.get('min')), number(salary.get('max'))
    minimum = minimum if minimum is not None and minimum >= 0 else None
    maximum = maximum if maximum is not None and maximum >= 0 else None
    # Preserve uncertainty rather than swapping contradictory source values.
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum = maximum = None
    workplace = (text(raw.get('workplaceType')) or '').lower()
    workplace = {'on-site': 'onsite', 'on site': 'onsite'}.get(workplace, workplace)
    if workplace not in {'remote', 'hybrid', 'onsite'}:
        workplace = None
    created_at = None
    milliseconds = number(raw.get('createdAt'))
    if milliseconds is not None and milliseconds >= 0:
        try:
            created_at = datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')
        except (OverflowError, OSError, ValueError):
            pass
    host = 'jobs.eu.lever.co' if region == 'eu' else 'jobs.lever.co'
    canonical = f'https://{host}/{board}/{job_id}'
    locations = categories.get('allLocations')
    if not isinstance(locations, list):
        locations = []
    locations = list(dict.fromkeys(v for value in locations if (v := text(value))))
    location = text(categories.get('location'))
    if not locations and location:
        locations = [location]
    return {
        'jobId': job_id, 'board': board, 'region': region, 'title': title,
        'department': text(categories.get('department')), 'team': text(categories.get('team')),
        'employmentType': text(categories.get('commitment')), 'location': location,
        'allLocations': '; '.join(locations) or None, 'countryCode': text(raw.get('country')),
        'workplaceType': workplace,
        'isRemote': workplace == 'remote' if workplace is not None else None,
        'salaryMin': minimum, 'salaryMax': maximum,
        'salaryCurrency': text(salary.get('currency')), 'salaryInterval': text(salary.get('interval')),
        'createdAt': created_at, 'sourceUrl': canonical, 'applyUrl': canonical + '/apply',
        'fetchedAt': fetched_at,
    }


def parse_page(payload) -> list:
    if not isinstance(payload, list):
        raise SchemaError('Expected a job array; the public API response schema may have changed.')
    return payload
