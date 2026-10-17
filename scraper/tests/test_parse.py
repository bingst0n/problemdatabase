import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from contests import Contest, all_contests, parse_contest_id  # noqa: E402
from parse import (  # noqa: E402
    boxed_letter, map_categories, parse_answer_key, parse_problem_page, split_choices,
)

FIX = HERE / "fixtures"


class ChoiceSplitting(unittest.TestCase):
    def test_textbf_display(self):
        tex = r"\textbf{(A) } 90 \qquad\textbf{(B) } 100 \qquad\textbf{(C) } 105 \qquad\textbf{(D) } 110 \qquad\textbf{(E) } 120"
        got = [(c.label, c.tex) for c in split_choices(tex)]
        self.assertEqual(got, [("A", "90"), ("B", "100"), ("C", "105"), ("D", "110"), ("E", "120")])

    def test_mathrm_old_style(self):
        tex = r"\mathrm{(A) \ } 10 \qquad \mathrm{(B) \ } 11 \qquad \mathrm{(C) \ } 18 \qquad \mathrm{(D) \ } 19 \qquad \mathrm{(E) \ } 20"
        got = [c.tex for c in split_choices(tex)]
        self.assertEqual(got, ["10", "11", "18", "19", "20"])

    def test_text_with_fractions_and_linebreaks(self):
        tex = r"\text{(A)}\ \frac{1}{2} \qquad \text{(B)}\ \frac{2}{3} \\ \text{(C)}\ \frac{3}{4} \qquad \text{(D)}\ 1 \qquad \text{(E)}\ \frac{5}{4}"
        got = [c.tex for c in split_choices(tex)]
        self.assertEqual(got, [r"\frac{1}{2}", r"\frac{2}{3}", r"\frac{3}{4}", "1", r"\frac{5}{4}"])

    def test_parenthesised_text_label(self):
        tex = r"(\text{A})\ 5\qquad(\text{B})\ 6\qquad(\text{C})\ 7\qquad(\text{D})\ 8\qquad(\text{E})\ 9"
        got = [c.tex for c in split_choices(tex)]
        self.assertEqual(got, ["5", "6", "7", "8", "9"])

    def test_text_answers(self):
        tex = r"\textbf{(A) }\text{Monday}\qquad\textbf{(B) }\text{Tuesday}\qquad\textbf{(C) }\text{Wednesday}\qquad\textbf{(D) }\text{Thursday}\qquad\textbf{(E) }\text{Friday}"
        got = [c.tex for c in split_choices(tex)]
        self.assertEqual(got[0], r"\text{Monday}")
        self.assertEqual(got[4], r"\text{Friday}")

    def test_incomplete_returns_none(self):
        self.assertIsNone(split_choices(r"\textbf{(A) } 1 \qquad \textbf{(B) } 2"))
        self.assertIsNone(split_choices(r"x^2 + y^2 = 1"))


class BoxedAnswer(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(boxed_letter(r"\boxed{\textbf{(D) } 110}"), "D")
        self.assertEqual(boxed_letter(r"\boxed{\mathrm{(C) \ } 18}"), "C")
        self.assertEqual(boxed_letter(r"\boxed{\text{(B)}}"), "B")
        self.assertEqual(boxed_letter(r"\boxed{E}"), "E")
        self.assertEqual(boxed_letter(r"\boxed{(A)}"), "A")
        self.assertEqual(boxed_letter(r"\boxed{\textbf{(E)}\ \frac{1}{2}}"), "E")
        self.assertIsNone(boxed_letter(r"\boxed{42}"))


class Categories(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(map_categories(["Introductory_Geometry_Problems"]), ["geometry"])
        self.assertEqual(
            map_categories(["Introductory Number Theory Problems", "Introductory Algebra Problems"]),
            ["algebra", "number_theory"],
        )
        self.assertEqual(map_categories(["Introductory Trigonometry Problems"]), ["other"])
        self.assertEqual(map_categories(["Introductory Probability Problems", "Introductory Combinatorics Problems"]),
                         ["combinatorics", "probability"])
        self.assertEqual(map_categories(["Pages with broken file links"]), [])
        self.assertEqual(map_categories([]), [])


class ProblemPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = (FIX / "problem_page.html").read_text(encoding="utf-8")
        cls.p = parse_problem_page(html, ["Introductory_Geometry_Problems"])

    def test_statement(self):
        s = self.p.statement_html
        self.assertIn('<span class="tex">\\triangle ABC</span>', s)
        self.assertNotIn("redirect to this page", s)
        self.assertNotIn("mw-editsection", s)
        self.assertNotIn("(A)", s)  # choices removed from the statement
        self.assertIn('<img alt="diagram" class="diagram"', s)  # Diagram section kept with the statement
        self.assertIn("https://latex.artofproblemsolving.com/0/0/0/000asy.png", s)
        self.assertNotIn("<h2", s)
        self.assertTrue(self.p.statement_text.startswith("Let \\triangle ABC be an isosceles triangle"))

    def test_choices(self):
        self.assertEqual([c.tex for c in self.p.choices], ["90", "100", "105", "110", "120"])
        self.assertIn(r"\textbf{(A) } 90", self.p.choices_tex)

    def test_solutions(self):
        heads = [s.heading for s in self.p.solutions]
        self.assertEqual(heads, ["Solution 1", "Solution 2 (Casework)", "Video Solution"])
        sol2 = self.p.solutions[1].html
        self.assertIn("<h3>Case 1</h3>", sol2)
        self.assertIn('<div class="tex-display">\\angle BFC = 180^\\circ - 70^\\circ = 110^\\circ.</div>', sol2)
        self.assertIn('<a href="https://artofproblemsolving.com/wiki/index.php/Inscribed_angle">wiki link</a>', sol2)
        self.assertIn("<table><tbody><tr><th>x</th>", sol2)
        self.assertNotIn("wikitable", sol2)
        self.assertIn('href="https://youtu.be/abcdefghijk"', self.p.solutions[2].html)
        self.assertNotIn('class="external', self.p.solutions[2].html)

    def test_see_also_dropped(self):
        for s in self.p.solutions:
            self.assertNotIn("Preceded by", s.html)
            self.assertNotIn("copyrighted", s.html)
        self.assertNotIn("NewPP", json.dumps([s.html for s in self.p.solutions]))

    def test_boxed_and_categories(self):
        self.assertEqual(self.p.boxed_answer, "D")
        self.assertEqual(self.p.categories, ["geometry"])
        self.assertEqual(self.p.wiki_categories, ["Introductory Geometry Problems"])
        self.assertEqual(self.p.warnings, [])


class OldProblemPage(unittest.TestCase):
    def test_inline_choices_and_numbered_heading(self):
        html = (FIX / "problem_page_old.html").read_text(encoding="utf-8")
        p = parse_problem_page(html, [])
        self.assertEqual([c.tex for c in p.choices], ["10", "11", "18", "19", "20"])
        self.assertTrue(p.statement_text.startswith("A set of tiles"))
        self.assertNotIn("(A)", p.statement_html)
        self.assertEqual(p.boxed_answer, "C")
        self.assertEqual([s.heading for s in p.solutions], ["Solution"])
        self.assertEqual(p.categories, [])


class AnswerKey(unittest.TestCase):
    def test_ordered_list(self):
        key = parse_answer_key((FIX / "answer_key.html").read_text(encoding="utf-8"))
        self.assertEqual(len(key), 25)
        self.assertEqual(key[1], "D")
        self.assertEqual(key[13], "D")
        self.assertEqual(key[25], "C")

    def test_plain_lines(self):
        html = "<div class='mw-parser-output'><p>" + "<br/>".join(f"{i}. {'ABCDE'[i % 5]}" for i in range(1, 26)) + "</p></div>"
        key = parse_answer_key(html)
        self.assertEqual(len(key), 25)
        self.assertEqual(key[7], "C")


class Contests(unittest.TestCase):
    def test_titles(self):
        c = Contest(2019, "A")
        self.assertEqual(c.id, "2019_AMC_10A")
        self.assertEqual(c.problem_title(13), "2019 AMC 10A Problems/Problem 13")
        self.assertEqual(c.answer_key_title, "2019 AMC 10A Answer Key")
        f = Contest(2021, "B", fall=True)
        self.assertEqual(f.id, "2021_Fall_AMC_10B")
        self.assertEqual(f.problem_title(1), "2021 Fall AMC 10B Problems/Problem 1")
        self.assertEqual(f.url, "https://artofproblemsolving.com/wiki/index.php/2021_Fall_AMC_10B_Problems")

    def test_listing_and_ids(self):
        cs = all_contests(2002, 2025)
        self.assertEqual(len(cs), 24 * 2 + 2)
        self.assertEqual(parse_contest_id("2021_Fall_AMC_10B"), Contest(2021, "B", True))
        self.assertEqual(parse_contest_id("2019_AMC_10A"), Contest(2019, "A"))


if __name__ == "__main__":
    unittest.main()
