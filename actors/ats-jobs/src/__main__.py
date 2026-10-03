"""Use `python -m src`; optional --input is for local testing only."""
import argparse
import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', help='JSON input file inside this Actor folder (local only).')
    args = parser.parse_args()
    at_home = os.environ.get('APIFY_IS_AT_HOME', '').lower() in {'1', 'true'}
    supplied = None
    if not at_home:
        # Force all local runtime files into this Actor, ignoring external storage paths.
        os.environ['APIFY_LOCAL_STORAGE_DIR'] = str(ROOT / 'storage')
        os.environ['CRAWLEE_STORAGE_DIR'] = str(ROOT / 'storage')
        os.environ['APIFY_PURGE_ON_START'] = 'true'
        if args.input:
            path = (ROOT / args.input).resolve()
            if not path.is_relative_to(ROOT):
                parser.error('--input must be inside the Actor folder.')
            supplied = json.loads(path.read_text(encoding='utf-8-sig'))
    elif args.input:
        parser.error('--input is local-only; supply cloud input through Apify.')
    from apify import Actor
    from .main import main
    asyncio.run(main(Actor, supplied))


if __name__ == '__main__':
    run()
