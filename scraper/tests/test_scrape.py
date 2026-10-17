"""End-to-end test of scrape.py with a fake fetcher that serves the fixtures
(no network)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import scrape  # noqa: E402

FIX = HERE / "fixtures"
PAGE = (FIX / "problem_page.html").read_text(encoding="utf-8")
PAGE_OLD = (FIX / "problem_page_old.html").read_text(encoding="utf-8")
KEY = (FIX / "answer_key.html").read_text(encoding="utf-8")


class FakeFetcher:
    """Serves the two fixture pages for 2019 AMC 10A (problem 13 is the new-style
    page with a diagram, everything else the old-style page) and nothing for
    any other contest."""

    def __init__(self, *a, **k):
        self.requests_made = 0
        self.images_downloaded = 0
        self.image_requests = []

    def parse_page(self, title):
        self.requests_made += 1
        if not title.startswith("2019 AMC 10A"):
            return None
        if title.endswith("Answer Key"):
            return {"title": title, "text": KEY, "categories": []}
        if title.endswith("Problem 13"):
            return {"title": "2019 AMC 12A Problems/Problem 10", "text": PAGE,
                    "categories": [{"category": "Introductory_Geometry_Problems"}]}
        if title.endswith("Problem 7"):
            return None  # a missing page
        if title.endswith("Problem 2"):
            text = PAGE_OLD.replace("A set of tiles numbered 1 through 100 is modified repeatedly. How many times must the operation be performed to reduce the number of tiles in the set to one?",
                                    "How many positive integers less than 100 are divisible by 6 but not by 4?")
            return {"title": title, "text": text, "categories": []}
        return {"title": title, "text": PAGE_OLD, "categories": []}

    def fetch_image(self, url, img_dir):
        self.image_requests.append(url)
        if "fail" in url:
            return None
        name = "img_" + str(abs(hash(url)) % 10**8) + ".png"
        (img_dir / name).write_bytes(b"\x89PNG fake")
        self.images_downloaded += 1
        return name


class ScrapeEndToEnd(unittest.TestCase):
    def setUp(self):
        self._real = scrape.Fetcher
        scrape.Fetcher = FakeFetcher
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "data"
        self.overrides = Path(self.tmp.name) / "overrides.json"
        self.overrides.write_text(json.dumps({"_comment": "x", "2019_AMC_10A_5": ["combinatorics", "probability"]}))

    def tearDown(self):
        scrape.Fetcher = self._real
        self.tmp.cleanup()

    def run_main(self, *extra):
        rc = scrape.main(["--out", str(self.out), "--cache", str(Path(self.tmp.name) / "cache"),
                          "--years", "2019-2020", "--workers", "2", "--overrides", str(self.overrides), *extra])
        self.assertEqual(rc, 0)
        index = json.loads((self.out / "index.json").read_text())
        report = json.loads((self.out / "report.json").read_text())
        return index, report

    def test_full_run(self):
        index, report = self.run_main()
        self.assertEqual([c["id"] for c in index["contests"]], ["2019_AMC_10A"])
        self.assertEqual(sorted(report["contests_skipped"]), ["2019_AMC_10B", "2020_AMC_10A", "2020_AMC_10B"])
        self.assertEqual(len(index["problems"]), 24)
        self.assertEqual(report["missing_problems"], ["2019_AMC_10A_7"])

        by_id = {p["id"]: p for p in index["problems"]}
        p13 = by_id["2019_AMC_10A_13"]
        self.assertEqual(p13["answer"], "D")
        self.assertEqual(p13["answer_source"], "answer_key")
        self.assertEqual(p13["redirected_to"], "2019 AMC 12A Problems/Problem 10")
        self.assertEqual(p13["categories"], ["geometry"])
        self.assertEqual(p13["category_source"], "wiki")
        self.assertEqual(p13["difficulty"], 2.5)
        self.assertEqual([c["tex"] for c in p13["choices"]], ["90", "100", "105", "110", "120"])
        self.assertEqual(p13["solution_count"], 3)
        # diagram downloaded and rewritten to a local path
        self.assertIn('src="data/img/img_', p13["statement_html"])
        self.assertNotIn("latex.artofproblemsolving.com", p13["statement_html"])
        self.assertTrue(list((self.out / "img").glob("img_*.png")))
        manifest = json.loads((self.out / "images.json").read_text())
        self.assertEqual(list(manifest.values()), ["https://latex.artofproblemsolving.com/0/0/0/000asy.png"])

        p5 = by_id["2019_AMC_10A_5"]
        self.assertEqual(p5["categories"], ["combinatorics", "probability"])
        self.assertEqual(p5["category_source"], "override")

        p1 = by_id["2019_AMC_10A_1"]
        self.assertEqual(p1["categories"], [])  # "tiles ... how many times" is too thin to guess
        self.assertIsNone(p1["category_source"])
        self.assertIn("2019_AMC_10A_1", report["uncategorized"])
        p2 = by_id["2019_AMC_10A_2"]
        self.assertEqual(p2["categories"], ["number_theory"])
        self.assertEqual(p2["category_source"], "guessed")
        self.assertEqual([g["problem"] for g in report["guessed_categories"]], ["2019_AMC_10A_2"])
        self.assertEqual(p1["answer"], "D")  # from the answer key (fixture key says D for #1)
        # old-style pages all box C; the key says C for 5, 10, 15, 20, 25 -> 23 old pages - 5 = 18 disagreements
        self.assertEqual(len(report["answer_mismatches"]), 18)

        sols = json.loads((self.out / "solutions" / "2019_AMC_10A.json").read_text())
        self.assertEqual(len(sols), 24)
        self.assertEqual(sols["2019_AMC_10A_13"][1]["heading"], "Solution 2 (Casework)")
        self.assertEqual(report["image_failures"], [])
        self.assertEqual(report["unsplit_choices"], [])

    def test_no_images_keeps_remote_urls(self):
        index, report = self.run_main("--no-images")
        p13 = next(p for p in index["problems"] if p["id"] == "2019_AMC_10A_13")
        self.assertIn("https://latex.artofproblemsolving.com/0/0/0/000asy.png", p13["statement_html"])
        self.assertFalse((self.out / "img").exists())
        self.assertFalse((self.out / "images.json").exists())


if __name__ == "__main__":
    unittest.main()


class FailingFetcher(FakeFetcher):
    """Raises on one problem page; the run must survive it."""

    def parse_page(self, title):
        if title == "2019 AMC 10A Problems/Problem 4":
            raise RuntimeError("API error for the page: {'code': 'readonly'}")
        return super().parse_page(title)


class BlockedFetcher(FakeFetcher):
    def parse_page(self, title):
        raise scrape.BlockedError("error code: 1007")


class Robustness(unittest.TestCase):
    def setUp(self):
        self._real = scrape.Fetcher
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "data"
        self.cache = Path(self.tmp.name) / "cache"
        self.noover = Path(self.tmp.name) / "none.json"

    def tearDown(self):
        scrape.Fetcher = self._real
        self.tmp.cleanup()

    def args(self, *extra):
        return ["--out", str(self.out), "--cache", str(self.cache), "--overrides", str(self.noover),
                "--years", "2019", "--workers", "2", "--no-images", *extra]

    def test_one_bad_page_costs_one_problem(self):
        scrape.Fetcher = FailingFetcher
        self.assertEqual(scrape.main(self.args()), 0)
        index = json.loads((self.out / "index.json").read_text())
        report = json.loads((self.out / "report.json").read_text())
        ids = {p["id"] for p in index["problems"]}
        self.assertEqual(len(ids), 23)
        self.assertNotIn("2019_AMC_10A_4", ids)
        self.assertEqual([f["problem"] for f in report["failed_problems"]], ["2019_AMC_10A_4"])
        self.assertIn("readonly", report["failed_problems"][0]["error"])
        self.assertEqual(report["failed_contests"], [])
        self.assertEqual(report["missing_problems"], ["2019_AMC_10A_7"])
        self.assertFalse(list(self.out.glob("*.tmp")))

    def test_cloudflare_block_stops_the_run(self):
        scrape.Fetcher = BlockedFetcher
        with self.assertRaises(scrape.BlockedError):
            scrape.main(self.args())

    def test_limited_run_keeps_other_contests_in_index(self):
        scrape.Fetcher = FakeFetcher
        self.out.mkdir(parents=True)
        foreign = {"id": "2018_AMC_10B_1", "contest_id": "2018_AMC_10B", "year": 2018, "fall": False, "version": "B", "number": 1}
        (self.out / "index.json").write_text(json.dumps({
            "contests": [{"id": "2018_AMC_10B", "year": 2018, "fall": False, "version": "B"},
                         {"id": "2019_AMC_10A", "year": 2019, "fall": False, "version": "A", "stale": True}],
            "problems": [foreign, {"id": "2019_AMC_10A_99", "contest_id": "2019_AMC_10A", "year": 2019, "fall": False, "version": "A", "number": 99}],
        }))
        self.assertEqual(scrape.main(self.args("--contests", "2019_AMC_10A")), 0)
        index = json.loads((self.out / "index.json").read_text())
        self.assertEqual([c["id"] for c in index["contests"]], ["2018_AMC_10B", "2019_AMC_10A"])
        self.assertNotIn("stale", index["contests"][1])  # the rescraped contest replaced its old entry
        ids = [p["id"] for p in index["problems"]]
        self.assertIn("2018_AMC_10B_1", ids)
        self.assertNotIn("2019_AMC_10A_99", ids)
        self.assertEqual(len(ids), 1 + 24)


class StubResponse:
    def __init__(self, status, body, json_ok=True):
        self.status_code, self.text, self._json_ok = status, body, json_ok
        self.headers = {}
        self.content = body.encode()

    def json(self):
        if not self._json_ok:
            raise ValueError("not json")
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class CacheBehaviour(unittest.TestCase):
    """The real Fetcher with a stubbed HTTP session."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fetcher = scrape.Fetcher(Path(self.tmp.name), 0.0, False)
        self.replies = []
        self.fetcher.session.get = lambda url, params=None, timeout=None: self.replies.pop(0)
        self._sleep = scrape.time.sleep
        scrape.time.sleep = lambda s: None

    def tearDown(self):
        scrape.time.sleep = self._sleep
        self.tmp.cleanup()

    def test_only_real_pages_are_cached(self):
        self.replies = [StubResponse(200, json.dumps({"error": {"code": "missingtitle"}}))]
        self.assertIsNone(self.fetcher.parse_page("Nope"))
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])  # missing page: not cached
        self.replies = [StubResponse(200, json.dumps({"parse": {"title": "X", "text": "<p>x</p>"}}))]
        self.assertEqual(self.fetcher.parse_page("X")["title"], "X")
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 1)
        self.assertEqual(self.fetcher.parse_page("X")["title"], "X")  # served from cache, no reply consumed
        self.assertFalse(list(Path(self.tmp.name).glob("*.tmp")))

    def test_transient_error_is_not_cached_and_non_json_is_retried(self):
        self.replies = [StubResponse(200, json.dumps({"error": {"code": "readonly"}}))]
        with self.assertRaises(RuntimeError):
            self.fetcher.parse_page("Y")
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])
        self.replies = [StubResponse(200, "<html>challenge</html>", json_ok=False),
                        StubResponse(503, "busy"),
                        StubResponse(200, json.dumps({"parse": {"title": "Y", "text": ""}}))]
        self.assertEqual(self.fetcher.parse_page("Y")["title"], "Y")

    def test_corrupt_cache_file_is_refetched(self):
        (Path(self.tmp.name) / "Z.json").write_text("{truncated")
        self.replies = [StubResponse(200, json.dumps({"parse": {"title": "Z", "text": ""}}))]
        self.assertEqual(self.fetcher.parse_page("Z")["title"], "Z")

    def test_cloudflare_1007_raises_blocked(self):
        self.replies = [StubResponse(403, "error code: 1007")]
        with self.assertRaises(scrape.BlockedError):
            self.fetcher.parse_page("W")
