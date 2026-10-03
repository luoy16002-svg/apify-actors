"""Independent bounded Python implementation of the documented fingerprint format."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import regex
from bs4 import BeautifulSoup

from .net import FetchError


def array(value):
    return value if isinstance(value, list) else [] if value is None else [value]


def tagged(value):
    parts = value.split('\\;')
    tags = {}
    for part in parts[1:]:
        key, _, val = part.partition(':')
        tags[key] = val
    try:
        confidence = max(0, min(100, int(tags.get('confidence', '100'))))
    except ValueError:
        confidence = 100
    return parts[0], confidence, tags.get('version')


def extract_version(template, match):
    if not template:
        return None
    def group(n):
        try:
            return match.group(int(n)) or ''
        except (IndexError, KeyError):
            return ''
    # Wappalyzer supports optional-capture ternaries, then normal capture substitution.
    template = re.sub(r'\\(\d+)\?([^:]*):(.*)', lambda m: m[2] if group(m[1]) else m[3], template)
    result = re.sub(r'\\(\d+)', lambda m: group(m[1]), template).strip()
    return result[:100] if result and not any(ord(c) < 32 for c in result) else None


@dataclass
class Rule:
    channel: str
    key: str
    source: str
    pattern: object
    confidence: int
    version: str | None


def signals(html, headers, cookies, url, js=None):
    soup = BeautifulSoup(html, 'html.parser')
    meta = {}
    for node in soup.find_all('meta'):
        name = node.get('name') or node.get('property') or node.get('http-equiv')
        if name and node.get('content') is not None:
            meta.setdefault(name.lower(), []).append(node['content'])
    scripts = soup.find_all('script')
    return {'html': [html], 'url': [url], 'headers': {k.lower(): array(v) for k, v in headers.items()},
            'cookies': {k.lower(): array(v) for k, v in cookies.items()}, 'meta': meta,
            'scriptSrc': [node['src'] for node in scripts if node.get('src')],
            'scripts': [node.get_text()[:250000] for node in scripts if not node.get('src') and
                        (node.get('type') or '').lower() in {'', 'text/javascript', 'application/javascript', 'module'}][:100],
            'js': {k: array(v) for k, v in (js or {}).items()},
            'soup': soup}


class Matcher:
    CHANNELS = ('headers', 'cookies', 'meta', 'html', 'scriptSrc', 'scripts', 'url', 'js')

    def __init__(self, technologies, categories):
        self.technologies, self.categories = technologies, categories
        self.rules, self.invalid_patterns = {}, []
        for name, tech in technologies.items():
            rules = []
            for channel in self.CHANNELS:
                raw = tech.get(channel)
                mapping = raw if isinstance(raw, dict) else {'': raw}
                for key, patterns in mapping.items():
                    for source in array(patterns):
                        if not isinstance(source, str):
                            continue
                        pattern, confidence, version = tagged(source)
                        try:
                            compiled = regex.compile(pattern.replace('[^]', '[\\s\\S]'), regex.IGNORECASE)
                        except regex.error:
                            self.invalid_patterns.append({'technology': name, 'channel': channel})
                            continue
                        rules.append(Rule(channel, key if channel == 'js' else key.lower(), source, compiled, confidence, version))
            self.rules[name] = rules

    @property
    def js_paths(self):
        # Only identifier/index paths are read; no eval, calls, or user expressions.
        return sorted({r.key for rules in self.rules.values() for r in rules if r.channel == 'js'
                       and re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$0-9][\w$]*)*', r.key)})

    def detect(self, data, category_filter=None, max_seconds=20):
        start = time.monotonic()
        direct, timeouts = {}, 0
        for name, rules in self.rules.items():
            if time.monotonic() - start > max_seconds:
                raise FetchError('matcher_timeout', 'Fingerprint matching exceeded its CPU time budget.')
            hits = []
            for rule in rules:
                channel = data.get(rule.channel, {})
                values = channel.get(rule.key, []) if isinstance(channel, dict) else channel
                for value in values:
                    try:
                        match = rule.pattern.search(str(value), timeout=.015)
                    except TimeoutError:
                        timeouts += 1
                        break
                    if match:
                        hits.append((rule.confidence, extract_version(rule.version, match), rule.channel + (':' + rule.key if rule.key else '')))
                        break  # one pattern contributes confidence at most once
            if hits:
                confidence = min(100, sum(h[0] for h in hits))
                version_hits = sorted((h for h in hits if h[1]), key=lambda h: (h[0], len(h[1])), reverse=True)
                if confidence:
                    direct[name] = {'confidence': confidence, 'version': version_hits[0][1] if version_hits else None,
                                    'evidence': sorted(set(h[2] for h in hits))}
        active = self.resolve(direct)
        rows = []
        for name, value in sorted(active.items()):
            tech = self.technologies[name]
            cats = [{'id': c, 'name': self.categories.get(str(c), {}).get('name', str(c))} for c in tech.get('cats', [])]
            if category_filter and not any(str(c['id']).casefold() in category_filter or c['name'].casefold() in category_filter for c in cats):
                continue
            rows.append({'name': name, 'version': value['version'], 'confidence': value['confidence'],
                         'categories': cats, 'website': tech.get('website', ''), 'evidence': value['evidence']})
        return rows, {'regexTimeouts': timeouts, 'unsupportedPatterns': len(self.invalid_patterns),
                      'matchSeconds': round(time.monotonic() - start, 4)}

    def prerequisites(self, name, active):
        tech = self.technologies[name]
        required = [tagged(x)[0] for x in array(tech.get('requires'))]
        required_cats = array(tech.get('requiresCategory'))
        cats = {c for n in active for c in self.technologies[n].get('cats', [])}
        return all(x in active for x in required) and all(x in cats for x in required_cats)

    def resolve(self, direct):
        # Rebuild closure after exclusions. This removes orphan implication cycles and
        # gated dependants when their only supporting root is excluded.
        banned = set()
        for _ in range(len(self.technologies) + 1):
            active = {}
            for _round in range(len(self.technologies) + 1):
                before = {k: (v['confidence'], v['version'], tuple(v['evidence'])) for k, v in active.items()}
                for name, value in direct.items():
                    if name not in banned and self.prerequisites(name, active):
                        previous = active.get(name, {})
                        active[name] = {**value, 'confidence': max(value['confidence'], previous.get('confidence', 0)),
                                        'evidence': list(value['evidence'])}
                for name, value in list(active.items()):
                    for implication in array(self.technologies[name].get('implies')):
                        target, weight, version = tagged(implication)
                        if target not in self.technologies or target in banned or not self.prerequisites(target, active):
                            continue
                        confidence = min(value['confidence'], weight)
                        if not confidence:
                            continue
                        current = active.get(target)
                        if not current:
                            active[target] = {'confidence': confidence, 'version': version if version and '\\' not in version else None,
                                              'evidence': ['implied:' + name]}
                        else:
                            current['confidence'] = max(current['confidence'], confidence)
                            if target not in direct and 'implied:' + name not in current['evidence']:
                                current['evidence'].append('implied:' + name)
                after = {k: (v['confidence'], v['version'], tuple(v['evidence'])) for k, v in active.items()}
                if before == after:
                    break
            before_bans = set(banned)
            remaining = set(active)
            for name in sorted(list(active), key=lambda n: (n not in direct, -active[n]['confidence'], n)):
                if name not in remaining:
                    continue
                for excluded in array(self.technologies[name].get('excludes')):
                    target = tagged(excluded)[0]
                    if target in remaining and target != name:
                        remaining.remove(target)
                        banned.add(target)
            if before_bans == banned:
                return active
        raise FetchError('resolution_error', 'Technology dependency resolution did not converge.')


def convenience(technologies):
    groups = {'cms': {1}, 'ecommerce': {6, 108}, 'analytics': {10}, 'frameworks': {12, 18, 26, 66},
              'cdn': {31}, 'hosting': {62, 88}, 'programmingLanguages': {27}}
    return {field: [t['name'] for t in technologies if any(c['id'] in categories for c in t['categories'])]
            for field, categories in groups.items()}
