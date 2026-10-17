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
