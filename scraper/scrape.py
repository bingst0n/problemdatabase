#!/usr/bin/env python3
"""Scrape AMC 10A/10B problems from the AoPS wiki into site/data/.

    python3 scraper/scrape.py                       # everything, 2002..this year
    python3 scraper/scrape.py --years 2019-2020     # a range of years
    python3 scraper/scrape.py --contests 2019_AMC_10A,2021_Fall_AMC_10B
    python3 scraper/scrape.py --force               # ignore the on-disk cache

Raw API responses are cached in scraper/cache/ so parser changes never
re-download. Diagrams are downloaded into site/data/img/ (skip with
--no-images). Output: site/data/index.json, site/data/solutions/<contest>.json,
site/data/images.json, site/data/report.json.

Note: AoPS sits behind Cloudflare and blocks many cloud/datacenter IP ranges
(HTTP 403 "error code: 1007"). Run this from an ordinary home connection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
from parse import (  # noqa: E402
    guess_categories, image_urls, parse_answer_key, parse_problem_page, rewrite_image_srcs,
)

HERE = Path(__file__).resolve().parent
API = "https://artofproblemsolving.com/wiki/api.php"
USER_AGENT = (
    "problemdatabase-scraper/0.1 (personal AMC study tool; "
    "https://github.com/bingst0n/problemdatabase)"
)
PROBLEMS_PER_CONTEST = 25


class Fetcher:
    """Polite MediaWiki API client with a disk cache and a global rate limit."""

    def __init__(self, cache_dir: Path, min_interval: float, force: bool, image_interval: float = 0.1):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.image_interval = image_interval
        self.force = force
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._lock = threading.Lock()
        self._last = {"api": 0.0, "image": 0.0}
        self.requests_made = 0
        self.images_downloaded = 0

    def _throttle(self, kind: str = "api") -> None:
        interval = self.min_interval if kind == "api" else self.image_interval
        with self._lock:
            wait = self._last[kind] + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[kind] = time.monotonic()
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
            if r.status_code == 403 and "error code: 1007" in r.text:
                raise RuntimeError(
                    "AoPS (Cloudflare) refuses this IP address: HTTP 403 'error code: 1007'. "
                    "Run the scraper from an ordinary home connection, not a cloud/datacenter host.")
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"gave up fetching {title!r}")

    def fetch_image(self, url: str, img_dir: Path) -> str | None:
        """Download one image into img_dir; returns the local file name, or
        None on failure. Already-downloaded files are reused."""
        ext = Path(url.split("?")[0]).suffix.lower()
        if ext not in (".png", ".gif", ".jpg", ".jpeg", ".svg", ".webp"):
            ext = ".png"
        name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ext
        path = img_dir / name
        if path.exists() and path.stat().st_size > 0:
            return name
        delay = 2.0
        for attempt in range(4):
            self._throttle("image")
            try:
                r = self.session.get(url, timeout=60)
            except requests.RequestException as e:
                if attempt == 3:
                    print(f"  image failed {url}: {e}", file=sys.stderr)
                    return None
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code != 200 or not r.content:
                print(f"  image HTTP {r.status_code} {url}", file=sys.stderr)
                return None
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(r.content)
            tmp.replace(path)
            with self._lock:
                self.images_downloaded += 1
            return name
        return None


def load_difficulty(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["bands"]


def difficulty_for(number: int, bands: list[dict]) -> tuple[float | None, str | None]:
    for b in bands:
        if b["from"] <= number <= b["to"]:
            return b["rating"], b["label"]
    return None, None


def scrape_contest(contest: Contest, fetcher: Fetcher, bands: list[dict], report: dict,
                   overrides: dict[str, list[str]], img_dir: Path | None,
                   image_manifest: dict[str, str], lock: threading.Lock) -> tuple[list[dict], dict]:
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
        categories, category_source = parsed.categories, ("wiki" if parsed.categories else None)
        if pid in overrides:
            categories, category_source = list(overrides[pid]), "override"
        elif not categories:
            choice_text = " ".join(c.tex for c in parsed.choices) if parsed.choices else (parsed.choices_tex or "")
            categories = guess_categories(parsed.statement_text + " " + choice_text,
                                          has_diagram='class="diagram"' in parsed.statement_html)
            category_source = "guessed" if categories else None
        if category_source == "guessed":
            report["guessed_categories"].append({"problem": pid, "categories": categories})
        if not categories:
            report["uncategorized"].append(pid)

        statement_html = parsed.statement_html
        solution_list = [asdict(s) for s in parsed.solutions]
        if img_dir is not None:
            urls = image_urls(statement_html)
            for s in solution_list:
                urls += [u for u in image_urls(s["html"]) if u not in urls]
            mapping: dict[str, str] = {}
            for u in urls:
                name = fetcher.fetch_image(u, img_dir)
                if name:
                    mapping[u] = "data/img/" + name
                    with lock:
                        image_manifest[name] = u
                else:
                    with lock:
                        report["image_failures"].append({"problem": pid, "url": u})
            statement_html = rewrite_image_srcs(statement_html, mapping)
            for s in solution_list:
                s["html"] = rewrite_image_srcs(s["html"], mapping)
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
            "statement_html": statement_html,
            "statement_text": parsed.statement_text,
            "choices": [asdict(c) for c in parsed.choices] if parsed.choices else None,
            "choices_tex": parsed.choices_tex,
            "answer": answer,
            "answer_source": source,
            "difficulty": rating,
            "difficulty_label": label,
            "categories": categories,
            "category_source": category_source,
            "wiki_categories": parsed.wiki_categories,
            "solution_count": len(parsed.solutions),
        })
        solutions[pid] = solution_list
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
    ap.add_argument("--overrides", type=Path, default=HERE / "category_overrides.json",
                    help="optional JSON {problem_id: [categories]} that beats wiki and guessed categories")
    ap.add_argument("--no-images", action="store_true", help="keep AoPS image URLs instead of downloading diagrams")
    ap.add_argument("--image-delay", type=float, default=0.1, help="minimum seconds between image downloads (default 0.1)")
    args = ap.parse_args(argv)

    if args.contests:
        contests = [parse_contest_id(c.strip()) for c in args.contests.split(",") if c.strip()]
    elif args.years:
        contests = all_contests(args.years[0], args.years[1])
    else:
        contests = all_contests()

    bands = load_difficulty(args.difficulty)
    overrides: dict[str, list[str]] = {}
    if args.overrides.exists():
        overrides = {k: v for k, v in json.loads(args.overrides.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    fetcher = Fetcher(args.cache, args.delay, args.force, args.image_delay)
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
        "guessed_categories": [],
        "image_failures": [],
        "warnings": [],
    }

    out_dir: Path = args.out
    (out_dir / "solutions").mkdir(parents=True, exist_ok=True)
    img_dir: Path | None = None
    image_manifest: dict[str, str] = {}
    if not args.no_images:
        img_dir = out_dir / "img"
        img_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "images.json"
        if manifest_path.exists():
            image_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

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
        problems, solutions = scrape_contest(c, fetcher, bands, report, overrides, img_dir, image_manifest, lock)
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
    if img_dir is not None:
        (out_dir / "images.json").write_text(
            json.dumps(dict(sorted(image_manifest.items())), ensure_ascii=False, indent=0), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n{len(all_problems)} problems from {len(contest_meta)} contests "
        f"({fetcher.requests_made} requests, {time.monotonic() - started:.0f}s)\n"
        f"  unsplit choices: {len(report['unsplit_choices'])}\n"
        f"  uncategorized:   {len(report['uncategorized'])} (guessed for {len(report['guessed_categories'])})\n"
        f"  images: {fetcher.images_downloaded} downloaded, {len(report['image_failures'])} failed\n"
        f"  missing answers: {len(report['missing_answers'])}\n"
        f"  answer mismatches (key vs boxed): {len(report['answer_mismatches'])}\n"
        f"  missing problem pages: {len(report['missing_problems'])}\n"
        f"  details: {out_dir / 'report.json'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
