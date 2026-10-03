# Career Page Jobs Scraper - Greenhouse, Lever, Ashby, Workable, Recruitee, Personio

Get every open job from a list of companies in one table, whichever applicant tracking system each company uses. Paste
career-page links such as `boards.greenhouse.io/figma` or `jobs.ashbyhq.com/linear`, or just a company's own careers
page, and the actor finds the right job board and returns clean, comparable rows.

Useful for job boards and newsletters, sales teams watching who is hiring, recruiters tracking competitors, and anyone
who wants job data without running six different scrapers.

## Supported systems

| System | Example link |
| --- | --- |
| Greenhouse | `https://boards.greenhouse.io/figma` or `https://job-boards.greenhouse.io/figma` |
| Lever | `https://jobs.lever.co/spotify` (EU boards too) |
| Ashby | `https://jobs.ashbyhq.com/linear` |
| Workable | `https://apply.workable.com/<company>` |
| Recruitee | `https://<company>.recruitee.com` |
| Personio | `https://<company>.jobs.personio.de` or `.com` |

You can also give a company's own careers page (`https://www.example.com/careers`). The actor opens it once, looks for a
link or embed from one of the systems above and reads that board. SmartRecruiters is not supported: its robots.txt asks
crawlers to stay away, and the actor respects that.

## Quick start

```json
{
  "companies": [
    "https://jobs.ashbyhq.com/linear",
    "https://boards.greenhouse.io/figma",
    "https://jobs.lever.co/spotify"
  ],
  "titleContains": "engineer"
}
```

## Input

| Field | Default | What it does |
| --- | --- | --- |
| `companies` | required | Up to 50 entries: career-board links, careers pages, or objects like `{"slug": "figma", "ats": "greenhouse"}`. |
| `titleContains` | empty | Keep jobs whose title contains this text (not case sensitive). |
| `locationContains` | empty | Keep jobs whose location contains this text. |
| `department` | empty | Keep jobs whose department contains this text. |
| `postedAfter` | empty | Keep jobs posted after this date, such as `2026-09-01`. Jobs without a date are left out. |
| `remoteOnly` | `false` | Keep only jobs the board marks as remote. |
| `maxJobsPerCompany` | `1000` | Cap per company. |
| `maxItems` | `10000` | Cap for the whole run. |

Filters run before anything is saved, so you only pay for the jobs you keep.

## Output

One row per job. The field names are the same for every system:

```json
{
  "company": "linear",
  "ats": "ashby",
  "jobId": "d3bc1ced-3ce4-4086-a050-555055dbb1ff",
  "title": "Senior / Staff Fullstack Engineer",
  "department": "Product",
  "team": "Engineering",
  "location": "Europe",
  "country": "European Union",
  "isRemote": true,
  "workplaceType": "remote",
  "employmentType": "FullTime",
  "createdAt": "2021-04-27T20:13:45.158000Z",
  "sourceUrl": "https://jobs.ashbyhq.com/linear/d3bc1ced-3ce4-4086-a050-555055dbb1ff",
  "applyUrl": "https://jobs.ashbyhq.com/linear/d3bc1ced-3ce4-4086-a050-555055dbb1ff/application",
  "description": "At Linear, we're building the product development system for teams and agents. ...",
  "salaryMin": null,
  "salaryMax": null,
  "salaryCurrency": null,
  "salaryInterval": null
}
```

Descriptions are plain text with paragraphs kept. Salary fields are filled only when the company publishes a structured
pay range (common on Ashby and Lever); the actor never guesses pay from the description text. Each row also carries a
stable `sourceId`, so you can spot new jobs between runs.

Companies that could not be read (a wrong slug, a removed board, a careers page with no supported system) are listed in
the run's `OUTPUT` record with the reason. They never appear as dataset rows and cost nothing.

## Pricing

$1.50 per 1,000 jobs on the Free plan, $1.35 on Starter, $1.15 on Scale and $0.95 on Business. No start fee; filtered-out
and duplicate jobs are free.

## FAQ

**Is this the same data as the careers page?** Yes. Every system here has a public job feed that powers the company's own
careers page, and the actor reads that feed. In our checks the counts matched the careers pages.

**How fast is it?** Requests to each site are spaced out (about one per second) to stay polite. A few hundred jobs take
well under a minute.

**Can I run it every day?** Yes. Schedule it and compare `sourceId` values to find new and closed jobs.

**Does it log in anywhere?** No. Only public job boards are read.
