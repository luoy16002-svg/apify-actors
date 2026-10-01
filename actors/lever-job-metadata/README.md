# Lever Jobs - Live Metadata and Published Salaries

Pull the current openings from any company that hires through Lever. You give it board names, it gives you a clean
table of jobs: title, team, department, location, workplace type, employment type, the salary range when the
employer publishes one, and links to the posting and the application form.

Good for keeping a job board fresh, watching who a shortlist of companies is hiring, or comparing published pay.
Data comes straight from Lever's official public Postings API on every run.

## Quick start

A company's board name is the last part of its Lever URL: `https://jobs.lever.co/spotify` is `spotify`.

```json
{
  "boards": ["spotify", "palantir"],
  "titleContains": "engineer",
  "workplaceType": "remote",
  "maxItems": 200
}
```

Boards hosted on `jobs.eu.lever.co` need `"region": "eu"`.

## Input

| Field | Default | What it does |
| --- | --- | --- |
| `boards` | `["spotify"]` | 1-25 board names, processed in order. |
| `region` | `global` | `global` or `eu`, for all boards in the run. |
| `titleContains` | empty | Keep jobs whose title contains this text (case-insensitive). |
| `locationContains` | empty | Keep jobs with a location containing this text. |
| `workplaceType` | `any` | `any`, `remote`, `hybrid` or `onsite`. |
| `maxItems` | `20` | Stop after this many saved jobs (up to 10,000). |
| `proxyConfiguration` | off | Not needed for normal use. |

Filters are combined, and they run before anything is saved, so you only pay for jobs you keep.

## Output

One row per job. Example:

```json
{
  "jobId": "2193db3f-77c5-43b8-b030-8f92c9882bf1",
  "board": "spotify",
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

Salary fields are filled only from Lever's structured salary data. Pay mentioned inside a job description is not
guessed or parsed, so many rows have empty salary fields. `isRemote` is `null` when the employer doesn't say.

## Pricing

$2.00 per 1,000 saved jobs, plus a tiny start fee per run. Filtered-out jobs and duplicates are free.

## FAQ

**Can it find every company that uses Lever?** No. You supply the board names; it doesn't keep a global company list.

**Does it export full job descriptions or contacts?** No. It returns job metadata and links. Follow `sourceUrl` for
the full description. No applicant data, emails or phone numbers.

**A board returned nothing.** The company may have no open roles right now, may use the EU region, or may have moved
to another applicant tracking system.

**Fewer results than `maxItems`?** Usually there simply weren't more matches. The run's `RUN_STATS` record shows how
many jobs were scanned, filtered and saved.

## Responsible use

This actor uses Lever's public [Postings API](https://github.com/lever/postings-api), sends one request at a time,
checks robots.txt and backs off on errors. It is not affiliated with Lever or the employers listed. Keep the source
links and dates when you republish job data.
