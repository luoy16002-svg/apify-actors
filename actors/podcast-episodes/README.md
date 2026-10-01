# Podcast Episodes Scraper - RSS Feeds and Apple Podcasts

Turn podcasts into a clean episode table. Paste Apple Podcasts links or IDs, or RSS feed URLs, and get every episode's
title, publish date, duration, audio file link, episode page, season and episode numbers, explicit flag and a
plain-text description, plus the show's details on each row.

Handy for tracking new episodes from a list of shows, building a podcast directory or newsletter, researching guests
and topics, or feeding audio links into a transcription pipeline.

## Quick start

```json
{
  "shows": ["https://podcasts.apple.com/us/podcast/houston-we-have-a-podcast/id1262594123"],
  "maxEpisodesPerShow": 50
}
```

An Apple Podcasts link or its numeric ID (`1262594123`) both work. If you already have the RSS feed, put it in
`feedUrls` instead.

## Input

| Field | Default | What it does |
| --- | --- | --- |
| `shows` | empty | Apple Podcasts show links or IDs. Each one is resolved to the show's public RSS feed. |
| `feedUrls` | empty | Public podcast RSS feed URLs. |
| `country` | `us` | Apple storefront used to look up shows. |
| `maxShows` | `5` | How many shows to read in one run (up to 50). |
| `maxEpisodesPerShow` | `20` | Episodes to keep per show, in the order the feed lists them, usually newest first (up to 1,000). |
| `publishedAfter` | empty | Keep only episodes published after this date, such as `2026-09-01`. |

Give at least one show or feed. Episodes with no date are skipped when `publishedAfter` is set.

## Output

One row per episode. Example:

```json
{
  "showTitle": "Houston We Have a Podcast",
  "showId": "1262594123",
  "feedUrl": "https://feeds.megaphone.fm/NATIONALAERONAUTICSANDSPACEADMINISTRATION1776343825",
  "showLanguage": "en-US",
  "showUrl": "https://www.nasa.gov/podcasts/houston-we-have-a-podcast/",
  "showGenres": ["Science", "Podcasts"],
  "episodeTitle": "Crew-13",
  "guid": "ca6e1f66-b8e5-11f1-a633-7f4c8f342395",
  "publishedAt": "2026-09-25T13:36:00Z",
  "durationSeconds": 3765,
  "audioUrl": "https://traffic.megaphone.fm/NATIONALAERONAUTICSANDSPACEADMINISTRATION2863054701.mp3",
  "episodeUrl": "https://www.nasa.gov/podcasts/houston-we-have-a-podcast/crew-13/",
  "description": "NASA’s SpaceX Crew-13 members discuss their journeys to becoming astronauts and their upcoming mission to the International Space Station. Episode 438",
  "seasonNumber": 1,
  "episodeNumber": 438,
  "explicit": false
}
```

Rows also include the show's author, description and explicit flag, and a stable `episodeKey` you can use to spot
new episodes between runs. Durations are converted to seconds whatever format the feed uses, and HTML is stripped from
descriptions.

## Pricing

$2.00 per 1,000 episodes on the Free plan, $1.80 on Starter, $1.50 on Scale and $1.20 on Business. Duplicates and
filtered-out episodes are free, and there is no start fee.

## FAQ

**Does it download the audio?** No. You get the link to each audio file.

**Can I search podcasts by keyword?** Not in this actor. Start from the shows you already know, using their Apple
Podcasts links or RSS feeds.

**Why do I get fewer episodes than the show has?** The actor reads what the feed lists. Most feeds list every
episode, but some publishers keep only the latest ones in the feed.

**Private or premium feeds?** Only public feeds are supported.

**Who owns the content?** Titles, descriptions and audio belong to each publisher. Keep the links and follow the
publisher's terms when you reuse them.

## Responsible use

The actor sends one request every few seconds, checks each feed host's robots.txt first and never downloads audio or
artwork.
