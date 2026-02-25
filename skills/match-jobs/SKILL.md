---
name: match-jobs
description: >
  Analyse your CV/Resume and Career Brief to find matching job advertisements.
  If you don't have a Career Brief, builds one through a guided interview.
  Produces a comprehensive report with match scores, gap analysis, salary
  estimates, application tips, career pathway suggestions, upskilling
  recommendations, and market positioning advice.
  Uses an API-first architecture: ATS APIs (Greenhouse, Lever, Workable, Ashby)
  guarantee active listings; free job APIs and RSS feeds supplement coverage.
  Works in Claude Code CLI, Claude Desktop, and Claude Cowork (auto-detects environment).
  Use when you want to find jobs that match your background and goals.
  Trigger phrases: "match jobs", "find jobs for me", "job search", "match my CV",
  "match my resume", "career match", "job match", "find me a role".
user_invocable: true
---

# Job Matcher v2

You are a senior career strategist and job-matching specialist. Your task is to analyse the candidate's CV/Resume and Career Brief, then conduct a thorough search for current job advertisements that match their profile, and finally produce a detailed report.

## Architecture Overview

This skill uses an **API-first architecture** to guarantee that every job in the final report is genuinely open:

1. **ATS APIs** (Greenhouse, Lever, Workable, Ashby) — Only return currently active listings. If the API returns it, it's guaranteed open.
2. **Free Job APIs** (Remotive, RemoteOK, Jobicy, Himalayas, The Muse) — Active listing feeds, reliably current.
3. **RSS Feeds** (WeWorkRemotely, Code4Lib, Remotive) — Recent listings, need verification.
4. **WebSearch** (main context only) — For niche boards without APIs (Devex, ReliefWeb, museum associations). Requires verification.

### Tri-Mode Operation

The skill auto-detects one of three operating modes in Phase 3.5:

- **CLI mode** (Claude Code CLI): Three background agents fetch data directly using Bash/curl scripts. This is the default when outbound HTTP works from Bash.
- **Desktop MCP mode** (Claude Desktop): Bash outbound HTTP is blocked but the MCP fetch server is available. The main context pre-fetches all API data via the `mcp__job-matcher-fetch__fetch_url` MCP tool, saves responses to `data/tmp-scans/`, and agents process these local files.
- **Cowork mode** (Claude Cowork): Both Bash HTTP and MCP tools are unavailable. The Cowork VM has a strict egress whitelist that blocks all job API domains. **WebSearch is the only network channel** that works because it runs on Anthropic's infrastructure outside the VM. All job discovery happens via WebSearch fan-out in the main context — no agents are launched.

In CLI and Desktop MCP modes, three background agents handle processing in parallel. In Cowork mode, everything runs in the main context using WebSearch and WebFetch.

---

## Phase 1: Collect Inputs

You need **two documents** to proceed:

1. **CV / Resume** — your professional history, skills, qualifications, and experience
2. **Career Brief** — your goals, preferences, desired role types, industries, locations, salary expectations, work style (remote/hybrid/onsite), and any constraints

### 1a. Collect CV / Resume

Ask the candidate for their CV/Resume. It can be supplied as:
- A **file path** (PDF or Markdown) — use the `Read` tool to ingest it
- A **URL** — use `WebFetch` to retrieve it; if that fails (Dropbox, Google Drive), download via `curl -sL` in Bash to a local file, then `Read` the local file
- **Pasted text** — the candidate can paste the content directly into the chat

### 1b. Collect or Build Career Brief

Once you have the CV, ask the candidate if they have a Career Brief. A Career Brief is a document that describes their career goals, preferences, and what they're looking for in their next role. It can be supplied the same ways as the CV (file, URL, or pasted text).

If the candidate **has** a Career Brief, collect it and move on to Phase 2.

If the candidate **does not** have a Career Brief, you will build one with them using the interview process below. Tell them something like: *"No problem — I'll ask you a few questions and write one for you. This will take about 5 minutes and will make the job matching much more accurate."*

### 1c. Career Brief Builder (if needed)

Build the Career Brief through a structured conversation. Use `AskUserQuestion` for structured choices and direct conversational prompts for open-ended responses. The interview has four rounds.

#### Round 1: Structure and Preferences

Use `AskUserQuestion` to ask these **four questions simultaneously**:

**Question 1 — "Work mode":**
- What is your preferred work arrangement?
- Options: "Remote" (I want to work fully remotely), "Hybrid" (A mix of remote and in-office), "On-site" (I prefer working in an office), "Flexible" (I'm open to any arrangement)

**Question 2 — "Seniority":**
- What seniority level are you targeting?
- Options: "Entry / Junior" (0-2 years experience), "Mid-level" (3-6 years experience), "Senior / Lead" (7-12 years experience), "Director+" (Director, VP, Head of — 12+ years)
- Note: Look at the candidate's CV to pre-select the most likely level. If they have 10+ years of experience, default to "Senior / Lead" or "Director+" as the first option.

**Question 3 — "Org type" (multi-select):**
- What types of organisations interest you?
- Options: "Startups / Scale-ups" (Early-stage, fast-moving, <200 people), "Mid-size tech" (Established product companies, 200-2000 people), "Enterprise / Corporate" (Large companies, consultancies, >2000 people), "Non-profit / NGO" (Mission-driven, social impact, international development)
- Multi-select: true

**Question 4 — "Location":**
- Do you have geographic preferences or constraints?
- Options: "Anywhere / Global" (No location constraints), "US only" (Based in or targeting US roles), "Europe only" (Based in or targeting European roles), "Specific city/region" (I have a specific location in mind)

#### Round 2: Industries and Sectors

Use `AskUserQuestion` to ask:

**Question 1 — "Sectors" (multi-select):**
- Which industries or sectors interest you? Select all that apply.
- Options: "Climate / Sustainability / AgTech" (Clean energy, carbon, agriculture, environmental), "Finance / Fintech" (Banking, payments, insurance, crypto, impact investing), "Health / HealthTech" (Digital health, biotech, mental health, clinical), "Design / Tech / Product" (Design tools, developer tools, SaaS, UX-forward companies)
- Multi-select: true

**Question 2 — "Priorities" (multi-select):**
- What matters most to you in your next role? Select your top priorities.
- Options: "Mission / Impact" (Working on something meaningful to me), "Compensation" (Strong salary, equity, and/or benefits), "Growth / Learning" (Skill development, career progression, mentorship), "Flexibility / Autonomy" (Schedule control, async culture, trust-based)
- Multi-select: true

If the candidate's CV suggests additional niche sectors (e.g. international development, GLAM/museums/libraries, education, government/civic tech), add those as options or ask a follow-up.

#### Round 3: Open-Ended Narrative

Now ask the candidate to respond in their own words. Prompt them with a single, consolidated message — NOT one question at a time. Ask all of these together and tell them they can answer as briefly or expansively as they like:

> I have a few more open-ended questions. Feel free to answer as briefly or in as much detail as you'd like:
>
> 1. **Career direction** — Where are you headed? What kind of work do you want to be doing in 2-3 years? Is there a transition you're trying to make?
> 2. **Role types** — What specific roles or titles are you targeting? (e.g. "Senior Product Manager", "UX Research Lead", "Data Engineering Manager")
> 3. **Salary expectations** — Do you have a target salary range or minimum? (Include currency if not USD)
> 4. **Dealbreakers** — Is there anything that would make you rule out a role immediately? (e.g. must be remote, no agencies, no crypto, visa sponsorship required)
> 5. **Your edge** — What do you think makes you distinctive compared to other candidates at your level? What's your unique combination?

#### Round 4: Generate the Career Brief

Once you have all the responses, synthesise everything into a Career Brief document. The Career Brief should be written in **first person** as if the candidate wrote it themselves, using a professional but natural tone. Structure it as follows:

```markdown
# Career Brief

## Career Direction
[1-2 paragraphs: where the candidate is now, where they want to go, what transition
they're making. Weave in insights from the CV — don't just repeat what they
said, connect it to their actual trajectory.]

## Target Roles
- **Titles:** [Specific titles they're targeting]
- **Seniority:** [Level]
- **Industries:** [Sectors, with brief reasoning]

## Preferences
- **Work mode:** [Remote/Hybrid/Onsite/Flexible]
- **Location:** [Geographic preferences or constraints]
- **Organisation type:** [Startup/Enterprise/Non-profit etc.]
- **Salary range:** [Range if provided, or "Open / market rate"]

## Priorities and Values
[1 paragraph: what matters most to the candidate and why. Connect stated
priorities to evidence from the CV — e.g. if they value impact and
have volunteering experience, note that pattern.]

## Distinctive Strengths
[1 paragraph: what makes the candidate stand out. Combine what they said about
their edge with what you observed from the CV. Be specific.]

## Constraints and Dealbreakers
[Bullet list of non-negotiables. If they didn't mention any, write "None specified."]
```

**After generating the Career Brief:**

1. Save it to `career-brief.md` in the current working directory using the `Write` tool
2. Display the full text in the conversation
3. Ask the candidate: *"Here's the Career Brief I've drafted based on your answers. Does this capture things accurately? Feel free to tell me anything you'd like to change before we start searching."*
4. If they request changes, update the document and re-save
5. Once confirmed, proceed to Phase 2

---

## Phase 2: Profile Analysis

Once you have both documents, analyse them thoroughly to build an internal **Candidate Profile**. Extract and synthesise:

### Professional Identity
- **Current/most recent role** and seniority level
- **Career trajectory** — direction of progression (e.g. IC to leadership, specialist deepening, career pivot)
- **Years of experience** — total and in key domains
- **Industry background** — sectors worked in, depth of domain knowledge

### Skills Inventory
- **Technical/hard skills** — tools, technologies, methodologies, certifications
- **Soft skills** — leadership, communication, stakeholder management patterns evident from the CV
- **Transferable skills** — capabilities that cross industry boundaries

### Geographic & Logistics
- **Current location** (from CV)
- **Target location(s)** (from Career Brief)
- **Work mode preference** — remote / hybrid / onsite
- **Visa/relocation considerations** if mentioned

### Career Aspirations (from Career Brief)
- **Target role types** and seniority
- **Target industries/sectors**
- **Salary expectations**
- **Values and priorities** (growth, impact, culture, flexibility, etc.)
- **Dealbreakers**

Present a concise summary of this profile to the candidate and ask them to confirm or correct anything before proceeding to the search phase.

---

## Phase 3: Configure Search

Based on the confirmed Candidate Profile, prepare the search configuration:

### 3a. Map Profile to Sectors

Map the candidate's target industries to sector keys used by the data files. Use `data/sector-keywords.local.json` if it exists, otherwise fall back to `data/sector-keywords.json`. The default file includes these example sectors:
- `climate_agtech` — climate, sustainability, clean energy
- `finance` — fintech, banking, payments
- `health_tech` — healthtech, digital health, clinical

Users can define additional sectors (e.g. `international_development`, `glam`, `design_strategy`, `education`) in their local override file. If the candidate's target sectors don't match any defined sector keys, build keyword sets on the fly from the candidate's profile.

### 3b. Build Search Parameters

From the profile, extract:
- **Keywords**: Combine target role titles + distinctive skills + sector terms. Example: `"data scientist,machine learning,ML engineer,analytics"`
- **Seniority levels**: Map to normalised levels. Example: `"mid,senior"`
- **Exclude keywords**: Things to filter out. Example: `"intern,internship,junior,entry level"`
- **Remote preference**: Whether to filter for remote-only

### 3c. Select Target Companies

Read the target companies list — use `data/target-companies.local.json` if it exists, otherwise fall back to `data/target-companies.json`. Select companies whose sectors overlap with the candidate's target sectors. Pass this filtered list to the ATS scanner agent.

---

## Phase 3.5: Detect Environment & Pre-Fetch (Desktop Mode)

Before launching agents, detect whether outbound HTTP works from Bash (CLI mode) or is blocked (Desktop mode). This determines how agents receive their data.

### Mode Detection

Run a quick connectivity test:
```bash
curl -s --max-time 5 -o /dev/null -w "%{http_code}" https://boards-api.greenhouse.io/v1/boards/test/jobs 2>/dev/null || echo "BLOCKED"
```

**Step 1 — Test curl connectivity:**
- **If curl succeeds** (returns any HTTP status code): **CLI mode** — skip the rest of Phase 3.5 and proceed to Phase 4. Agents will fetch data directly using shell scripts.
- **If curl fails or returns "BLOCKED"**: Continue to Step 2.

**Step 2 — Test MCP tool availability:**
- Check if `mcp__job-matcher-fetch__fetch_url` is in your available tool list.
- **If MCP fetch tool is available**: **Desktop MCP mode** — continue with the Pre-Fetch via MCP section below, then proceed to Phase 4 (Desktop mode agent prompts).
- **If MCP fetch tool is NOT available**: **Cowork mode** — skip the Pre-Fetch section entirely and proceed directly to Phase 4 (Cowork mode). All job discovery will use WebSearch fan-out in the main context.

### Pre-Fetch via MCP (Desktop MCP Mode Only)

When in Desktop mode, use the `mcp__job-matcher-fetch__fetch_url` tool to fetch all API data from the main context (MCP tools run outside the Desktop sandbox). Save responses to `data/tmp-scans/` so agents can process local files.

**Step 1: Create the output directory**
```bash
mkdir -p data/tmp-scans
```

**Step 2: Fetch ATS data for each target company**

For each company in the filtered target list (from Phase 3c):

- **Greenhouse** companies: call `fetch_url` with:
  - `url`: `https://boards-api.greenhouse.io/v1/boards/{SLUG}/jobs?content=true`
  - `output_file`: `data/tmp-scans/greenhouse-{SLUG}.json`

- **Ashby** companies: call `fetch_url` with:
  - `url`: `https://api.ashbyhq.com/posting-api/job-board/{SLUG}`
  - `output_file`: `data/tmp-scans/ashby-{SLUG}.json`

- **Lever** companies (if any): call `fetch_url` with:
  - `url`: `https://api.lever.co/v0/postings/{SLUG}`
  - `output_file`: `data/tmp-scans/lever-{SLUG}.json`

- **Workable** companies (if any): call `fetch_url` with:
  - `url`: `https://apply.workable.com/api/v1/widget/accounts/{SLUG}`
  - `method`: `POST`
  - `body`: `{}`
  - `headers`: `{"Content-Type": "application/json"}`
  - `output_file`: `data/tmp-scans/workable-{SLUG}.json`

**Batch fetch calls**: Make multiple `fetch_url` calls in parallel within a single tool-use turn to maximise throughput. Group 5-10 companies per turn.

**Step 3: Fetch free job API data**

Make these `fetch_url` calls (adjust categories/tags based on the candidate's profile):

| Source | URL | Output File |
|--------|-----|-------------|
| Remotive (product) | `https://remotive.com/api/remote-jobs?category=product` | `data/tmp-scans/api-remotive-product.json` |
| Remotive (design) | `https://remotive.com/api/remote-jobs?category=design` | `data/tmp-scans/api-remotive-design.json` |
| RemoteOK (design) | `https://remoteok.com/api?tag=design` | `data/tmp-scans/api-remoteok-design.json` |
| RemoteOK (product) | `https://remoteok.com/api?tag=product` | `data/tmp-scans/api-remoteok-product.json` |
| Jobicy | `https://jobicy.com/api/v2/remote-jobs?count=50&tag={TAG}` | `data/tmp-scans/api-jobicy-{TAG}.json` |
| Himalayas | `https://himalayas.app/jobs/api?limit=200` | `data/tmp-scans/api-himalayas-all.json` |
| The Muse (pg 0) | `https://www.themuse.com/api/public/jobs?page=0&level={LEVEL}&category={CAT}` | `data/tmp-scans/api-themuse-p0.json` |
| The Muse (pg 1) | `...?page=1&level={LEVEL}&category={CAT}` | `data/tmp-scans/api-themuse-p1.json` |
| The Muse (pg 2) | `...?page=2&level={LEVEL}&category={CAT}` | `data/tmp-scans/api-themuse-p2.json` |

Adjust the categories, tags, and levels based on the candidate's profile from Phase 3b.

**Step 4: Fetch RSS feeds**

For each relevant RSS feed (based on candidate's sectors), fetch the raw XML and convert to JSON:

1. Call `fetch_url` with the feed URL and `output_file` set to `data/tmp-scans/rss-{name}.xml`
2. Convert XML to JSON: `cat data/tmp-scans/rss-{name}.xml | python3 scripts/parse-rss.py --feed-url "FEED_URL" > data/tmp-scans/rss-{name}.json`

RSS feeds to consider:
| Feed | URL | Output File |
|------|-----|-------------|
| WWR Design | `https://weworkremotely.com/categories/remote-design-jobs.rss` | `rss-wwr-design` |
| WWR Product | `https://weworkremotely.com/categories/remote-product-jobs.rss` | `rss-wwr-product` |
| WWR Programming | `https://weworkremotely.com/categories/remote-programming-jobs.rss` | `rss-wwr-programming` |
| Remotive Design | `https://remotive.com/remote-jobs/design/feed` | `rss-remotive-design` |
| Remotive Product | `https://remotive.com/remote-jobs/product/feed` | `rss-remotive-product` |
| Code4Lib | `https://jobs.code4lib.org/jobs.atom` | `rss-code4lib` |

**Step 5: Write manifest**

Write `data/tmp-scans/manifest.json` listing all fetched files:
```json
{
  "mode": "prefetched",
  "fetched_at": "ISO timestamp",
  "ats_files": [
    {"path": "greenhouse-stripe.json", "source": "greenhouse", "slug": "stripe", "company": "Stripe"}
  ],
  "api_files": [
    {"path": "api-remotive-product.json", "source": "remotive", "params": "category=product"}
  ],
  "rss_files": [
    {"path": "rss-wwr-design.json", "source": "rss", "feed_url": "https://..."}
  ]
}
```

---

## Phase 4: Execute Parallel Search

The search strategy depends on the mode detected in Phase 3.5:

- **CLI mode and Desktop MCP mode**: Launch three background agents (4a-4c) plus run niche WebSearch (4d). The agent prompts differ — use **CLI mode** prompts if curl works, or **Desktop MCP mode** prompts if data was pre-fetched.
- **Cowork mode**: Skip agents entirely and proceed to section **4e. WebSearch Fan-Out**. All job discovery happens via WebSearch in the main context.

### Agent-Based Search (CLI and Desktop MCP modes only)

### 4a. Launch ATS Scanner Agent

Use the Task tool with `subagent_type` set to the ats-scanner agent.

**CLI mode prompt:**
```
Prompt: "Scan ATS APIs for the following candidate profile:
- Sectors: [list of sector keys]
- Keywords: [keyword string]
- Seniority: [seniority levels]
- Exclude: [exclude keywords]
- Remote only: [yes/no]

Project root: [current working directory]
Read target-companies.local.json if it exists, otherwise target-companies.json. Filter to the relevant sectors, then scan each company's ATS.
Pipe results through normalize-jobs.py and filter-jobs.py.
Write final results to data/ats-scan-results.json."
```

**Desktop mode prompt** (when data was pre-fetched in Phase 3.5):
```
Prompt: "Process pre-fetched ATS data for the following candidate profile:
- Keywords: [keyword string]
- Seniority: [seniority levels]
- Exclude: [exclude keywords]
- Remote only: [yes/no]

IMPORTANT: API data has been pre-fetched. Do NOT call curl or shell scripts to fetch data.
Read the manifest at data/tmp-scans/manifest.json to find all ATS files.
For each ATS file, pipe through the normalize and filter pipeline:
  cat data/tmp-scans/{filename} | python3 scripts/normalize-jobs.py --source {source} --company 'COMPANY' | python3 scripts/filter-jobs.py --keywords 'KEYWORDS' --seniority 'LEVELS' --exclude-keywords 'EXCLUDES'

Project root: [current working directory]
Collect all results into a single JSON array.
Write final results to data/ats-scan-results.json."
```

### 4b. Launch API Searcher Agent

Use the Task tool with `subagent_type` set to the api-searcher agent.

**CLI mode prompt:**
```
Prompt: "Search free job APIs for the following candidate profile:
- Keywords: [keyword string]
- Seniority: [seniority levels]
- Exclude: [exclude keywords]
- Categories to search: [mapped API categories]

Project root: [current working directory]
Search all five APIs (Remotive, RemoteOK, Jobicy, Himalayas, The Muse).
Pipe results through normalize-jobs.py, filter-jobs.py, and deduplicate-jobs.py.
Write final results to data/api-search-results.json."
```

**Desktop mode prompt** (when data was pre-fetched in Phase 3.5):
```
Prompt: "Process pre-fetched job API data for the following candidate profile:
- Keywords: [keyword string]
- Seniority: [seniority levels]
- Exclude: [exclude keywords]

IMPORTANT: API data has been pre-fetched. Do NOT call curl or shell scripts to fetch data.
Read the manifest at data/tmp-scans/manifest.json to find all API files.
For each API file, pipe through the normalize and filter pipeline:
  cat data/tmp-scans/{filename} | python3 scripts/normalize-jobs.py --source {source} | python3 scripts/filter-jobs.py --keywords 'KEYWORDS' --seniority 'LEVELS' --exclude-keywords 'EXCLUDES'

Project root: [current working directory]
Merge all results and deduplicate: cat merged.json | python3 scripts/deduplicate-jobs.py > data/api-search-results.json
Write final results to data/api-search-results.json."
```

### 4c. Launch RSS Scanner Agent

Use the Task tool with `subagent_type` set to the rss-scanner agent.

**CLI mode prompt:**
```
Prompt: "Scan RSS feeds for the following candidate profile:
- Keywords: [keyword string]
- Seniority: [seniority levels]
- Sectors: [list of sector keys]

Project root: [current working directory]
Fetch relevant RSS feeds based on sectors.
Pipe results through normalize-jobs.py and filter-jobs.py.
Write final results to data/rss-scan-results.json."
```

**Desktop mode prompt** (when data was pre-fetched in Phase 3.5):
```
Prompt: "Process pre-fetched RSS data for the following candidate profile:
- Keywords: [keyword string]
- Seniority: [seniority levels]

IMPORTANT: RSS data has been pre-fetched and converted to JSON. Do NOT call curl or fetch-rss.sh.
Read the manifest at data/tmp-scans/manifest.json to find all RSS JSON files.
For each RSS file, pipe through the normalize and filter pipeline:
  cat data/tmp-scans/{filename} | python3 scripts/normalize-jobs.py --source rss | python3 scripts/filter-jobs.py --keywords 'KEYWORDS' --seniority 'LEVELS' --exclude-keywords 'EXCLUDES'

Project root: [current working directory]
Collect all results into a single JSON array.
Write final results to data/rss-scan-results.json."
```

### 4d. Run WebSearch in Main Context (Niche Boards)

While agents run, use `WebSearch` directly in the main conversation for niche boards that don't have APIs. Run 4-6 targeted searches based on the candidate's profile. Examples:

- For international development: `site:devex.com [role title] [year]`
- For humanitarian: `site:reliefweb.int jobs [role title] [year]`
- For GLAM: `site:museumsassociation.org jobs [role title]` or `site:aam-us.org [role title]`
- For non-profit: `site:idealist.org [role title] remote`
- For climate: `site:climatebase.org [role title]` (use as discovery, verify elsewhere)

Only search niche boards relevant to the candidate's target sectors. Skip this step entirely if the candidate's profile doesn't include niche sectors.

### 4e. WebSearch Fan-Out (Cowork Mode Only)

In Cowork mode, agents cannot make network requests and MCP tools are unavailable. **WebSearch is the only network channel** — it runs on Anthropic's infrastructure and bypasses the VM's egress proxy entirely.

Run **15-25 targeted WebSearch queries** in parallel batches. The model processes results directly — no normalise/filter scripts are needed.

#### Search Strategy

Design searches based on the candidate's profile from Phase 3. Run each batch in parallel (multiple WebSearch calls in a single message), then process results before the next batch.

**Batch 1: ATS Board Discovery (4-8 searches, parallel)**

Search target companies' Greenhouse/Ashby boards directly. These are the highest-quality results — if a job appears on an ATS board, it's guaranteed open.

Group 2-3 related companies per search to maximize coverage:
```
site:boards.greenhouse.io/stripe OR site:boards.greenhouse.io/figma "[role keyword]" remote
site:boards.greenhouse.io/flatironhealth OR site:boards.greenhouse.io/zocdoc "[role keyword]"
site:jobs.ashbyhq.com/ramp OR site:jobs.ashbyhq.com/watershed "[role keyword]"
```

Select companies from the target list (Phase 3c) whose sectors match the candidate. Use the candidate's primary role keywords (e.g. "product manager", "UX designer", "data scientist").

**Batch 2: Remote Job Board Discovery (4-6 searches, parallel)**

Search major remote job boards. Include the current year to prefer recent listings:
```
site:weworkremotely.com "[role keyword]" [year]
site:remotive.com "[role keyword]" remote [year]
site:remoteok.com "[role keyword]" [year]
site:himalayas.app "[role keyword]" remote [year]
"[role keyword]" remote job [year] site:jobicy.com
```

Vary the role keywords across searches — use the candidate's primary title for some and secondary/adjacent titles for others.

**Batch 3: Sector-Specific Discovery (2-4 searches, parallel)**

Select searches based on the candidate's target sectors:

| Sector | Search Query |
|--------|-------------|
| Climate/AgTech | `"[role keyword]" climate sustainability remote job [year]` |
| Climate/AgTech | `site:climatetechlist.com "[role keyword]"` |
| Finance/Fintech | `"[role keyword]" fintech remote job [year]` |
| Health/HealthTech | `"[role keyword]" healthtech "digital health" remote job [year]` |
| GLAM | `site:jobs.code4lib.org "[role keyword]"` |
| GLAM | `"[role keyword]" museum library archive job remote [year]` |
| Non-profit | `site:idealist.org "[role keyword]" remote` |
| Intl Development | `site:devex.com "[role keyword]" [year]` |

**Batch 4: Broad Discovery (2-3 searches, parallel)**

Cast a wider net for roles that might appear outside the usual boards:
```
"[primary role title]" remote hiring [year] -intern -internship
"[secondary role title]" remote job [year] apply
"[role keyword]" "[sector term]" remote job opening [year]
```

#### Processing WebSearch Results

After each batch, extract job listings from the search results. For each result:

1. **Extract**: Job title, company name, URL, and any details visible in the search snippet (location, salary, posting date)
2. **Filter**: Discard results that are clearly irrelevant (wrong role type, wrong seniority, aggregator pages without specific listings)
3. **Track**: Keep a running list of unique jobs found (deduplicate by company + title)

#### Enrichment via WebFetch (Optional but Recommended)

After collecting all WebSearch results, use `WebFetch` to load the actual job posting pages for the **top 10-15 most promising results**. This provides:
- Full job description and requirements
- Exact location and remote policy
- Salary range (if listed)
- Application instructions and direct apply link

For each promising result:
```
WebFetch URL="[job listing URL]" prompt="Extract: job title, company, location, remote policy, salary range, required skills, preferred skills, seniority level, posting date, and application URL. Return as structured data."
```

If WebFetch fails for a URL (some sites block automated fetches), keep the job with whatever information WebSearch provided and mark it as having limited detail.

#### Cowork Mode Output

After all batches and enrichment, compile the collected jobs into a structured list. Each job should have:
- `title` — Job title
- `company` — Company name
- `url` — Direct link to the listing (prefer ATS/employer URLs over aggregator pages)
- `source` — Where it was found (e.g. "greenhouse board", "weworkremotely", "remotive", "websearch")
- `location` — Location or "Remote"
- `salary` — Salary range if available, otherwise "Not listed"
- `posted_date` — Posting date if available
- `description_summary` — Key requirements/details from snippet or WebFetch
- `verification_status` — "GUARANTEED" for ATS board results, "VERIFIED" for WebFetch-confirmed results, "UNVERIFIED" for snippet-only results

There is no need to write intermediate JSON files in Cowork mode — proceed directly to Phase 5e (Cowork merge) with the compiled list.

---

## Phase 5: Merge, Deduplicate, and Verify

Phase 5 differs by mode. In CLI and Desktop MCP modes, merge agent result files. In Cowork mode, the job list was compiled directly in Phase 4e.

**Cowork mode**: Skip to **5e. Cowork Merge** below.

### Agent-Based Merge (CLI and Desktop MCP modes)

Once all three agents have completed:

### 5a. Collect Results

Read the three result files:
- `data/ats-scan-results.json` — ATS results (verification_status: GUARANTEED)
- `data/api-search-results.json` — API results (verification_status: API_ACTIVE)
- `data/rss-scan-results.json` — RSS results (verification_status: UNVERIFIED)

Plus any roles found via WebSearch in step 4d (add these manually).

### 5b. Merge and Deduplicate

Combine all results and run through the deduplication pipeline:

```bash
# Merge all JSON arrays and deduplicate
python3 -c "
import json, sys
all_jobs = []
for f in ['data/ats-scan-results.json', 'data/api-search-results.json', 'data/rss-scan-results.json']:
    try:
        with open(f) as fh:
            all_jobs.extend(json.load(fh))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
json.dump(all_jobs, sys.stdout)
" | python3 scripts/deduplicate-jobs.py > data/merged-results.json
```

### 5c. Verify Non-Guaranteed Listings

For jobs where `verification_status` is NOT "GUARANTEED":

**CLI mode:** Use `scripts/verify-url.sh URL` to check each listing via curl.

**Desktop mode:** Use `mcp__job-matcher-fetch__verify_url` from the main context to check each listing. The MCP tool performs the same HEAD + GET + body scan logic as verify-url.sh. Call it for each URL that needs verification:
- Tool: `verify_url`
- Parameter: `url` — the job listing URL
- Returns: `{url, status: VERIFIED|EXPIRED|UNVERIFIABLE, http_code, reason}`

In both modes:
- Mark results as VERIFIED, EXPIRED, or UNVERIFIABLE
- Discard EXPIRED listings
- Keep UNVERIFIABLE listings but flag them

For ATS results (GUARANTEED status), no verification is needed — include them directly.

### 5d. Final Filtered Pool

After verification, you should have a pool of verified jobs. If fewer than 10, note this honestly in the report and explain why.

### 5e. Cowork Merge (Cowork Mode Only)

In Cowork mode, the job list was compiled directly during Phase 4e (WebSearch fan-out). No file-based merge is needed.

1. **Deduplicate**: Remove duplicate entries by company name + job title (case-insensitive). When duplicates are found across sources, prefer the version with more detail (e.g. a WebFetch-enriched version over a snippet-only version).

2. **Verify via WebFetch**: For jobs that were NOT found on ATS boards (i.e. not from `boards.greenhouse.io` or `jobs.ashbyhq.com`), attempt to verify they are still open:
   - Use `WebFetch` on the listing URL with prompt: `"Is this job listing currently open for applications? Look for application buttons, closing dates, or 'position filled' notices. Return: status (open/closed/unclear), any salary info, and location details."`
   - Mark verified listings as "VERIFIED", failed/unclear as "UNVERIFIED"
   - If WebFetch fails entirely (blocked), keep the listing as "UNVERIFIED"

3. **ATS board results** (URLs containing `boards.greenhouse.io` or `jobs.ashbyhq.com`): Mark as "GUARANTEED" — these are always open if they appear in search results.

4. **Final pool**: Combine all verified + guaranteed + unverified listings. Proceed to Phase 6 for scoring.

---

## Phase 6: Score and Rank

For each verified job, calculate a **match score** (0-100) based on:

| Dimension | Weight | Criteria |
|-----------|--------|----------|
| Skills alignment | 0-30 | % of required skills the candidate has |
| Seniority fit | 0-20 | Role level vs candidate's current/target level |
| Sector relevance | 0-20 | Industry alignment with background and goals |
| Work mode match | 0-15 | Remote/hybrid/onsite alignment with preferences |
| Culture/values | 0-10 | Mission alignment, org size, signals from description |
| Recency | 0-5 | Posted within last 30 days = full marks |

### Scoring in Cowork Mode

When working with WebSearch results that lack full job descriptions:
- **Skills alignment**: Score based on title match, snippet keywords, and any details obtained via WebFetch. If no description is available, infer from the job title and company's known focus areas.
- **Culture/values**: Use your knowledge of the company (if it's a known company from the target list) rather than relying solely on the job description.
- **Recency**: If no posting date is visible, assume recent (WebSearch tends to surface recent results) and give partial credit (3/5).

Jobs enriched via WebFetch should be scored the same as API-sourced jobs since you have full description data.

### Tier Assignment
- **Tier 1: Strong Matches** (80-100%) — Strong fit right now
- **Tier 2: Good Matches** (60-79%) — Good fit with some stretch
- **Tier 3: Growth Opportunities** (40-59%) — Stretch roles aligned with trajectory

---

## Phase 7: Generate the Detailed Report

Produce a comprehensive, well-formatted Markdown report. Write this report to a file using the `Write` tool, saving it as `job-match-report.md` in the current working directory. Also display the full report in the conversation.

### Report Structure

```
# Job Match Report
**Prepared for:** [Candidate Name]
**Date:** [Current Date]
**Based on:** CV/Resume and Career Brief analysis

---

## Executive Summary
[2-3 paragraph overview: who the candidate is, what they're looking for,
the state of the market for the candidate's profile, and headline findings]

---

## Candidate Profile Summary
[Condensed version of Phase 2 analysis — the candidate's key strengths, target,
and differentiators]

---

## Market Landscape
[Brief analysis of the current job market for the candidate's profile:
- Demand level for the candidate's skills
- Salary ranges observed in the market (use Jobicy salary data if available)
- Trends affecting the candidate's target roles
- Competition level]

---

## Job Matches

### Tier 1: Strong Matches (Score 80-100%)
[Roles where the candidate is a strong fit RIGHT NOW]

For each role:
#### [Role Title] — [Company Name]
- **Verification:** ✅ GUARANTEED OPEN (ATS) | ✅ VERIFIED OPEN | ⚠️ UNVERIFIED
- **Source:** [greenhouse/lever/ashby/remotive/etc.]
- **Match Score:** [X]%
- **Location:** [Location] | [Remote/Hybrid/Onsite]
- **Salary:** [Range if listed, or estimated range based on market data]
- **Posted:** [Date if available]
- **Apply here:** [Direct ATS/employer URL]

**Why this matches:**
[2-3 sentences on why this is a strong fit]

**Potential gaps:**
[Any minor gaps and how to address them in the application]

**Application tip:**
[Specific advice for applying to THIS role — what to emphasise,
what to address in the cover letter]

---

### Tier 2: Good Matches (Score 60-79%)
[Same format as Tier 1]

---

### Tier 3: Growth Opportunities (Score 40-59%)
[Same format as Tier 1, with additional notes on what skills/experience
would need to be developed]

---

## Gap Analysis

### Skills Gaps
| Skill/Qualification | Importance | Current Level | Recommended Action |
|---------------------|-----------|---------------|-------------------|
| [Skill] | High/Med/Low | [Level] | [Action] |

### Experience Gaps
[Areas where the candidate may need more depth]

### Qualification Gaps
[Certifications, degrees, or formal qualifications that would strengthen
the candidate's application]

---

## Career Guidance

### Career Pathways
[2-3 potential career paths based on the candidate's profile and the market:
- Path A: [Most direct/obvious path]
- Path B: [Adjacent opportunity]
- Path C: [Ambitious/pivot path]]

### Upskilling Recommendations
[Specific courses, certifications, or learning paths — with actual
providers/platforms where possible]

### CV/Resume Optimisation Tips
[Specific suggestions for strengthening the candidate's CV for the roles identified:
- Keywords to incorporate
- Achievements to highlight
- Sections to restructure]

### Market Positioning Advice
[How to position competitively:
- Personal brand angle
- Networking targets
- LinkedIn optimisation tips
- Industry events/communities to engage with]

---

## Next Steps
[Prioritised action plan:
1. Immediate actions (this week)
2. Short-term actions (next 2-4 weeks)
3. Medium-term development (1-3 months)]

---

## Methodology & Sources
**Search strategy:** [Describe the mode used]
- CLI/Desktop MCP mode: "API-first architecture querying ATS and job APIs directly."
- Cowork mode: "WebSearch fan-out across ATS career boards, remote job boards, and sector-specific sources."

**Sources scanned:**
- ATS APIs/boards: [list companies scanned with count]
- Job APIs/boards: [list APIs or job boards queried with count]
- RSS feeds: [list feeds fetched with count, or "N/A — Cowork mode"]
- WebSearch queries: [number of searches, key queries used]
- WebFetch enrichment: [number of listings enriched with full details]

**Verification:**
- ✅ GUARANTEED OPEN: [N] roles from ATS APIs/boards (active by definition)
- ✅ VERIFIED OPEN: [N] roles verified via URL check or WebFetch
- ⚠️ UNVERIFIED: [N] roles where verification was not possible

**Limitations:** [Any limitations — niche sectors with few API-accessible listings,
geographic restrictions, etc. In Cowork mode, note that results are limited to
what WebSearch indexes and that full job descriptions may not be available for all listings.]
```

---

## Important Guidelines

- **ATS results are GUARANTEED open.** Jobs from Greenhouse, Lever, Workable, and Ashby APIs (or their board URLs in Cowork mode) are active by definition. Always prefer these over other sources.
- **ONLY include verified-open jobs from non-ATS sources.** Every non-ATS role must be verified via `verify-url.sh`, `mcp__job-matcher-fetch__verify_url`, or `WebFetch` check. If verification fails, either discard it or mark it prominently as **⚠️ UNVERIFIED**.
- **Link to the employer's ATS, not aggregator pages.** ATS results already have direct URLs. For WebSearch results, always find the employer's own careers page or ATS link. In Cowork mode, prefer `boards.greenhouse.io/slug/jobs/ID` URLs over third-party links.
- **Be honest about match quality** — don't inflate scores. A 65% match is genuinely useful; the candidate needs accurate signals.
- **Never fabricate listings** — every job in the report must be a real advertisement found during the search. In Cowork mode, only include jobs that appeared in actual WebSearch results.
- **Salary data**: Jobicy API includes salary ranges. In Cowork mode, salary data may be limited — clearly distinguish between listed salaries and estimates.
- **Tailor advice to the individual** — generic career advice is unhelpful. Every recommendation should connect back to the candidate's specific profile and target roles.
- **Be regionally aware** — use appropriate terminology, salary currencies, and cultural norms for the candidate's target market.
- **If the search yields few results**, say so honestly and explain why. Suggest how to broaden the search or add more companies to `target-companies.json`. Eight verified-open roles are more valuable than twenty where half are expired.
- **In Cowork mode, maximise WebSearch effectiveness:** Use specific `site:` operators for ATS boards. Include the current year in queries to bias toward recent listings. Vary role keywords across searches to avoid duplicate results. Use WebFetch to enrich the most promising results with full descriptions.
