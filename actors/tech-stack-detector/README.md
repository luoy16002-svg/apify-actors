# Tech Stack Detector - What Is This Website Built With?

Find out which technologies a list of websites use: CMS, e-commerce platform, JavaScript framework, analytics, CDN,
hosting, payment and marketing tools, and thousands more. Paste domains or URLs and get one row per site with the
technologies found, their versions when visible, and a confidence score.

Handy for lead generation (find every Shopify or WordPress site in a list), competitor research, agency audits and
market sizing.

## Quick start

```json
{
  "urls": ["nextjs.org", "wordpress.org", "https://www.python.org/"]
}
```

Bare domains are fine. Up to 100 sites per run.

## Input

| Field | Default | What it does |
| --- | --- | --- |
| `urls` | required | Websites to check. |
| `renderJs` | `false` | Open each site in a real browser to catch tools that only show up in JavaScript. Slower, finds more. |
| `includeCategories` | empty | Return only some categories, such as `["CMS", "Ecommerce", "Analytics"]`. Empty returns everything. |
| `maxConcurrency` | `5` | Sites checked at the same time (2 when rendering). |
| `timeoutSeconds` | `45` | Time allowed per site. |

## Output

One row per site:

```json
{
  "url": "https://nextjs.org/",
  "finalUrl": "https://nextjs.org/",
  "statusCode": 200,
  "status": "ok",
  "frameworks": ["Next.js", "React"],
  "hosting": ["Vercel"],
  "cms": [],
  "ecommerce": [],
  "analytics": [],
  "cdn": [],
  "programmingLanguages": [],
  "technologies": [
    {"name": "Next.js", "version": null, "confidence": 100, "categories": [{"id": 12, "name": "JavaScript frameworks"}],
     "website": "https://nextjs.org", "evidence": ["headers:x-powered-by"]},
    {"name": "Vercel", "version": null, "confidence": 100, "categories": [{"id": 62, "name": "PaaS"}],
     "website": "https://vercel.com", "evidence": ["headers:server", "headers:x-vercel-cache", "headers:x-vercel-id"]}
  ],
  "rendered": false,
  "fetchedAt": "2026-10-03T05:35:20Z"
}
```

The flat fields (`cms`, `ecommerce`, `frameworks`, `analytics`, `cdn`, `hosting`, `programmingLanguages`) make filtering
easy in a spreadsheet. `evidence` tells you why each technology was matched, so you can judge borderline cases yourself.

Sites that could not be checked (down, blocked, robots.txt disallows) are listed in the `OUTPUT` record and are not
charged.

## How it works

The actor fetches each homepage once, follows redirects, and matches the headers, cookies, meta tags, HTML and script URLs
against the open-source WebAppAnalyzer fingerprint database (about 7,600 technologies, GPL-3.0). With `renderJs` it also
checks JavaScript globals in a real browser.

## Pricing

$2.00 per 1,000 sites on the Free plan, $1.80 on Starter, $1.50 on Scale and $1.20 on Business, with or without
rendering. No start fee; failed sites are free.

## FAQ

**How accurate is it?** It finds what a site exposes publicly. Tools that leave no trace in the page (server-side
libraries, back-office software) cannot be detected by anyone from the outside. Turn on `renderJs` for sites built as
single-page apps.

**Why does a site I know uses Shopify show nothing?** Headless shops (a custom front end on top of Shopify) often hide the
platform. The rendered mode catches some of them.

**Is robots.txt respected?** Yes. Only the homepage and its redirects are requested, and sites that disallow crawlers
are skipped.
