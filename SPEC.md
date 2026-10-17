# AMC 10 Problem Database — V1 Spec

## Purpose

A small, local, searchable database of AMC 10A and AMC 10B problems. Type a
reference like `2019 AMC 10A number 13` into a search bar and get the problem
rendered with LaTeX, its five answer choices, a toggle that reveals the
correct choice, and every solution from the AoPS wiki page. The same search
bar doubles as an advanced filter over the whole set (year, contest, problem
number, difficulty, category, free text).

## Scope (V1)

- **Contests:** AMC 10A and AMC 10B, 2002 through the most recent contest on
  the AoPS wiki (2025 at the time of writing), including the two 2021 Fall
  contests. 25 problems each. 2000 and 2001 (plain "AMC 10", before the A/B
  split) are **not** included.
- **Source:** the AoPS wiki (`artofproblemsolving.com/wiki`), fetched through
  its MediaWiki API. Nothing is written by hand; everything comes from the
  wiki's problem pages and answer-key pages.
- **Out of scope:** AMC 8, AMC 12, AIME, user accounts, progress tracking,
  a server-side database, editing problems.

## Data source and what is taken from each page

Per problem page, e.g. `2019 AMC 10A Problems/Problem 13`:

| Field | Where it comes from |
|---|---|
| Statement | The section under the `Problem` heading, up to the first solution heading. Includes any `Diagram`/`Note` sections that appear before the solutions. |
| Answer choices | The LaTeX line containing `(A)` … `(E)`, split into five choices. If the split fails, the raw LaTeX is kept and shown as one line. |
| Solutions | Every section from the first `Solution…` heading up to `See Also`, in order, with its heading text (so "Solution 2 (Casework)" and "Video Solution by X" keep their names). |
| Categories | The page's MediaWiki categories (`Introductory Geometry Problems`, etc.). |
| Correct answer | The contest's `… Answer Key` page. The first `\boxed{…(D)…}` in the solutions is used as a cross-check and as a fallback when the key is missing. |
| Redirects | AMC 10 problems shared with the AMC 12 redirect to the AMC 12 page. Redirects are followed and the original title is recorded. |

LaTeX arrives in the wiki's rendered HTML as `<img alt="$…$">`; the `alt`
text is the LaTeX source, so it is stored as text and rendered client-side
with KaTeX. Asymptote diagrams have no LaTeX equivalent, so their rendered PNGs
(and any wiki-uploaded images) are downloaded into `site/data/img/`, named by
a hash of their source URL, and referenced with relative paths. The site works
offline once scraped. `site/data/images.json` maps each file back to its
source URL.

## Tags

**Category.** Derived from the wiki categories by keyword:

| Wiki category contains | Tag |
|---|---|
| Number Theory | `number_theory` |
| Combinatorics | `combinatorics` |
| Probability | `probability` |
| Geometry | `geometry` |
| Algebra | `algebra` |
| any other `… Problems` category (Trigonometry, Logic, …) | `other` |

A problem can carry several tags. Each problem records where its tags came
from (`category_source`):

| Source | Meaning |
|---|---|
| `wiki` | the page had at least one `… Problems` category |
| `override` | listed in `scraper/category_overrides.json` (hand-set; beats everything) |
| `guessed` | the page had no category, so a keyword scorer over the statement and choices picked one; shown with a dashed tag and a `?` in the UI |
| `null` | nothing matched; shown as `Uncategorized` in the filter so gaps stay visible |

The guesser scores each subject by weighted keyword hits (e.g. "divisible",
"digit" → number theory; "probability", "random" → probability; "triangle",
"area" → geometry; a diagram nudges geometry) and assigns the top subject when
the score clears a small threshold, plus a second subject only when it is
nearly as strong. It is deliberately conservative.

**Difficulty.** The wiki has no per-problem rating. V1 uses the position-based
convention from the AoPS "Competition ratings" page, kept in
`scraper/difficulty.json` so it can be edited:

| Problems | Rating | Label |
|---|---|---|
| 1–5 | 1 | Easy |
| 6–10 | 2 | Easy–Medium |
| 11–15 | 2.5 | Medium |
| 16–20 | 3 | Medium–Hard |
| 21–25 | 4 | Hard |

The rating numbers follow the AoPS 1–10 scale as best recalled; the page
itself could not be fetched from the build environment, so these values
should be checked against it.

## Architecture

Two parts, no backend:

```
scraper/   Python 3. Fetches pages via the MediaWiki API, caches raw
           responses on disk, parses them, writes JSON into site/data/.
site/      Static HTML + vanilla JS + vendored KaTeX. Loads site/data/
           with fetch() and does all searching/filtering in the browser.
```

Run with any static file server (`python3 -m http.server --directory site`).

### Data files

`site/data/index.json` — everything needed to search and display a problem
except its solutions:

```json
{
  "generated_at": "2026-10-17T13:40:00Z",
  "contests": [{"id": "2019_AMC_10A", "name": "2019 AMC 10A", "year": 2019,
                "fall": false, "version": "A", "url": "…"}],
  "problems": [{
    "id": "2019_AMC_10A_13",
    "contest_id": "2019_AMC_10A",
    "year": 2019, "fall": false, "version": "A", "number": 13,
    "title": "2019 AMC 10A Problem 13",
    "url": "https://artofproblemsolving.com/wiki/index.php/2019_AMC_10A_Problems/Problem_13",
    "redirected_to": "2019 AMC 12A Problems/Problem 10",
    "statement_html": "<p>Let <span class=\"tex\">\\triangle ABC</span> …</p>",
    "statement_text": "Let \\triangle ABC be …",
    "choices": [{"label": "A", "tex": "110"}, …],
    "choices_tex": "\\textbf{(A) } 110 \\qquad …",
    "answer": "D",
    "answer_source": "answer_key",
    "difficulty": 2.5, "difficulty_label": "Medium",
    "categories": ["geometry"],
    "wiki_categories": ["Introductory Geometry Problems"],
    "solution_count": 7
  }]
}
```

`site/data/solutions/<contest_id>.json` — solutions for one contest, loaded
when a problem is opened:

```json
{"2019_AMC_10A_13": [{"heading": "Solution 1", "html": "<p>…</p>"}, …]}
```

`site/data/report.json` — what the scrape could not do: missing pages,
problems whose choices did not split, answer-key/boxed-answer disagreements,
uncategorized problems. Meant to be read after each scrape.

Stored HTML is a whitelist of plain tags (`p, ul, ol, li, table, …`). Math is
`<span class="tex">…</span>` (inline) or `<div class="tex-display">…</div>`
(display) holding raw LaTeX; diagrams are `<img class="diagram">`.

## Search

One text box. The query is parsed for a contest reference first; whatever is
left is free text matched against the statement.

| Query | Interpreted as |
|---|---|
| `2019 AMC 10A number 13`, `2019 10a #13`, `2019 10A 13`, `amc 10a 2019 problem 13` | year 2019, version A, problem 13 → opens the problem directly |
| `2021 fall 10b` | the 25 problems of 2021 Fall AMC 10B |
| `2019 10a` | the 25 problems of 2019 AMC 10A |
| `10b` | every AMC 10B problem |
| `inscribed circle` | every problem whose statement contains both words |
| `2019 triangle` | 2019 problems mentioning "triangle" |

Below the box, filters narrow the result set and combine with the query:

- Year range (from/to)
- Contest (10A, 10B)
- Problem number range (from/to, 1–25)
- Difficulty (one checkbox per rating)
- Category (one checkbox per tag; a problem matches if any of its tags is checked)

Results are listed newest first with a plain-text snippet and tags. One exact
match opens immediately.

## Problem view

- Heading `2019 AMC 10A · Problem 13`, tags, link to the AoPS page.
- Statement rendered with KaTeX.
- Answer choices as a list (A)–(E).
- `Show answer` checkbox: highlights the correct choice and prints the letter.
- `Show solutions (n)` button: reveals all solutions in order, each with its
  wiki heading. Hidden by default to avoid spoilers.
- Previous / Next problem within the same contest.
- The URL hash holds the problem id (`#/problem/2019_AMC_10A_13`) so a
  problem can be bookmarked or shared.

## Scraper behaviour

- Endpoint: `api.php?action=parse&page=<title>&prop=text|categories&redirects=1`.
- Descriptive User-Agent; at most a few requests per second (default 4
  workers, 0.25 s minimum spacing); exponential backoff on 429/5xx.
- Raw API responses cached under `scraper/cache/` (git-ignored) so re-runs
  and parser fixes do not re-fetch. Images already in `site/data/img/` are
  not re-downloaded.
- AoPS is behind Cloudflare and refuses many cloud/datacenter IP ranges with
  HTTP 403 `error code: 1007`. The scraper detects that and says so; it has to
  run from an ordinary home connection.
- A contest whose answer-key page is missing (e.g. a future year) is skipped
  and reported.
- `python3 scraper/scrape.py` scrapes everything; `--years 2019-2020` or
  `--contests 2019_AMC_10A` limit it; `--force` ignores the cache;
  `--no-images` keeps AoPS image URLs instead of downloading.

## Decisions

- 2002 onward only; the 2000 and 2001 plain "AMC 10" are not included.
- Diagrams are downloaded into the repo, not hotlinked.
- Solutions stay hidden behind a button to avoid spoilers.
- Video-solution sections are kept as links.
- Problems with no wiki category get a guessed category, marked as such.
- Difficulty stays position-based. The AoPS ratings page could not be
  fetched to confirm the numeric values in `scraper/difficulty.json`.
