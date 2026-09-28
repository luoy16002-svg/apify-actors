"""Normalize FSA establishments without inventing missing ratings or scores."""
from .common import SchemaError, boolean, integer, iso_date, number, text


def parse_establishment(raw: dict, *, fetched_at: str, extract_date: str | None) -> dict:
    if not isinstance(raw, dict):
        raise SchemaError('An establishment is not an object.')
    record_id = integer(raw.get('FHRSID'))
    name = text(raw.get('BusinessName'))
    if record_id is None or record_id <= 0 or not name:
        raise SchemaError('Establishment is missing a valid FHRSID or BusinessName.')
    geo = raw.get('geocode') if isinstance(raw.get('geocode'), dict) else {}
    scores = raw.get('scores') if isinstance(raw.get('scores'), dict) else {}
    latitude, longitude = number(geo.get('latitude')), number(geo.get('longitude'))
    if latitude is not None and not -90 <= latitude <= 90:
        latitude = None
    if longitude is not None and not -180 <= longitude <= 180:
        longitude = None
    rating = text(raw.get('RatingValue'))
    # Keep FHIS labels, Exempt, and AwaitingInspection as strings; never force 0.
    if rating is None and type(raw.get('RatingValue')) is int:
        rating = str(raw['RatingValue'])
    return {
        'fhrsId': str(record_id), 'businessName': name,
        'businessType': text(raw.get('BusinessType')), 'businessTypeId': integer(raw.get('BusinessTypeID')),
        'address': ', '.join(filter(None, [text(raw.get(f'AddressLine{i}')) for i in range(1, 5)])) or None,
        'postcode': text(raw.get('PostCode')), 'rating': rating,
        'ratingDate': iso_date(raw.get('RatingDate')), 'ratingKey': text(raw.get('RatingKey')),
        'schemeType': text(raw.get('SchemeType')), 'newRatingPending': boolean(raw.get('NewRatingPending')),
        'hygieneScore': integer(scores.get('Hygiene')), 'structuralScore': integer(scores.get('Structural')),
        'managementScore': integer(scores.get('ConfidenceInManagement')),
        'localAuthorityName': text(raw.get('LocalAuthorityName')),
        'localAuthorityCode': text(raw.get('LocalAuthorityCode')),
        'latitude': latitude, 'longitude': longitude,
        'sourceUrl': f'https://ratings.food.gov.uk/business/{record_id}',
        'sourceExtractedAt': text(extract_date), 'fetchedAt': fetched_at,
        'dataSource': 'Food Standards Agency',
        'licenseUrl': 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/',
    }


def parse_page(payload) -> tuple[list, dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get('establishments'), list):
        raise SchemaError('Expected an object with an establishments array; source schema may have changed.')
    meta = payload.get('meta')
    if not isinstance(meta, dict):
        raise SchemaError('Missing FSA pagination metadata.')
    if meta.get('returncode') not in (None, 'OK'):
        raise SchemaError('FSA reported an unsuccessful query.')
    return payload['establishments'], meta
