# Test record

Completed 2026-09-29 Asia/Singapore. Latest live run finished **2026-09-28T22:50:31Z**. Python 3.13.5 on Windows; Apify SDK 3.4.1, HTTPX 0.28.1 and Protego 0.7.0.

## Results

| Check | Result |
| --- | --- |
| Offline tests | **49 passed**; [log](tests/unit-test.log) |
| Real local Apify SDK run | Exit 0; **3 unique businesses**, 2 source pages |
| Requests in final live run | 3 total: robots.txt plus 2 API requests; 0 retries |
| Output | [sample-output.json](sample-output.json), 3 flat records |
| Source policy | API-host robots.txt returned 404; documented public API used |
| Input schema | Validated against the downloaded official Apify input meta-schema |
| Dataset schema | All 3 sample records validated with JSON Schema format checks |
| README | Output example exactly matches the first saved live record |

The tests cover real fixture parsing, missing fields, FHIS text ratings, zero scores, null coordinates, malformed identities, changing envelopes, fixed-size pagination, duplicate/overlapping pages, scan/item limits, robots wildcard/allow precedence, crawl delays, 429 Retry-After, bounded network/5xx retries, permanent access failures and simulated billing limits. No test contacts the source unless the live command is explicitly used.

The local dataset and `RUN_STATS` were produced by `Actor.push_data()` and the real SDK, not a substitute JSON-only runner. [live-test-result.json](live-test-result.json), [verification-result.json](verification-result.json) and [live log](tests/live-test.log) retain the final evidence.

## Commands used

From repository root `C:\Projects\xinmi\apify`, the shared virtual environment and all temporary/cache directories were created inside this folder:

```powershell
New-Item -ItemType Directory -Force .tmp,.cache | Out-Null
$env:TEMP = Join-Path $PWD '.tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $PWD '.cache'
$env:PIP_CONFIG_FILE = 'NUL'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r actors/uk-food-hygiene-ratings/requirements-dev.txt
.\.venv\Scripts\python.exe -B scripts/verify.py --live
```

`scripts/verify.py --live` runs both actors' offline suites, then each real SDK entry point with `test-input.json`, captures the logs, exports the SDK datasets and validates the schemas. The development session initially installed compatible ranges, then pinned the exact resolved runtime/test versions in the supplied requirement files. The equivalent isolated actor commands are:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:APIFY_IS_AT_HOME = 'false'
$env:APIFY_TOKEN = ''
Push-Location actors/uk-food-hygiene-ratings
..\..\.venv\Scripts\python.exe -B -m pytest -q
..\..\.venv\Scripts\python.exe -B -m src --input test-input.json
Pop-Location
```

`test-input.json` searches `Pret A Manger` and `London`, with `maxItems: 3`, `pageSize: 2`, `maxPages: 3`, delay 1.2 seconds and proxies off. The live endpoint was `https://api.ratings.food.gov.uk/Establishments`, with the documented `x-api-version: 2` header and `pageNumber` 1 then 2.

To rerun only offline validation from the repository root, use `.\.venv\Scripts\python.exe -B scripts/verify.py`. To use this actor on its own, create an actor-local `.venv`, install `requirements-dev.txt`, and run `python -m pytest -q` / `python -m src --input test-input.json` in this directory. On other platforms use that virtual environment's Python executable.

## Fixture provenance and limits

`tests/fixtures/live-page.json` was saved from a three-result public FSA response earlier in this session. Unused phone, authority email and right-to-reply fields were removed; no retained field values were fabricated. Source attribution: Food Standards Agency, [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). Adverse shapes are generated in memory by the offline tests.

The initial SDK invocation from the tool's actor-directory context failed to create local storage. Launching from the authorized repository-root context resolved that environment permission issue; no filesystem permissions were changed. A preliminary successful source run encountered an overlapping record and deduplicated it; the final run saw no overlap. This illustrates why these changing offset-paginated results are not guaranteed full snapshots.

No Docker image was built: the Docker daemon's image/cache storage would be outside the permitted folder. The Dockerfile uses the documented official `apify/actor-python:3.13` image. Apify cloud builds, production event billing, cloud storage and optional proxies were not exercised. Synthetic event caps were tested offline with simulated SDK charge results; the human publisher must confirm real billing in Console. No account login, publication or external write occurred.
