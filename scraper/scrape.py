#!/usr/bin/env python3
"""Scrape AMC 10A/10B problems from the AoPS wiki into site/data/.

    python3 scraper/scrape.py                       # everything, 2002..this year
    python3 scraper/scrape.py --years 2019-2020     # a range of years
    python3 scraper/scrape.py --contests 2019_AMC_10A,2021_Fall_AMC_10B
    python3 scraper/scrape.py --force               # ignore the on-disk cache

Raw API responses are cached in scraper/cache/ so parser changes never
re-download. Output: site/data/index.json, site/data/solutions/<contest>.json,
site/data/report.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contests import Contest, all_contests, page_url, parse_contest_id  # noqa: E402
from parse import parse_answer_key, parse_problem_page  # noqa: E402

HERE = Path(__file__).resolve().parent
API = "https://artofproblemsolving.com/wiki/api.php"
USER_AGENT = (
    "problemdatabase-scraper/0.1 (personal AMC study tool; "
    "https://github.com/bingst0n/problemdatabase)"
)
PROBLEMS_PER_CONTEST = 25


class Fetcher:
    """Polite MediaWiki API client with a disk cache and a global rate limit."""

    def __init__(self, cache_dir: Path, min_interval: float, force: bool):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.force = force
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._lock = threading.Lock()
        self._last = 0.0
        self.requests_made = 0

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests_made += 1

    def _cache_path(self, title: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", title)
        return self.cache_dir / f"{safe}.json"

    def parse_page(self, title: str) -> dict | None:
        """action=parse for a page. Returns the `parse` object, or None if the
        page does not exist."""
        path = self._cache_path(title)
        if path.exists() and not self.force:
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = self._request(title)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if "error" in data:
            code = data["error"].get("code")
            if code in ("missingtitle", "nosuchpageid", "invalidtitle"):
                return None
            raise RuntimeError(f"API error for {title!r}: {data['error']}")
        return data["parse"]

    def _request(self, title: str) -> dict:
        params = {
            "action": "parse",
            "page": title,
            "prop": "text|categories|displaytitle|revid",
            "redirects": 1,
            "disableeditsection": 1,
            "disabletoc": 1,
            "format": "json",
            "formatversion": 2,
        }
        delay = 2.0
        for attempt in range(6):
            self._throttle()
            try:
                r = self.session.get(API, params=params, timeout=60)
            except requests.RequestException as e:
                if attempt == 5:
                    raise
                print(f"  network error on {title!r}: {e}; retrying in {delay:.0f}s", file=sys.stderr)
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                retry_after = r.headers.get("Retry-After")
                sleep_for = float(retry_after) if retry_after and retry_after.isdigit() else delay
                print(f"  HTTP {r.status_code} on {title!r}; retrying in {sleep_for:.0f}s", file=sys.stderr)
                time.sleep(sleep_for)
                delay *= 2
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"gave up fetching {title!r}")


def load_difficulty(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["bands"]


def difficulty_for(number: int, bands: list[dict]) -> tuple[float | None, str | None]:
    for b in bands:
        if b["from"] <= number <= b["to"]:
            return b["rating"], b["label"]
    return None, None


def scrape_contest(contest: Contest, fetcher: Fetcher, bands: list[dict], report: dict) -> tuple[list[dict], dict]:
    key_page = fetcher.parse_page(contest.answer_key_title)
    answer_key: dict[int, str] = {}
    if key_page is None:
        report["missing_answer_keys"].append(contest.id)
    else:
        answer_key = parse_answer_key(key_page["text"])
        if len(answer_key) < PROBLEMS_PER_CONTEST:
            report["incomplete_answer_keys"].append({"contest": contest.id, "found": len(answer_key)})

    problems: list[dict] = []
    solutions: dict[str, list[dict]] = {}
    for n in range(1, PROBLEMS_PER_CONTEST + 1):
        title = contest.problem_title(n)
        page = fetcher.parse_page(title)
        pid = contest.problem_id(n)
        if page is None:
            report["missing_problems"].append(pid)
            continue
        cats = [c["category"] if isinstance(c, dict) else str(c) for c in page.get("categories", [])]
        parsed = parse_problem_page(page["text"], cats)

        final_title = page.get("title") or title
        redirected_to = final_title if final_title != title else None

        key_answer = answer_key.get(n)
        answer = key_answer or parsed.boxed_answer
        source = "answer_key" if key_answer else ("boxed" if parsed.boxed_answer else None)
        if key_answer and parsed.boxed_answer and key_answer != parsed.boxed_answer:
            report["answer_mismatches"].append({"problem": pid, "answer_key": key_answer, "boxed": parsed.boxed_answer})
        if answer is None:
            report["missing_answers"].append(pid)
        if parsed.choices is None:
            report["unsplit_choices"].append(pid)
        if not parsed.categories:
            report["uncategorized"].append(pid)
        for w in parsed.warnings:
            if "choices" in w:
                continue
            report["warnings"].append({"problem": pid, "warning": w})

        rating, label = difficulty_for(n, bands)
        problems.append({
            "id": pid,
            "contest_id": contest.id,
            "year": contest.year,
            "fall": contest.fall,
            "version": contest.version,
            "number": n,
            "title": f"{contest.name} Problem {n}",
            "url": page_url(title),
            "redirected_to": redirected_to,
            "statement_html": parsed.statement_html,
            "statement_text": parsed.statement_text,
            "choices": [asdict(c) for c in parsed.choices] if parsed.choices else None,
            "choices_tex": parsed.choices_tex,
            "answer": answer,
            "answer_source": source,
            "difficulty": rating,
            "difficulty_label": label,
            "categories": parsed.categories,
            "wiki_categories": parsed.wiki_categories,
            "solution_count": len(parsed.solutions),
        })
        solutions[pid] = [asdict(s) for s in parsed.solutions]
    return problems, solutions


def parse_years(spec: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", spec.strip())
    if not m:
        raise argparse.ArgumentTypeError("years must look like 2019 or 2019-2021")
    a = int(m.group(1))
    b = int(m.group(2) or a)
    return (min(a, b), max(a, b))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=HERE.parent / "site" / "data", help="output directory (default: site/data)")
    ap.add_argument("--cache", type=Path, default=HERE / "cache", help="raw response cache (default: scraper/cache)")
    ap.add_argument("--years", type=parse_years, default=None, help="e.g. 2019 or 2019-2021 (default: 2002-this year)")
    ap.add_argument("--contests", default=None, help="comma-separated contest ids, e.g. 2019_AMC_10A,2021_Fall_AMC_10B")
    ap.add_argument("--workers", type=int, default=4, help="concurrent contests (default 4)")
    ap.add_argument("--delay", type=float, default=0.25, help="minimum seconds between requests (default 0.25)")
    ap.add_argument("--force", action="store_true", help="re-download even if cached")
    ap.add_argument("--difficulty", type=Path, default=HERE / "difficulty.json")
    args = ap.parse_args(argv)

    if args.contests:
        contests = [parse_contest_id(c.strip()) for c in args.contests.split(",") if c.strip()]
    elif args.years:
        contests = all_contests(args.years[0], args.years[1])
    else:
        contests = all_contests()

    bands = load_difficulty(args.difficulty)
    fetcher = Fetcher(args.cache, args.delay, args.force)
    report: dict = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contests_requested": [c.id for c in contests],
        "contests_skipped": [],
        "missing_answer_keys": [],
        "incomplete_answer_keys": [],
        "missing_problems": [],
        "missing_answers": [],
        "answer_mismatches": [],
        "unsplit_choices": [],
        "uncategorized": [],
        "warnings": [],
    }

    out_dir: Path = args.out
    (out_dir / "solutions").mkdir(parents=True, exist_ok=True)

    # Skip contests that do not exist yet (future years): one cheap probe each.
    live: list[Contest] = []
    for c in contests:
        if fetcher.parse_page(c.answer_key_title) is None and fetcher.parse_page(c.problem_title(1)) is None:
            report["contests_skipped"].append(c.id)
            print(f"skip {c.name}: not on the wiki", file=sys.stderr)
        else:
            live.append(c)

    started = time.monotonic()
    all_problems: list[dict] = []
    contest_meta: list[dict] = []
    lock = threading.Lock()

    def work(c: Contest) -> None:
        t0 = time.monotonic()
        problems, solutions = scrape_contest(c, fetcher, bands, report)
        (out_dir / "solutions" / f"{c.id}.json").write_text(
            json.dumps(solutions, ensure_ascii=False), encoding="utf-8")
        with lock:
            all_problems.extend(problems)
            contest_meta.append({"id": c.id, "name": c.name, "year": c.year, "fall": c.fall,
                                 "version": c.version, "url": c.url, "problem_count": len(problems)})
        print(f"{c.name}: {len(problems)} problems in {time.monotonic() - t0:.1f}s", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(work, live))

    def sort_key(p: dict):
        return (p["year"], p["fall"], p["version"], p["number"])

    all_problems.sort(key=sort_key)
    contest_meta.sort(key=lambda c: (c["year"], c["fall"], c["version"]))
    for key in ("missing_problems", "missing_answers", "unsplit_choices", "uncategorized"):
        report[key].sort()

    index = {
        "generated_at": report["generated_at"],
        "source": "https://artofproblemsolving.com/wiki/",
        "contests": contest_meta,
        "problems": all_problems,
    }
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n{len(all_problems)} problems from {len(contest_meta)} contests "
        f"({fetcher.requests_made} requests, {time.monotonic() - started:.0f}s)\n"
        f"  unsplit choices: {len(report['unsplit_choices'])}\n"
        f"  uncategorized:   {len(report['uncategorized'])}\n"
        f"  missing answers: {len(report['missing_answers'])}\n"
        f"  answer mismatches (key vs boxed): {len(report['answer_mismatches'])}\n"
        f"  missing problem pages: {len(report['missing_problems'])}\n"
        f"  details: {out_dir / 'report.json'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
