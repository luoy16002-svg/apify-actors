# UK & EU Public Tenders - Find a Tender, Contracts Finder, TED

Pull new public procurement notices from three official sources in one run: the UK's Find a Tender service, UK
Contracts Finder and the EU's Tenders Electronic Daily (TED). Filter by date, keyword, CPV code and estimated value,
and get one clean table with the buyer, notice type, deadline, value, CPV codes and a link to the official notice.

Built for bid teams, consultants and sales teams who want a daily list of tenders in their field without checking three
portals by hand. Data comes from each service's public API at the time you run it.

## Quick start

```json
{
  "keywords": ["software", "cyber security"],
  "publishedFrom": "2026-09-01",
  "maxResults": 500
}
```

Leave `keywords` empty to get everything published in the date range. With no dates, the run covers the last seven
days.

## Input

| Field | Default | What it does |
| --- | --- | --- |
| `sources` | all three | Any of `find-tender`, `contracts-finder` and `ted`. |
| `keywords` | empty | Keep notices whose title, description or buyer contains any of these phrases. |
| `publishedFrom` | 7 days ago | First publication date to include (`YYYY-MM-DD`, UTC). |
| `publishedTo` | today | Last publication date to include. |
| `cpvCodes` | empty | Keep notices with a matching CPV code. A prefix works too: `72` covers all IT services. |
| `minimumValue` | `0` | Keep notices with an estimated value at or above this amount. Needs `valueCurrency`. |
| `valueCurrency` | empty | Three-letter currency for `minimumValue`, such as `GBP` or `EUR`. There is no conversion. |
| `maxResults` | `100` | Stop after this many notices (up to 10,000). |

Filters run before anything is saved, so you only pay for the notices you keep.

## Output

One row per notice. Example from TED (long text shortened here):

```json
{
  "recordType": "notice",
  "source": "ted",
  "noticeId": "670714-2026",
  "title": "Romania – Medical equipments – Furnizare echipamente medicale pentru tratarea pacienților critici cardiaci …",
  "buyerName": "JUDETUL CARAS-SEVERIN",
  "buyerCountry": "ROU",
  "noticeType": "cn-standard",
  "publishedAt": "2026-09-30",
  "deadline": "2026-10-15T12:00:00Z",
  "estimatedValue": 3243807.59,
  "currency": "RON",
  "cpvCodes": ["33100000", "79632000"],
  "procedureType": "open",
  "officialUrl": "https://ted.europa.eu/en/notice/-/detail/670714-2026",
  "licenseUrl": "https://ted.europa.eu/en/legal-notice"
}
```

Rows also carry the full `description`, the source's own IDs (`sourceId`, `ocid`), every published deadline, the raw
deadline text and an `attribution` line.

A few things to know:

- Each row is a notice. One procurement can have several notices over time (the call for tender, changes, the award),
  and UK notices above the threshold often appear in both Find a Tender and Contracts Finder with different IDs.
- `estimatedValue` is the estimate published in the notice. Award amounts are not mixed in, and nothing is guessed, so
  many rows have no value.
- Country codes are kept as each source writes them (Find a Tender uses `GB`, TED uses three letters such as `ROU`).
- TED publication dates are day-only, so `publishedAt` has no time for TED rows.
- Contact-point fields are left out, and email addresses and phone numbers inside the text are masked.

## Pricing

$3.00 per 1,000 notices on the Free plan, $2.70 on Starter, $2.30 on Scale and $1.90 on Business. Filtered-out
notices and duplicates are free, and there is no start fee.

## FAQ

**How fresh is the data?** Each run reads the official APIs live, so new notices show up as soon as the source
publishes them.

**Can I run it every morning?** Yes. Schedule it in Apify with `publishedFrom` left empty, or set it to yesterday, and
send the results to Google Sheets, Slack or email with an integration.

**Do you cover Australia or the US?** Not yet. Only the three sources above.

**Can I reuse the data?** UK notices are published under the Open Government Licence v3.0, and each UK row carries the
required attribution. TED notices can be reused under the EU's legal notice for TED. This actor is not affiliated with
the UK government or the Publications Office of the EU.

## Responsible use

The actor uses only the documented public APIs, sends one request at a time, honours `Retry-After` and stops when a
source refuses access.
