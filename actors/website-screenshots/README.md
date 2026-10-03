# Website Screenshots and PDFs - Full Page, Mobile, No Cookie Banners

Turn a list of URLs into clean screenshots. Full-page or just the visible area, desktop or a real phone viewport, PNG,
JPEG or WebP, and a PDF if you want one. Cookie banners are hidden before the shot, lazy images are scrolled into view
first, and you can capture a single element instead of the whole page.

Good for monitoring how pages look over time, building link previews and thumbnails, archiving pages, QA of
responsive layouts, and reports that need a picture of a page.

## Quick start

```json
{
  "urls": ["https://www.bbc.com/news", "https://github.com/"],
  "viewport": "mobile",
  "format": "webp"
}
```

## Input

| Field | Default | What it does |
| --- | --- | --- |
| `urls` | required | Public pages to capture. Duplicates are removed. |
| `viewport` | `desktop` | `desktop` 1440×900, `laptop` 1280×800, `tablet` 820×1180, `mobile` 390×844 at 3× with a phone user agent, or `custom`. |
| `width`, `height` | empty | Size for the `custom` viewport. |
| `fullPage` | `true` | Capture the whole page height, not just the first screen. |
| `format` | `png` | `png`, `jpeg` or `webp`. |
| `quality` | `85` | JPEG and WebP quality. |
| `pdf` | `false` | Also save the page as a PDF (`pdfFormat` A4 or Letter). |
| `hideCookieBanners` | `true` | Hide common consent pop-ups (OneTrust, Cookiebot, Didomi, Usercentrics and others). Nothing is accepted on your behalf. |
| `scrollPage` | `true` | Scroll down first so lazy-loaded images appear. |
| `elementSelector` | empty | CSS selector; capture only that element. |
| `waitStrategy` | `load` | `load`, `networkidle`, `fixed` (wait `waitDelaySeconds`) or `selector` (wait for `waitSelector`). |
| `darkMode` | `false` | Ask the page for its dark theme. |
| `blockAds` | `false` | Block a short list of ad and analytics domains. |
| `css` | empty | Extra CSS to apply before the shot, for example to hide a chat widget. |
| `timeoutSeconds` | `60` | Time allowed per page. |

## Output

Images and PDFs are saved in the run's key-value store. The dataset has one row per captured page with links to the
files:

```json
{
  "url": "https://example.com/",
  "finalUrl": "https://example.com/",
  "statusCode": 200,
  "title": "Example Domain",
  "viewport": {"width": 1440, "height": 900, "deviceScaleFactor": 1, "preset": "desktop"},
  "fullPage": true,
  "format": "png",
  "width": 1440,
  "height": 900,
  "byteSize": 41040,
  "fileUrl": "https://api.apify.com/v2/key-value-stores/<store>/records/capture-a0f1ed89a1f1e61ad1410eb5.png",
  "pdfUrl": "https://api.apify.com/v2/key-value-stores/<store>/records/capture-a0f1ed89a1f1e61ad1410eb5.pdf",
  "capturedAt": "2026-10-03T05:35:25Z",
  "warnings": []
}
```

Pages that fail (timeouts, blocked by the site, robots.txt disallows, 404) are listed in the `OUTPUT` record with the
reason and are not charged.

## Pricing

$2.50 per 1,000 captured pages on the Free plan, $2.25 on Starter, $1.90 on Scale and $1.50 on Business. A PDF of the same
page is included in that price. Failed pages cost nothing and there is no start fee.

## FAQ

**Does it work on pages behind a login?** No, public pages only.

**Some pages still show a pop-up.** Banners from unusual consent tools can slip through. Use `css` to hide them, for
example `#my-banner { display: none !important; }`.

**Why is a page cut off or blank at the bottom?** Very long pages with infinite scroll never end. Use `fullPage: false`
or an `elementSelector` for those.

**Is robots.txt respected?** Yes. Pages a site asks crawlers not to visit are skipped and reported in `OUTPUT`.
