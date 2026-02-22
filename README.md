# Job Matcher Plugin v2.0.0

A Claude Code plugin that matches your CV/Resume and Career Brief to current job advertisements. Uses an **API-first architecture** — querying ATS and job APIs directly — to guarantee that every returned job is genuinely open.

## Why API-First?

The v1 approach used WebSearch to find jobs across aggregator sites (Glassdoor, ClimateBase, ClimateTechList). Two problems:

1. **Stale listings.** Aggregators cache expired jobs. The first two results in v1 testing were already closed.
2. **Agent delegation fails.** `WebSearch`/`WebFetch` permissions don't propagate to background agents in Claude Code, so parallel search agents silently failed.

The v2 fix:

- **ATS APIs** (Greenhouse, Lever, Workable, Ashby) only return active listings — guaranteed open by definition
- **Free job APIs** (Remotive, RemoteOK, Jobicy, Himalayas, The Muse) also serve only active listings
- **All agents use `Bash`/`curl`** instead of WebSearch — Bash permissions propagate correctly

---

## Installation

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed
- `python3` (3.9+, standard library only — no pip dependencies)
- `curl`

### Option A: Install via marketplace (recommended)

From within Claude Code, add this repo as a plugin marketplace and install:

```
> /plugin marketplace add rabourn/job-matcher
> /plugin install job-matcher@job-matcher
```

That's it. The plugin is now available in all your Claude Code sessions.

### Option B: Clone and load locally

If you prefer to run from source (or want to customise the target companies list):

1. Clone this repo:
   ```bash
   git clone https://github.com/rabourn/job-matcher.git
   cd job-matcher
   ```

2. Start Claude Code with the plugin loaded:
   ```bash
   claude --plugin-dir .
   ```

To install it permanently from a local clone (so you don't need `--plugin-dir` every time):
```
> /plugin install /path/to/job-matcher
```

### Running it

Once installed, start a job search with:

```
> /match-jobs
```

Or just say "find jobs for me", "match my CV", "job search", etc.

The plugin will ask for your CV/Resume, then either collect your Career Brief or walk you through a guided interview to build one. After that it searches all APIs in parallel and generates a detailed match report.

### Customising Target Companies

The plugin ships with 12 example companies across several sectors. You'll want to customise this list for your own search.

Create a **`data/target-companies.local.json`** file with your personal company list. The plugin checks for this file first and falls back to the default `target-companies.json` if it doesn't exist. Local files are gitignored, so your personal list stays out of version control.

```bash
# Copy the example as a starting point
cp data/target-companies.json data/target-companies.local.json
# Then edit data/target-companies.local.json to add your target companies
```

See [Adding a Company](#adding-a-company) below for the format.

---

## Architecture

```
User provides CV + Career Brief
         │
         ▼
  ┌─────────────┐
  │  Phase 1-2  │  Collect inputs, build Candidate Profile
  │  (main ctx) │
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │   Phase 3   │  Map profile → sectors, keywords, seniority, target companies
  │  (main ctx) │
  └──────┬──────┘
         │
         ▼
  ┌──────────────────────────────────────────────────────────┐
  │                    Phase 4: Parallel Search               │
  │                                                          │
  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
  │  │ ATS Scanner  │  │ API Searcher │  │ RSS Scanner  │   │
  │  │   (agent)    │  │   (agent)    │  │   (agent)    │   │
  │  │              │  │              │  │              │   │
  │  │ Greenhouse   │  │ Remotive     │  │ WeWorkRemote │   │
  │  │ Lever        │  │ RemoteOK     │  │ Remotive RSS │   │
  │  │ Workable     │  │ Jobicy       │  │ Code4Lib     │   │
  │  │ Ashby        │  │ Himalayas    │  │              │   │
  │  │              │  │ The Muse     │  │              │   │
  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
  │         │                 │                  │           │
  │         ▼                 ▼                  ▼           │
  │  ats-scan-       api-search-        rss-scan-           │
  │  results.json    results.json       results.json        │
  │                                                          │
  │  + WebSearch in main context for niche boards            │
  │    (Devex, ReliefWeb, Idealist, etc.)                    │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    Phase 5      │  Merge, deduplicate, verify URLs
                    │   (main ctx)    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    Phase 6      │  Score (0-100) and rank into tiers
                    │   (main ctx)    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    Phase 7      │  Generate job-match-report.md
                    │   (main ctx)    │
                    └─────────────────┘
```

### Data Pipeline (per source)

Every API result flows through the same processing pipeline:

```
API response (JSON)
    │
    ▼
normalize-jobs.py --source {name}    → Unified job schema
    │
    ▼
filter-jobs.py --keywords "..." --seniority "..."    → Scored + filtered
    │
    ▼
deduplicate-jobs.py    → Cross-source dedup (ATS preferred over API preferred over RSS)
    │
    ▼
verify-url.sh    → Only for non-ATS sources (ATS = guaranteed active)
```

---

## Directory Structure

```
job-matcher/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Marketplace index for /plugin install
│
├── commands/
│   └── match-jobs.md            # /match-jobs slash command
│
├── skills/
│   └── match-jobs/SKILL.md      # Main orchestrator skill (7 phases)
│
├── agents/
│   ├── ats-scanner.md           # Scans ATS APIs for target companies
│   ├── api-searcher.md          # Queries 5 free job APIs
│   └── rss-scanner.md           # Fetches + parses RSS/Atom feeds
│
├── scripts/
│   │
│   │  # ATS scanners (guaranteed active listings)
│   ├── scan-greenhouse.sh       # boards-api.greenhouse.io
│   ├── scan-lever.sh            # api.lever.co
│   ├── scan-workable.sh         # apply.workable.com (POST)
│   ├── scan-ashby.sh            # api.ashbyhq.com
│   │
│   │  # Free job API searchers
│   ├── search-remotive.sh       # remotive.com/api (~20 listings)
│   ├── search-remoteok.sh       # remoteok.com/api (needs User-Agent)
│   ├── search-jobicy.sh         # jobicy.com/api (has salary data)
│   ├── search-himalayas.sh      # himalayas.app/jobs/api (search broken)
│   ├── search-themuse.sh        # themuse.com/api (best filtering)
│   │
│   │  # RSS + verification
│   ├── fetch-rss.sh             # Any RSS/Atom feed → JSON
│   ├── verify-url.sh            # Check if a job URL is still live
│   │
│   │  # Data processing (Python, stdlib only)
│   ├── normalize-jobs.py        # Any API output → unified JSON schema
│   ├── filter-jobs.py           # Keyword/seniority scoring + filtering
│   └── deduplicate-jobs.py      # Fuzzy dedup, prefers ATS sources
│
├── data/
│   ├── target-companies.json    # Example companies → ATS platform + slug
│   ├── sector-keywords.json     # 6 sectors → keyword sets
│   │
│   │  # Generated at runtime (by agents)
│   ├── ats-scan-results.json
│   ├── api-search-results.json
│   ├── rss-scan-results.json
│   └── merged-results.json
│
├── test/
│   ├── sample-cv.md             # Example CV (Sarah Chen, data analyst)
│   └── sample-career-brief.md   # Example Career Brief (matches sample CV)
│
└── job-match-report.md          # Generated report output
```

---

## Components

### Skill: `match-jobs`

The main orchestrator. Invoked via `/match-jobs` or trigger phrases ("find jobs for me", "match my CV", etc.).

**Seven phases:**

| Phase | What happens | Where |
|-------|-------------|-------|
| 1. Collect Inputs | Get CV + Career Brief (or build one via guided interview) | Main context |
| 2. Profile Analysis | Extract skills, experience, goals, preferences | Main context |
| 3. Configure Search | Map profile → sectors, keywords, seniority, companies | Main context |
| 4. Parallel Search | Launch 3 agents + run WebSearch for niche boards | 3 agents + main |
| 5. Merge & Verify | Combine results, dedup, verify non-ATS URLs | Main context |
| 6. Score & Rank | Calculate match scores (0-100), assign tiers | Main context |
| 7. Generate Report | Write `job-match-report.md` with full analysis | Main context |

### Agents

All three agents use `tools: [Bash, Read, Write]` — no WebSearch/WebFetch. They communicate via JSON files in `data/`.

| Agent | Model | Purpose | Output file |
|-------|-------|---------|-------------|
| `ats-scanner` | sonnet | Scan target companies' ATS APIs | `data/ats-scan-results.json` |
| `api-searcher` | sonnet | Query 5 free job APIs | `data/api-search-results.json` |
| `rss-scanner` | sonnet | Fetch job board RSS/Atom feeds | `data/rss-scan-results.json` |

### Scripts

#### ATS Scanners

Each queries a public, no-auth ATS API. Returns only active listings (guaranteed).

| Script | API endpoint | Method | Auth |
|--------|-------------|--------|------|
| `scan-greenhouse.sh SLUG [--content]` | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | GET | None |
| `scan-lever.sh SLUG` | `api.lever.co/v0/postings/{slug}` | GET | None |
| `scan-workable.sh SLUG` | `apply.workable.com/api/v1/widget/accounts/{slug}` | POST | None |
| `scan-ashby.sh SLUG` | `api.ashbyhq.com/posting-api/job-board/{slug}` | GET | None |

#### Free Job API Searchers

| Script | API | Key features | Quirks |
|--------|-----|-------------|--------|
| `search-remotive.sh [--category CAT]` | Remotive | Category filter | Only ~20 listings total. No keyword search. |
| `search-remoteok.sh [--tag TAG]` | RemoteOK | Tag filter, salary data | Requires User-Agent header. Element[0] is metadata. |
| `search-jobicy.sh [--count N] [--tag TAG] [--geo GEO]` | Jobicy | Tag, geo, salary data | Best salary data. `jobIndustry` can be list or string. |
| `search-himalayas.sh [--limit N]` | Himalayas | Salary data | **Search is broken** — fetch all + filter locally. |
| `search-themuse.sh [--level LVL] [--category CAT] [--location LOC]` | The Muse | Level, category, location | Best server-side filtering. 500 req/hr free tier. |

#### Data Processing (Python)

| Script | Input | Output | Key behaviour |
|--------|-------|--------|--------------|
| `normalize-jobs.py --source NAME [--company NAME]` | stdin JSON | stdout JSON | Converts any API format → unified schema. ATS sources set `verification_status: GUARANTEED`. |
| `filter-jobs.py --keywords "..." [--seniority "..."] [--remote-only] [--exclude-keywords "..."]` | stdin JSON | stdout JSON | Title matches weighted 3x. Adds `preliminary_relevance_score`. |
| `deduplicate-jobs.py` | stdin JSON | stdout JSON | Fuzzy match on (company, title). Source priority: ATS > API > RSS. Stats to stderr. |

#### RSS & Verification

| Script | Purpose |
|--------|---------|
| `fetch-rss.sh FEED_URL` | Fetch RSS/Atom feed → JSON. Handles both formats. Extracts company from "Title at Company" pattern. |
| `verify-url.sh URL` | Check if URL is live. Returns `{status: VERIFIED\|EXPIRED\|UNVERIFIABLE, http_code, reason}`. Checks HTTP status + page content for "no longer available" phrases + redirect to generic careers page. |

---

## Unified Job Schema

Every job, regardless of source, is normalised to this structure:

```json
{
  "id": "12-char hash",
  "source": "greenhouse|lever|workable|ashby|remotive|remoteok|jobicy|himalayas|themuse|rss",
  "source_id": "original ID from API",
  "title": "Job Title",
  "company": "Company Name",
  "location": "City, Country or Remote",
  "remote": true,
  "work_mode": "remote|hybrid|onsite",
  "employment_type": "Full-time|Contract|etc.",
  "seniority": "junior|mid|senior|director|executive",
  "salary_min": 120000,
  "salary_max": 180000,
  "salary_currency": "USD",
  "posted_date": "2025-02-15",
  "description_text": "Plain text (HTML stripped)",
  "url": "https://...",
  "apply_url": "https://...",
  "departments": ["Product", "Design"],
  "tags": ["remote", "fintech"],
  "verification_status": "GUARANTEED|API_ACTIVE|UNVERIFIED"
}
```

### Verification Status

| Status | Meaning | Sources | Action needed |
|--------|---------|---------|--------------|
| `GUARANTEED` | Active by definition — ATS API only returns open jobs | Greenhouse, Lever, Workable, Ashby | None |
| `API_ACTIVE` | From active listing API — reliably current | Remotive, RemoteOK, Jobicy, Himalayas, The Muse | Optional verify |
| `UNVERIFIED` | Freshness unknown — needs URL check | RSS feeds, WebSearch | Run `verify-url.sh` |

---

## Scoring

Match scores (0-100) combine six weighted dimensions:

| Dimension | Max points | What it measures |
|-----------|-----------|-----------------|
| Skills alignment | 30 | % of required skills the candidate has |
| Seniority fit | 20 | Role level vs. candidate's current/target level |
| Sector relevance | 20 | Industry alignment with background and goals |
| Work mode match | 15 | Remote/hybrid/onsite alignment |
| Culture/values | 10 | Mission alignment, org size, signals |
| Recency | 5 | Posted within last 30 days = full marks |

**Tiers:**
- **Tier 1** (80-100%): Strong fit right now
- **Tier 2** (60-79%): Good fit with some stretch
- **Tier 3** (40-59%): Growth opportunity aligned with trajectory

---

## Target Companies

`data/target-companies.json` ships with 12 example companies to get you started. All slugs have been verified to return data. You should customise this list for your own job search.

| Sector | Examples | ATS platforms |
|--------|---------|--------------|
| Finance | Stripe, Ramp | Greenhouse, Ashby |
| Health Tech | Flatiron Health, Zocdoc | Greenhouse |
| Climate/AgTech | Planet Labs, Watershed | Greenhouse, Ashby |
| Tech/ML | Anthropic, GitLab, Notion, Figma | Greenhouse, Ashby |
| GLAM | Wikimedia, Khan Academy | Greenhouse |

### Adding a Company

1. Find the company's ATS platform and slug:
   - **Greenhouse**: Check `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
   - **Lever**: Check `https://api.lever.co/v0/postings/{slug}`
   - **Workable**: Check `https://apply.workable.com/api/v1/widget/accounts/{slug}`
   - **Ashby**: Check `https://api.ashbyhq.com/posting-api/job-board/{slug}`

2. If it returns a 200 with jobs, add it to `data/target-companies.json`:
   ```json
   {
     "name": "Company Name",
     "ats": "greenhouse",
     "slug": "company-slug",
     "sectors": ["finance", "design_strategy"],
     "notes": "What the company does"
   }
   ```

### Finding Slugs

The slug is usually the company's subdomain on the ATS platform:
- Greenhouse: `https://job-boards.greenhouse.io/{SLUG}/` or `https://boards.greenhouse.io/{SLUG}`
- Lever: `https://jobs.lever.co/{SLUG}/`
- Ashby: `https://jobs.ashbyhq.com/{SLUG}`
- Workable: `https://apply.workable.com/{SLUG}/`

---

## Sector Keywords

`data/sector-keywords.json` defines 6 sectors with keyword sets for filtering:

| Sector | Key title terms | Key description terms |
|--------|----------------|----------------------|
| `climate_agtech` | climate, sustainability, ESG, carbon, agtech | renewable, clean energy, net zero, biodiversity |
| `international_development` | digital, innovation, program | humanitarian, USAID, CGIAR, financial inclusion |
| `glam` | curator, collections, archives, digital | museum, library, IIIF, digital preservation |
| `finance` | fintech, digital banking, payments | neobank, lending, DeFi, mobile money |
| `health_tech` | health, clinical, medical | telehealth, EMR, mHealth, diagnostics |
| `design_strategy` | HCD, service design, design ops | design thinking, UX research, inclusive design |

---

## Usage

### Running the Skill

```
> /match-jobs
```

Or say: "find jobs for me", "match my CV", "job search", etc.

The skill will ask for your CV and Career Brief, then run the full pipeline. If you don't have a Career Brief, it will walk you through a guided interview to build one — asking about your target roles, industries, work preferences, priorities, and dealbreakers, then generating a Career Brief document for your review before starting the search.

### Testing Individual Scripts

```bash
# Test a single ATS scan
bash scripts/scan-greenhouse.sh ideo --content | \
  python3 scripts/normalize-jobs.py --source greenhouse --company "IDEO" | \
  python3 scripts/filter-jobs.py --keywords "product,design,director"

# Test a free API
bash scripts/search-themuse.sh --level "Senior Level" --category "Design and UX" | \
  python3 scripts/normalize-jobs.py --source themuse | \
  python3 scripts/filter-jobs.py --keywords "product,design"

# Test RSS
bash scripts/fetch-rss.sh "https://weworkremotely.com/categories/remote-design-jobs.rss" | \
  python3 scripts/normalize-jobs.py --source rss | \
  python3 scripts/filter-jobs.py --keywords "product,design"

# Verify a URL
bash scripts/verify-url.sh "https://job-boards.greenhouse.io/wikimedia/jobs/7644440"
```

### Full Pipeline Test

```bash
# Scan multiple companies → normalize → filter → dedup
python3 -c "
import subprocess, json, sys

companies = [
    ('greenhouse', 'ideo', 'IDEO'),
    ('greenhouse', 'figma', 'Figma'),
    ('ashby', 'notion', 'Notion'),
]

all_jobs = []
for ats, slug, company in companies:
    scan = subprocess.run(['bash', f'scripts/scan-{ats}.sh', slug, '--content'],
                          capture_output=True, text=True, timeout=30)
    norm = subprocess.run(['python3', 'scripts/normalize-jobs.py', '--source', ats, '--company', company],
                          input=scan.stdout, capture_output=True, text=True)
    filt = subprocess.run(['python3', 'scripts/filter-jobs.py',
                          '--keywords', 'product,design,director,strategy'],
                          input=norm.stdout, capture_output=True, text=True)
    all_jobs.extend(json.loads(filt.stdout))
    print(f'{company}: {len(json.loads(filt.stdout))} matches', file=sys.stderr)

dedup = subprocess.run(['python3', 'scripts/deduplicate-jobs.py'],
                       input=json.dumps(all_jobs), capture_output=True, text=True)
print(f'Total unique: {len(json.loads(dedup.stdout))}', file=sys.stderr)
" 2>&1
```

---

## API Coverage Summary

| Source | Type | Auth | Active guarantee | Salary data | Volume |
|--------|------|------|-----------------|-------------|--------|
| Greenhouse | ATS | None | Yes (GUARANTEED) | Sometimes | Per company |
| Lever | ATS | None | Yes (GUARANTEED) | Rarely | Per company |
| Workable | ATS | None | Yes (GUARANTEED) | Rarely | Per company |
| Ashby | ATS | None | Yes (GUARANTEED) | Often | Per company |
| Remotive | API | None | Yes (API_ACTIVE) | No | ~20 total |
| RemoteOK | API | None | Yes (API_ACTIVE) | Sometimes | ~500+ |
| Jobicy | API | None | Yes (API_ACTIVE) | Often | ~1000+ |
| Himalayas | API | None | Yes (API_ACTIVE) | Sometimes | ~1000+ |
| The Muse | API | None | Yes (API_ACTIVE) | No | ~500+ |
| RSS feeds | RSS | None | No (UNVERIFIED) | No | ~50-100 per feed |
| WebSearch | Search | N/A | No (UNVERIFIED) | No | Variable |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| ATS-first, not WebSearch-first | ATS APIs guarantee active listings. WebSearch surfaces stale aggregator caches. |
| Agents use Bash/curl, not WebSearch | Bash permissions propagate to background agents; WebSearch doesn't. |
| 3 specialised agents, not 1 general agent | Each has different failure modes; all run in parallel for speed. |
| Client-side filtering via Python | Most free APIs have broken or missing server-side search. Local filtering is consistent. |
| Target companies as a data file | The ATS strategy requires knowing which companies to check. A curated JSON is maintainable and extensible. |
| WebSearch retained for niche boards only | Devex, ReliefWeb, museum associations have no APIs. WebSearch in main context fills this gap. |
| Python stdlib only | No pip dependencies means the plugin works out of the box. |

---

## Future Improvements

### Authenticated APIs (optional)

These require free API key registration but expand coverage:

- **USAJobs** (`scripts/search-usajobs.sh`) — Covers Smithsonian, Library of Congress, USAID, EPA. Valuable for GLAM + climate + development sectors.
- **Adzuna** (`scripts/search-adzuna.sh`) — 12 countries, has `max_days_old` freshness filter. Good for regional search.

### Expanding Target Companies

The example list of 12 companies is just a starting point. To find more:

```bash
# Test if a company uses Greenhouse
curl -s "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('jobs',[])))"

# Test Ashby
curl -s "https://api.ashbyhq.com/posting-api/job-board/{slug}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('jobs',[])))"
```

Tips:
- Most tech startups and mid-size companies use Greenhouse or Ashby
- Larger companies often use Workday or custom portals (not supported by ATS scanning, but covered by free API and WebSearch phases)
- Non-profits and NGOs vary — some use Greenhouse, many use custom portals
