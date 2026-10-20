# imodb

A local, searchable database of AMC 10A and AMC 10B problems (2002–present),
taken from the [AoPS Wiki](https://artofproblemsolving.com/wiki/). Type
`2019 AMC 10A number 13` and get the problem rendered with LaTeX, its answer
choices, a toggle to reveal the correct one, and every solution from the wiki.
The same box filters the whole set by year, contest, problem number,
difficulty and category.

See [SPEC.md](SPEC.md) for the full design.

## Setup

```sh
pip install -r scraper/requirements.txt
python3 scraper/scrape.py            # ~1,300 requests, a few minutes
python3 -m http.server 8000 --directory site
```

Then open <http://localhost:8000>. The site must be served over HTTP (it
loads `data/index.json` with `fetch`), but any static server works.

### Scraper options

```sh
python3 scraper/scrape.py --years 2019-2021            # a range of years
python3 scraper/scrape.py --contests 2019_AMC_10A      # one or more contest ids
python3 scraper/scrape.py --force                      # ignore scraper/cache/
python3 scraper/scrape.py --workers 2 --delay 0.5      # gentler on the wiki
```

Raw API responses are cached in `scraper/cache/` (git-ignored), so fixing the
parser and re-running never re-downloads. Diagrams are saved to
`site/data/img/` (`--no-images` to skip). After each run read
`site/data/report.json`: it lists problems whose answer choices did not split,
problems with no or guessed categories, failed image downloads, and
answer-key/solution disagreements.

AoPS is behind Cloudflare. Cloud/datacenter IPs get HTTP 403 `error code: 1007`,
and since October 2026 every non-browser client gets a browser challenge
(HTTP 403, `cf-mitigated: challenge`) on all `/wiki/` URLs, including
`api.php` and the `latex.artofproblemsolving.com` image host, even from a
home connection. The committed data was fetched from a real Chrome session
that had passed the challenge. The tab requested the same `api.php` URLs
the scraper builds, one at a time. Each response was saved as
`scraper/cache/<title>.json`, named by `Fetcher._cache_path`, and each
diagram was saved into `site/data/img/` under the name `Fetcher.fetch_image`
would give it. `scrape.py --years 2002-2025` then ran fully offline
(0 requests); a plain run would also ask about 2026, whose pages are not
cached, and stop at the challenge. Re-scraping needs the same approach.

Difficulty is position-based (problems 1–10, 11–20, 21–25 map to the AoPS
ratings page's ranges); edit
`scraper/difficulty.json` and re-run to change it. Categories come from the
wiki's own categories; when a page has none, a keyword scorer guesses one from
the statement (falling back to the solutions, then `other`). To pin a category by hand, add
`{"2019_AMC_10A_13": ["geometry"]}` to `scraper/category_overrides.json`.

## Search

| Type | Result |
|---|---|
| `2019 AMC 10A number 13`, `2019 10a #13`, `2019 10A 13` | opens that problem |
| `2021 fall 10b` | the 25 problems of 2021 Fall AMC 10B |
| `10b` | every AMC 10B problem |
| `inscribed circle` | problems whose statement contains both words |
| `2019 triangle` | 2019 problems mentioning "triangle" |

Press `/` to focus the search box. Filters (year range, contest, problem
number range, difficulty, category) combine with whatever is in the box.

## Layout

```
scraper/   Python 3 scraper (requests + BeautifulSoup). `python3 -m unittest discover -s scraper/tests`
site/      Static site: index.html, app.js, styles.css, vendored KaTeX, data/
```

Problems and solutions are © the Mathematical Association of America and the
AoPS Wiki contributors; this tool only fetches and displays them for personal
study.
