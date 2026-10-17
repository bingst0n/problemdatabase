# AMC 10 Problem Database

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

AoPS is behind Cloudflare and refuses cloud/datacenter IP addresses (HTTP 403,
`error code: 1007`), so run the scraper from a normal home connection.

Difficulty is position-based (problems 1–5, 6–10, … map to a rating); edit
`scraper/difficulty.json` and re-run to change it. Categories come from the
wiki's own categories; when a page has none, a keyword scorer guesses one and
the UI shows it with a dashed tag and a `?`. To pin a category by hand, add
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
