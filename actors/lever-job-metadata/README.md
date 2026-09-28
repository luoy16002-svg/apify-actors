# Lever Jobs - Live Metadata and Published Salaries

Get current job metadata from the Lever company boards you choose. Export titles, teams, locations, workplace types, employment types and employer-published salary ranges, with direct posting and application links.

Use it to refresh a focused job directory, monitor hiring at a company shortlist or compare published pay ranges. It calls Lever's documented public Postings API during each run.

## Start a run

For `https://jobs.lever.co/spotify`, use the board slug `spotify`. The default input fetches up to 20 jobs from that board and works without edits.

```json
{
  "boards": ["spotify"],
  "region": "global",
  "titleContains": "",
  "locationContains": "",
  "workplaceType": "any",
  "maxItems": 20,
  "proxyConfiguration": { "useApifyProxy": false }
}
```

Use `region: "eu"` for boards hosted at `jobs.eu.lever.co`. All boards in one run use the selected region. The actor processes your list in order; earlier boards can fill the result limit.

## Input

| Field | Default | Meaning |
| --- | --- | --- |
| `boards` | `["spotify"]` | 1–25 known board slugs. Duplicate slugs are merged. |
| `region` | `global` | Lever's `global` or `eu` hosting region. |
| `titleContains` | Empty | Case-insensitive literal title filter. |
| `locationContains` | Empty | Case-insensitive literal filter across published locations. |
| `workplaceType` | `any` | `any`, `remote`, `hybrid` or `onsite`. |
| `maxItems` | `20` | Maximum saved jobs across all boards, 1–10,000. |
| `pageSize` | `100` | Source records per page, 1–100; also capped by `maxItems`. |
| `maxPages` | `100` | Maximum source pages across all boards, 1–500. |
| `requestDelaySeconds` | `1.2` | Minimum request interval, 1–60 seconds; longer robots delays take precedence. |
| `proxyConfiguration` | Proxy off | Optional Apify/custom proxy. No proxy is required for normal public access. |

All three filters are combined with AND and applied before saving or billing. Literal text filters do not accept regex syntax. Filtered searches may need to read more source jobs than they return.

## Output

Each flat row has a stable `jobId`, the requested board slug, published metadata and source URLs. `board` is an identifier, not an inferred legal company name. `allLocations` joins source locations with `; `. Optional missing values are `null`.

`isRemote` is true only when Lever explicitly labels the role remote, false for hybrid/on-site, and null when unknown. Salaries come only from the structured `salaryRange` field; salary text in descriptions is not inferred or converted. `salaryInterval` is retained as supplied. `createdAt` is the source creation timestamp, not a promised last-update time.

Here is one complete record from the live test. This source job did not provide structured salary data. The full three-record sample is in `sample-output.json`.

```json
{
  "jobId": "2193db3f-77c5-43b8-b030-8f92c9882bf1",
  "board": "spotify",
  "region": "global",
  "title": "Android Engineer - Experience",
  "department": "Engineering",
  "team": "Experience",
  "employmentType": "Permanent",
  "location": "London",
  "allLocations": "London; Stockholm",
  "countryCode": "GB",
  "workplaceType": "hybrid",
  "isRemote": false,
  "salaryMin": null,
  "salaryMax": null,
  "salaryCurrency": null,
  "salaryInterval": null,
  "createdAt": "2026-06-23T11:29:45.805000Z",
  "sourceUrl": "https://jobs.lever.co/spotify/2193db3f-77c5-43b8-b030-8f92c9882bf1",
  "applyUrl": "https://jobs.lever.co/spotify/2193db3f-77c5-43b8-b030-8f92c9882bf1/apply",
  "fetchedAt": "2026-09-28T22:50:35Z"
}
```

## Pricing

**Free during launch:** you only pay Apify's normal platform usage, which is a fraction of a cent for a typical run. Paid pricing may be introduced later (about $1.00 per 1,000 saved jobs); Apify announces any change on the Store pricing tab at least 14 days in advance.

Only unique matching jobs are saved; excluded jobs and duplicates are dropped before saving.

## FAQ and limitations

**Does it find all companies using Lever?** Supply known company slugs. This actor does not discover employers or search a prebuilt global database.

**Does it collect applications or contacts?** It retrieves public job metadata only. It does not request applicant records, submit applications, or export narrative job descriptions, email addresses or phone numbers. Follow `sourceUrl` for the complete job description.

**Why is salary empty?** Many employers do not populate Lever's structured salary field, even when pay is mentioned in the description. Missing or invalid amounts remain null. Salary unit tests cover populated fields; the saved live example has none.

**Why does a board return no jobs?** It may have no current postings, use a different slug/region, or have moved to another ATS. The public API can return an empty list for an unknown board, so an empty result does not establish which explanation applies.

**Why fewer results than requested?** There may be too few matches, the scan cap or spending limit may be reached, or malformed source rows may be skipped. `RUN_STATS` records filtered/skipped counts and the stop reason. A failed board request fails the run; previously saved rows remain available and may be incomplete.

**Are snapshots complete and resumable?** Posting lists can change during offset pagination. Records are deduplicated by region and job ID within the run, but completeness is not guaranteed while jobs are changing. Each new run is a fresh snapshot; restart/resurrection is not a resumable checkpoint.

## Responsible use

Use the [official Lever Postings API](https://github.com/lever/postings-api) for public job data and respect employer content rights and [Lever's terms](https://www.lever.co/legal/terms-of-service). This actor is independent of Lever and the employers listed. Use it for employment and business research; keep source links and retrieval dates with redistributed metadata.

The actor checks robots.txt, uses one request at a time and retries temporary failures with backoff. Denied paths and access errors stop the run. A proxy never changes these rules.

## Local development

Requires Python 3.13. Install `requirements-dev.txt` in a virtual environment, then run `python -m pytest -q` and `python -m src --input test-input.json` from this actor directory. Local SDK files stay in ignored `storage/`. See `TESTING.md` for exact commands, fixture provenance and results.
