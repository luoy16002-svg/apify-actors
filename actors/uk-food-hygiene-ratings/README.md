# UK Food Hygiene Ratings - FSA Business Data

Export food-business ratings from the Food Standards Agency's public API. Search by business name, town, address, postcode, local authority or business type, and download a flat dataset in JSON, CSV or Excel.

Use it to maintain restaurant directories, check supplier records, compare branches and prepare hospitality market research. Each result includes the inspection date, source extraction timestamp and a link to the original business record.

## Start a run

The default input searches for Pret A Manger in London and returns up to 20 businesses. Click **Start** without changing the input to try it.

```json
{
  "name": "Pret A Manger",
  "address": "London",
  "maxItems": 20,
  "proxyConfiguration": { "useApifyProxy": false }
}
```

Clear `name` or `address` with an empty string to remove that filter. A supplied `localAuthorityId` or `businessTypeId` is combined with the other filters.

## Input

| Field | Default | Meaning |
| --- | --- | --- |
| `name` | `Pret A Manger` | Business-name search. Empty means any name. |
| `address` | `London` | Town, address or postcode search. Empty means any area. |
| `localAuthorityId` | `0` | Optional FSA authority ID; zero disables this filter. This differs from an authority's published code. |
| `businessTypeId` | `0` | Optional FSA business-type ID. Restaurant/Cafe/Canteen is `1`. |
| `maxItems` | `20` | Maximum unique output records, 1–10,000. |
| `pageSize` | `100` | Records per source request, 1–100; also capped by `maxItems`. |
| `maxPages` | `100` | Maximum source pages, 1–500. May return fewer than `maxItems`. |
| `requestDelaySeconds` | `1.2` | Minimum request interval, 1–60 seconds. |
| `proxyConfiguration` | Proxy off | Optional Apify/custom proxy. A proxy is not required by the source. |

Authority and business-type identifiers are listed in the [official API index](https://api.ratings.food.gov.uk/Help/Index/). Searches use the FSA's own matching behavior; an address term is not a geographic boundary.

## Output

One row represents one establishment, identified by the string `fhrsId`. Optional unavailable fields are `null`. Ratings stay strings so values such as `Pass`, `Exempt` and `AwaitingInspection` retain their meaning. Scores and coordinates are numeric; zero scores are preserved. The dataset contains no email or telephone fields.

The following is one complete record from the small live test. It is a dated example, not a statement of the business's current rating. The full three-record sample is in `sample-output.json`.

```json
{
  "fhrsId": "902473",
  "businessName": "Pret A Manger",
  "businessType": "Takeaway/sandwich shop",
  "businessTypeId": 7844,
  "address": "London City Airport, London",
  "postcode": "E16 2PX",
  "rating": "4",
  "ratingDate": "2026-03-24",
  "ratingKey": "fhrs_4_en-gb",
  "schemeType": "FHRS",
  "newRatingPending": false,
  "hygieneScore": 10,
  "structuralScore": 5,
  "managementScore": 5,
  "localAuthorityName": "City of London Corporation",
  "localAuthorityCode": "508",
  "latitude": null,
  "longitude": null,
  "sourceUrl": "https://ratings.food.gov.uk/business/902473",
  "sourceExtractedAt": "2026-09-28T23:50:27.8192558+01:00",
  "fetchedAt": "2026-09-28T22:50:30Z",
  "dataSource": "Food Standards Agency",
  "licenseUrl": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
}
```

## Pricing

**Publisher configuration pending.** Suggested launch price: **$0.80 per 1,000 saved businesses**, plus a **$0.00005 run-start event** at the default memory setting. Final prices will be shown in the Store pricing tab before a run.

One saved unique establishment is one billable result. Duplicate records are discarded before saving. A 100-result run would have a proposed event price of $0.08005. The source data is free; the charge is for running this extraction and normalization service. Previously saved results can remain billable if a later request fails.

## FAQ and limitations

**Do I need an FSA account or API key?** No. The [official API](https://api.ratings.food.gov.uk/help) currently provides access without registration.

**Does a rating describe the business today?** It describes the recorded inspection. Keep `ratingDate`, `sourceExtractedAt` and `fetchedAt` with downstream copies, and consult `sourceUrl` for current information.

**Why are some ratings text rather than numbers?** The API includes different schemes and non-numeric statuses. Read `schemeType` and `rating` together; do not compare an FHIS label numerically with an FHRS rating.

**Why are fewer rows returned?** The search may have fewer matches, `maxPages` or the Apify spending limit may be reached, or malformed source records may be skipped. `RUN_STATS` in the key-value store records counts and the stopping reason. A changed response format or repeated page fails visibly rather than pretending the result is complete.

**Can I export the whole country every day?** This actor is for bounded searches. The FSA recommends its [nightly open-data files](https://api.ratings.food.gov.uk/Help/BestPractices) for regular full downloads. This actor uses one request at a time and pages of at most 100. Offset pagination over a changing source cannot guarantee a complete point-in-time snapshot.

**Does it track changes between runs?** Each run is a fresh snapshot. Join successive exports on `fhrsId` in your own workflow. Deduplication applies within one uninterrupted run; automatic resume after a restart is not provided.

## Responsible use and attribution

Contains Food Standards Agency information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). Preserve source attribution and dates when sharing data. This actor is independent of the FSA and uses no FSA logos or rating imagery. Follow the [FSA reuse terms](https://www.food.gov.uk/terms-and-conditions).

Use business records responsibly. Do not infer or recover withheld addresses or personal contact information. Robots.txt is checked at runtime; denied paths, ambiguous policies and access failures stop the run. Retries are limited to temporary errors. Proxy settings do not change these rules.

## Local development

Requires Python 3.13. Install `requirements-dev.txt` in a virtual environment, then run `python -m pytest -q` and `python -m src --input test-input.json` from this actor directory. Local SDK storage stays in the ignored `storage/` directory. See `TESTING.md` for the recorded commands and results.
