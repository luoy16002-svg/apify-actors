# Test record

Completed 2026-09-29 Asia/Singapore. Latest live run finished **2026-09-28T22:50:36Z**. Python 3.13.5 on Windows; Apify SDK 3.4.1, HTTPX 0.28.1 and Protego 0.7.0.

## Results

| Check | Result |
| --- | --- |
| Offline tests | **58 passed**; [log](tests/unit-test.log) |
| Real local Apify SDK run | Exit 0; **3 unique jobs**, 2 source pages |
| Requests in final live run | 3 total: robots.txt plus 2 API requests; 0 retries |
| Output | [sample-output.json](sample-output.json), 3 flat records |
| Source policy | Global and EU robots permit the path with a 1-second delay; actor uses at least 1.2 seconds |
| Input schema | Validated against the downloaded official Apify input meta-schema |
| Dataset schema | All 3 sample rows validated with JSON Schema format checks |
| README | Output example exactly matches the first live record |

Tests cover saved real metadata, missing categories/salaries, published salary typing, invalid salary bounds, unknown remote status, timestamp normalization, canonical global/EU links, schema changes, input validation, board deduplication, offset pagination, filters before billing, repeated pages, scan/item limits, robots rules, rate-limit/network retries and simulated billing caps.

The live run used `Actor.push_data()` and local Apify SDK storage. [live-test-result.json](live-test-result.json), [verification-result.json](verification-result.json) and the [live log](tests/live-test.log) retain final results. Tests use HTTPX's mocked transport rather than real requests unless the live entry point is explicitly run.

## Commands used

From repository root `C:\Projects\xinmi\apify`:

```powershell
New-Item -ItemType Directory -Force .tmp,.cache | Out-Null
$env:TEMP = Join-Path $PWD '.tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $PWD '.cache'
$env:PIP_CONFIG_FILE = 'NUL'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r actors/lever-job-metadata/requirements-dev.txt
.\.venv\Scripts\python.exe -B scripts/verify.py --live
```

The session initially installed compatible dependency ranges; requirement files now pin the exact resolved direct runtime/test versions. The verification script runs both actors' suites, performs three-item SDK runs, exports the datasets and checks schemas and README consistency. The isolated actor commands are:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:APIFY_IS_AT_HOME = 'false'
$env:APIFY_TOKEN = ''
Push-Location actors/lever-job-metadata
..\..\.venv\Scripts\python.exe -B -m pytest -q
..\..\.venv\Scripts\python.exe -B -m src --input test-input.json
Pop-Location
```

The recorded input was `boards: ["spotify"]`, global region, `maxItems: 3`, `pageSize: 2`, `maxPages: 3`, delay 1.2 and proxies off. Requests used `https://api.lever.co/v0/postings/spotify?mode=json&skip=0&limit=2`, then `skip=2`. SDK `RUN_STATS` recorded no duplicates, filtered jobs or malformed rows.

Offline-only repository validation: `.\.venv\Scripts\python.exe -B scripts/verify.py`. For a standalone copy, create `.venv` here, install `requirements-dev.txt`, then run `python -m pytest -q` and `python -m src --input test-input.json` from this directory. Runtime storage always stays in ignored `storage/`.

## Fixture provenance and limits

`tests/fixtures/live-page.json` contains three public Spotify job records from an earlier small API probe. Only job metadata used by the parser plus source URLs were retained. Narrative descriptions and unrelated fields were removed; retained source values are unchanged. The initial `mistral` probe returned an empty list, so the functional example uses the verified `spotify` board.

The live sample has no structured salaries. Populated/invalid salary cases are offline tests, not invented live evidence. Global-region pagination was live-tested; EU URL mapping was tested offline and EU robots was read, but no EU employer feed was fetched. Multi-board collection and filters were tested offline. Optional proxies, production billing and Apify cloud builds/storage were not exercised.

An initial invocation from the tool's nested working-directory context hit a workspace-storage creation error. Running from repository root resolved the environment issue without changing permissions. Docker was not run because its image/cache storage would leave the allowed folder; the Dockerfile uses the official `apify/actor-python:3.13` image. The publisher must perform the cloud build and real billing smoke test described in `SUMMARY.md`. No login, publication or external write occurred.
