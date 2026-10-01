"""Normalize source facts without substituting award values for estimates."""
import re
from urllib.parse import urlsplit
from .common import SchemaError,number,text
from .helpers import plain_text,redact,timestamp,output_url

OGL='https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/'
TED_LICENSE='https://ted.europa.eu/en/legal-notice'

def obj(value):return value if isinstance(value,dict) else {}
def arr(value):return value if isinstance(value,list) else []

def unique(values):return list(dict.fromkeys(v for v in values if v is not None and v!=''))

def translated(value):
    if isinstance(value,dict):
        value=value.get('eng') or value.get('en') or next((value[k] for k in sorted(value) if value[k]),None)
    if isinstance(value,list):return '; '.join(unique(plain_text(v) for v in value if isinstance(v,str))) or None
    return plain_text(value)

def source_date(value):
    if not isinstance(value,str):return None
    # TED publishes a calendar date with an offset, not an exact publication time.
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:Z|[+-]\d{2}:\d{2})?',value):
        return value[:10] if timestamp(value[:10]) else None
    return timestamp(value)

def cpv_codes(tender):
    values=[]
    def visit(value):
        if isinstance(value,dict):
            for key,val in value.items():
                if key in {'classification','additionalClassifications'}:
                    for item in val if isinstance(val,list) else [val]:
                        if isinstance(item,dict) and str(item.get('scheme','')).upper()=='CPV':
                            code=str(item.get('id','')).split('-')[0]
                            if re.fullmatch(r'\d{8}',code):values.append(code)
                elif key in {'items','lots'}:visit(val)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(tender)
    return unique(values)

def notice_link(source,release,tender):
    origin='https://www.find-tender.service.gov.uk' if source=='find-tender' else 'https://www.contractsfinder.service.gov.uk'
    for doc in arr(tender.get('documents')):
        url=output_url(obj(doc).get('url'))
        if url and urlsplit(url).netloc==urlsplit(origin).netloc and urlsplit(url).path.startswith('/Notice/'):
            return url
    id=release['id']
    if source=='find-tender' and re.fullmatch(r'\d{6}-\d{4}',id):return origin+'/Notice/'+id
    match=re.match(r'([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})(?:-|$)',id)
    return origin+'/Notice/'+match[1] if source=='contracts-finder' and match else None

def parse_ocds(release,source):
    if not isinstance(release,dict) or not text(release.get('id')) or not text(release.get('ocid')):
        raise SchemaError('OCDS release needs source id and ocid.')
    tender=obj(release.get('tender'));buyer=obj(release.get('buyer'));buyer_id=buyer.get('id')
    parties=[p for p in arr(release.get('parties')) if isinstance(p,dict) and (p.get('id')==buyer_id or 'buyer' in arr(p.get('roles')))]
    countries=unique(redact(obj(p.get('address')).get('country') or obj(p.get('address')).get('countryName')) for p in parties)
    tags=[text(x) for x in arr(release.get('tag')) if text(x)]
    docs=arr(tender.get('documents'))
    notice_type=next((redact(obj(d).get('noticeType')) for d in docs if obj(d).get('id')==release['id'] and obj(d).get('noticeType')),None)
    value=obj(tender.get('value'));amount=number(value.get('amount'))
    if amount is not None and amount<0:amount=None
    raw_deadline=obj(tender.get('tenderPeriod')).get('endDate')
    deadline=source_date(raw_deadline)
    return {'recordType':'notice','source':source,'noticeId':release['id'],'sourceId':release['id'],'ocid':release['ocid'],
            'title':plain_text(tender.get('title')),'description':plain_text(tender.get('description')),
            'buyerName':redact(buyer.get('name')) or '; '.join(unique(redact(p.get('name')) for p in parties)) or None,
            'buyerCountry':'; '.join(countries) or None,'buyerCountries':countries,
            'noticeType':notice_type or ','.join(tags) or None,'publishedAt':source_date(release.get('date')),
            'deadline':deadline,'deadlines':[deadline] if deadline else [],'deadlineRaw':redact(raw_deadline),
            'estimatedValue':amount,'currency':redact(value.get('currency')),
            'valueBasis':'tender.value' if amount is not None else None,
            'cpvCodes':cpv_codes(tender),'procedureType':redact(tender.get('procurementMethod')),
            'officialUrl':notice_link(source,release,tender),'licenseUrl':OGL,
            'attribution':'Contains public sector information licensed under the Open Government Licence v3.0.'}

def ted_deadlines(raw):
    dates=raw.get('deadline-receipt-tender-date-lot',[])
    times=raw.get('deadline-receipt-tender-time-lot',[])
    if isinstance(dates,str):dates=[dates]
    if isinstance(times,str):times=[times]
    dates=[x for x in arr(dates) if isinstance(x,str)]
    times=[x for x in arr(times) if isinstance(x,str)]
    result=[]
    for date in dates if isinstance(dates,list) else []:
        parsed=source_date(date)
        if parsed:result.append(parsed)
    # Search fields are flattened, so arrays cannot safely be zipped across lots.
    # A single distinct date and single distinct time are unambiguous.
    if dates and len(dates)==len(times) and len(set(dates))==1 and len(set(times))==1:
        clock=times[0]
        if isinstance(clock,str) and re.fullmatch(r'\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})',clock):
            combined=timestamp(dates[0][:10]+'T'+clock)
            if combined:result=[combined]
    return sorted(unique(result))

def parse_ted(raw):
    publication=text(raw.get('publication-number'))
    if not publication or not re.fullmatch(r'\d+-\d{4}',publication):raise SchemaError('TED notice needs a publication number.')
    countries=unique(redact(x) for x in arr(raw.get('organisation-country-buyer') or raw.get('buyer-country')))
    value=number(raw.get('estimated-value-proc'))
    if value is not None and value<0:value=None
    codes=unique(str(x).split('-')[0] for x in arr(raw.get('classification-cpv')) if re.fullmatch(r'\d{8}(?:-\d)?',str(x)))
    deadlines=ted_deadlines(raw)
    return {'recordType':'notice','source':'ted','noticeId':publication,'sourceId':text(raw.get('notice-identifier')) or publication,'ocid':None,
            'title':translated(raw.get('notice-title')),'description':translated(raw.get('description-proc')) or translated(raw.get('description-lot')),
            'buyerName':translated(raw.get('buyer-name')),'buyerCountry':'; '.join(countries) or None,'buyerCountries':countries,
            'noticeType':redact(raw.get('notice-type')),'publishedAt':source_date(raw.get('publication-date')),
            'deadline':deadlines[0] if deadlines else None,'deadlines':deadlines,
            'deadlineRaw':'; '.join(unique(str(x) for x in arr(raw.get('deadline-receipt-tender-date-lot')))) or None,
            'estimatedValue':value,'currency':redact(raw.get('estimated-value-cur-proc')),
            'valueBasis':'estimated-value-proc' if value is not None else None,'cpvCodes':codes,
            'procedureType':redact(raw.get('procedure-type')),'officialUrl':f'https://ted.europa.eu/en/notice/-/detail/{publication}',
            'licenseUrl':TED_LICENSE,'attribution':'Source: TED, Supplement to the Official Journal of the European Union. Fields normalized; see official notice.'}
