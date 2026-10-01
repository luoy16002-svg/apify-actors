# UK Food Hygiene Ratings - FSA Business Data

Look up official food hygiene ratings for UK restaurants, cafes, takeaways, shops and other food businesses. Search
by business name, town, address or postcode, council or business type, and download the results as JSON, CSV or
Excel.

Handy for restaurant directories and review sites, checking suppliers, comparing branches of a chain, or local
market research. Every row carries the inspection date and a link to the business's page on the FSA ratings site.
Data comes from the Food Standards Agency's public ratings API.

## Quick start

```json
{
  "name": "Pret A Manger",
  "address": "London",
  "maxItems": 100
}
```

Leave `name` empty to get every business in an area, or leave `address` empty to search a name nationwide.

## Input

| Field | Default | What it does |
| --- | --- | --- |
| `name` | `Pret A Manger` | Business name to search. Empty means any name. |
| `address` | `London` | Town, address or postcode. Empty means anywhere. |
| `localAuthorityId` | `0` | Optional council filter using the FSA's authority ID (0 = off). |
| `businessTypeId` | `0` | Optional business type filter, e.g. `1` for Restaurant/Cafe/Canteen (0 = off). |
| `maxItems` | `20` | Stop after this many businesses (up to 10,000). |
| `proxyConfiguration` | off | Not needed. |

Council and business type IDs are listed in the [FSA API reference](https://api.ratings.food.gov.uk/Help/Index/).
The address search uses the FSA's own matching, so it is a text match rather than an exact map boundary.

## Output

One row per business. Example:

```json
{
  "fhrsId": "902473",
  "businessName": "Pret A Manger",
  "businessType": "Takeaway/sandwich shop",
  "address": "London City Airport, London",
  "postcode": "E16 2PX",
  "rating": "4",
  "ratingDate": "2026-03-24",
  "schemeType": "FHRS",
  "newRatingPending": false,
  "hygieneScore": 10,
  "structuralScore": 5,
  "managementScore": 5,
  "localAuthorityName": "City of London Corporation",
  "latitude": null,
  "longitude": null,
  "sourceUrl": "https://ratings.food.gov.uk/business/902473",
  "fetchedAt": "2026-09-28T22:50:30Z",
  "dataSource": "Food Standards Agency"
}
```

Ratings are kept as text because Scotland's scheme uses words such as `Pass` and `Improvement Required`, and some
businesses show `Exempt` or `AwaitingInspection`. For the sub-scores, lower is better (0 is the best).

## Pricing

$1.00 per 1,000 businesses on the Free plan, $0.90 on Starter, $0.80 on Scale and $0.70 on Business. Duplicates
are free, and there is no start fee.

## FAQ

**Is this the current rating?** It is the rating the FSA publishes at the time of your run, with its inspection
date. Ratings change after new inspections, so re-run for fresh data.

**Why are some coordinates empty?** The FSA doesn't publish a location for every business.

**Can I use the data commercially?** FSA data is published under the Open Government Licence v3.0. Credit the Food
Standards Agency and keep the source links. This actor is not affiliated with the FSA.

## Responsible use

The actor sends one request at a time, checks robots.txt and backs off on errors.
