"""Tolerant RSS/Atom parsing. This module only parses bytes; never fetches URLs."""
import calendar
import hashlib
import re
from datetime import datetime,timezone
from urllib.parse import urljoin
import feedparser
from .common import SchemaError,integer,number,text
from .helpers import plain_text,redact,timestamp,output_url,EMAIL

def explicit(value):
    if isinstance(value,bool):return value
    if isinstance(value,(str,int)):
        word=str(value).strip().lower()
        if word in {'yes','true','explicit','1'}:return True
        if word in {'no','false','clean','0'}:return False
    return None

def duration(value):
    if isinstance(value,bool):return None
    if isinstance(value,(str,int,float)):
        s=str(value).strip()
        if re.fullmatch(r'\d+(?:\.\d+)?',s):return int(float(s)) if number(s) is not None else None
        if re.fullmatch(r'\d+:\d{1,2}(?::\d{1,2})?',s):
            parts=[int(x) for x in s.split(':')]
            if any(x>=60 for x in parts[1:]):return None
            return sum(x*60**i for i,x in enumerate(reversed(parts)))
        match=re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?',s,re.I)
        if match and any(x is not None for x in match.groups()):
            h,m,sec=match.groups()
            try: return int(float(h or 0)*3600+float(m or 0)*60+float(sec or 0))
            except (ValueError, OverflowError): return None
    return None

def episode_date(entry):
    entry = dict(entry)  # Avoid feedparser deprecated updated/published aliases.
    for key in ['published','updated']:
        value=timestamp(entry.get(key))
        if value:return value
        parsed=entry.get(key+'_parsed')
        if parsed:
            try:return datetime.fromtimestamp(calendar.timegm(parsed),timezone.utc).isoformat().replace('+00:00','Z')
            except (ValueError,OverflowError,TypeError):pass
    return None

def parse_feed(content, feed_url, lookup=None, content_type=None):
    # Feedparser is tolerant of broken XML. DTDs are not needed by podcast feeds.
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b',content.replace(b'\x00',b''),re.I):
        raise SchemaError('RSS with DTD or entity declarations is unsupported.')
    content = re.sub(br'(xmlns:[A-Za-z_][\w.-]*\s*=\s*[\"\'])https?://(?:www\.)?itunes\.com/dtds/podcast-1\.0\.dtd/?', br'\1http://www.itunes.com/dtds/podcast-1.0.dtd', content, flags=re.I)
    # Feedparser maps only yes/clean, so preserve modern true/false and no values.
    def normalize_flag(match):
        flag = explicit(match[2].decode('ascii', errors='ignore'))
        return match[1] + (b'yes' if flag else b'clean') + match[3] if flag is not None else match[0]
    content = re.sub(br'(<[A-Za-z_][\w.-]*:explicit(?:\s[^>]*)?>)([^<]*)(</[A-Za-z_][\w.-]*:explicit\s*>)', normalize_flag, content, flags=re.I)
    parsed=feedparser.parse(content,response_headers={'content-location':feed_url,'content-type':content_type or 'application/xml'})
    if not parsed.get('version') or not isinstance(parsed.get('entries'),list):
        raise SchemaError('Source is not a recognizable RSS or Atom feed.')
    if not output_url(feed_url): raise SchemaError('Feed URL cannot be emitted without exposing a contact address.')
    lookup=lookup or {}
    feed=parsed.feed
    show={'showTitle':plain_text(feed.get('title')) or redact(lookup.get('collectionName')),
          'showId':str(lookup['collectionId']) if lookup.get('collectionId') else None,
          'feedUrl':output_url(feed_url), 'showAuthor':plain_text(feed.get('author')) or redact(lookup.get('artistName')),
          'showDescription':plain_text(feed.get('subtitle') or feed.get('description') or feed.get('summary')),
          'showLanguage':redact(feed.get('language')), 'showUrl':output_url(urljoin(feed_url,feed.get('link',''))) if feed.get('link') else output_url(lookup.get('collectionViewUrl')),
          'showGenres':[redact(x) for x in lookup.get('genres',[]) if isinstance(x,str)],
          'showExplicit':explicit(feed.get('itunes_explicit'))}
    return show,parsed.entries,bool(parsed.get('bozo'))

def parse_episode(entry,show):
    title=plain_text(entry.get('title'))
    guid_raw=text(entry.get('id') or entry.get('guid'))
    guid=EMAIL.sub('[redacted email]',guid_raw) if guid_raw else None
    base=show['feedUrl']
    audio=None
    for link in entry.get('enclosures',[]):
        href=link.get('href') or link.get('url')
        mime=str(link.get('type','')).lower()
        if href and (mime.startswith('audio/') or (not mime or mime=='application/octet-stream') and re.search(r'\.(mp3|m4a|aac|ogg|opus|wav)(?:\?|$)',href,re.I)):
            audio=output_url(urljoin(base,href))
            if audio:break
    page=output_url(urljoin(base,entry.get('link',''))) if entry.get('link') else None
    published=episode_date(entry)
    if not any((title,guid,audio,page)):raise SchemaError('Episode has no usable identity or title.')
    identity=guid_raw or audio or page or f'{title}|{published}'
    key=hashlib.sha256((base+'\n'+identity).encode()).hexdigest()
    description=entry.get('summary') or entry.get('description')
    if not description:
        description=next((c.get('value') for c in entry.get('content',[]) if c.get('value')),None)
    season,episode=integer(entry.get('itunes_season')),integer(entry.get('itunes_episode'))
    return {**show,'recordType':'episode','episodeKey':key,'episodeTitle':title,'guid':guid,
            'publishedAt':published,'durationSeconds':duration(entry.get('itunes_duration')),
            'audioUrl':audio,'episodeUrl':page,'description':plain_text(description),
            'seasonNumber':season if season is not None and season>=0 else None,
            'episodeNumber':episode if episode is not None and episode>=0 else None,
            'explicit':explicit(entry.get('itunes_explicit')) if 'itunes_explicit' in entry else show['showExplicit']}
