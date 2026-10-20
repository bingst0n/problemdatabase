import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from contests import Contest, all_contests, parse_contest_id  # noqa: E402
from parse import (  # noqa: E402
    boxed_letter, guess_categories, image_urls, map_categories, parse_answer_key, parse_problem_page,
    rewrite_image_srcs, split_choices, strip_math_delims,
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

    def test_doubled_brace_labels(self):
        tex = (r"\textbf{(A)}\ -20\qquad\textbf{{(B)}}\ -15\qquad\textbf{{(C)}}\ -10\qquad"
               r"\textbf{{(D)}}\ 0\qquad\textbf{{(E)}}\ 2")
        self.assertEqual([c.tex for c in split_choices(tex)], ["-20", "-15", "-10", "0", "2"])

    def test_unbalanced_body_returns_none(self):
        # A label the regex only half-matches would leave brace debris in the bodies.
        tex = r"\textbf{(A)}\ 1\qquad\textbf{[(B)}}\ 2\qquad\textbf{(C)}\ 3\qquad\textbf{(D)}\ 4\qquad\textbf{(E)}\ 5"
        self.assertIsNone(split_choices(tex))

    def test_label_sharing_text_group_with_body(self):
        tex = r"\text{(A)}\ 0 \qquad \text{(B)}\ 1 \qquad \text{(C)}\ 2 \qquad \text{(D)}\ 4 \qquad \text{(E) more than 4}"
        self.assertEqual([c.tex for c in split_choices(tex)], ["0", "1", "2", "4", r"\text{more than 4}"])

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


class GuessCategories(unittest.TestCase):
    def test_guesses(self):
        cases = [
            ("How many positive integers less than 1000 are divisible by 7 but not by 11?", ["number_theory"]),
            ("A fair 6-sided die is rolled twice. What is the probability that the sum of the two rolls is 7?", ["probability"]),
            ("Triangle ABC has AB = 5, BC = 12, and a right angle at B. What is the area of \\triangle ABC?", ["geometry"]),
            ("What is the value of 2x + 3 when x = 4?", ["algebra"]),
            ("In how many ways can 5 people be seated in a row of 5 chairs?", ["combinatorics"]),
            ("What is \\sin 30^\\circ + \\cos 60^\\circ?", ["other"]),
            ("What is the sum of the digits of the smallest perfect square that is a multiple of 12?", ["number_theory"]),
        ]
        for text, want in cases:
            self.assertEqual(guess_categories(text), want, text)

    def test_no_hints_falls_to_other(self):
        self.assertEqual(guess_categories("What is 2+2?"), ["other"])
        self.assertEqual(guess_categories(""), ["other"])

    def test_solution_text_used_only_when_statement_scores_zero(self):
        sol = "Each outcome has probability 1/6, so the expected value is 3.5."
        self.assertEqual(guess_categories("What is 2+2?", fallback_text=sol), ["probability"])
        self.assertEqual(guess_categories("A triangle has base 10 and height 4. What is its area?",
                                          fallback_text=sol), ["geometry"])
        self.assertEqual(guess_categories("What is 2+2?", fallback_text="Add them."), ["other"])

    def test_diagram_nudges_geometry(self):
        self.assertEqual(guess_categories("Find the shaded region.", has_diagram=True), ["geometry"])


class ImageHelpers(unittest.TestCase):
    HTML = ('<p><img alt="diagram" class="diagram" src="https://latex.artofproblemsolving.com/a/b/c/abc.png"/>'
            ' <img alt="x" src="https://artofproblemsolving.com/wiki/images/1/2/pic.png"/>'
            ' <img alt="local" src="data/img/already.png"/></p>')

    def test_image_urls(self):
        self.assertEqual(image_urls(self.HTML), [
            "https://latex.artofproblemsolving.com/a/b/c/abc.png",
            "https://artofproblemsolving.com/wiki/images/1/2/pic.png",
        ])
        self.assertEqual(image_urls(""), [])

    def test_rewrite(self):
        out = rewrite_image_srcs(self.HTML, {"https://latex.artofproblemsolving.com/a/b/c/abc.png": "data/img/abc.png"})
        self.assertIn('src="data/img/abc.png"', out)
        self.assertIn('src="https://artofproblemsolving.com/wiki/images/1/2/pic.png"', out)  # unmapped stays
        self.assertIn('src="data/img/already.png"', out)


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


class NestedSolutions(unittest.TestCase):
    @staticmethod
    def page(body):
        return ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2><p>What is 1+1?</p>'
                + body + '<h2><span class="mw-headline">See Also</span></h2><p>Preceded by</p></div>')

    @staticmethod
    def h(level, text):
        return f'<h{level}><span class="mw-headline">{text}</span></h{level}>'

    def test_wrapper_with_empty_lead_is_split(self):
        p = parse_problem_page(self.page(
            self.h(2, "Solutions") + "\n" + self.h(3, "Solution 1") + "<p>one</p>"
            + self.h(3, "Solution 2 (Trig)") + "<p>two</p>" + self.h(3, "Video Solution") + "<p>vid</p>"
            + self.h(2, "Solution 5") + "<p>five</p>"), [])
        self.assertEqual([s.heading for s in p.solutions],
                         ["Solution 1", "Solution 2 (Trig)", "Video Solution", "Solution 5"])
        self.assertEqual(p.solutions[1].html, "<p>two</p>")

    def test_real_lead_kept_before_h3_solutions(self):
        p = parse_problem_page(self.page(
            self.h(2, "Solution 3") + "<p>lead</p>" + self.h(3, "Solution 4") + "<p>four</p>"
            + self.h(3, "Solution 5 (Brute Force)") + "<p>five</p>"), [])
        self.assertEqual([s.heading for s in p.solutions], ["Solution 3", "Solution 4", "Solution 5 (Brute Force)"])
        self.assertEqual(p.solutions[0].html, "<p>lead</p>")

    def test_other_h3_stays_inside(self):
        p = parse_problem_page(self.page(
            self.h(2, "Solution 1") + "<p>lead</p>" + self.h(3, "Note") + "<p>note</p>"
            + self.h(2, "Solution 2") + "<p>x</p>" + self.h(3, "Case 1") + "<p>c1</p>"
            + self.h(3, "Solution 3") + "<p>three</p>"), [])
        self.assertEqual([s.heading for s in p.solutions], ["Solution 1", "Solution 2", "Solution 3"])
        self.assertIn("<h3>Note</h3>", p.solutions[0].html)
        self.assertIn("<p>note</p>", p.solutions[0].html)
        self.assertIn("<h3>Case 1</h3>", p.solutions[1].html)
        self.assertNotIn("three", p.solutions[1].html)

    def test_h3_solutions_under_problem_heading(self):
        html = ('<div class="mw-parser-output">' + self.h(2, "Problem") + '<p>Find P.</p>'
                '<p><img class="latex" alt="$\\textbf{(A) } 1 \\qquad\\textbf{(B) } 2 \\qquad\\textbf{(C) } 3'
                ' \\qquad\\textbf{(D) } 4 \\qquad\\textbf{(E) } 5$"/></p>'
                + self.h(3, "Solution 1") + '<p><img class="latex" alt="$P = \\boxed{\\textbf{(B) } 2}$"/></p>'
                + self.h(3, "Solution 2") + "<p>two</p>" + self.h(2, "Solution 3") + "<p>three</p></div>")
        p = parse_problem_page(html, [])
        self.assertEqual([s.heading for s in p.solutions], ["Solution 1", "Solution 2", "Solution 3"])
        self.assertEqual([c.tex for c in p.choices], ["1", "2", "3", "4", "5"])
        self.assertNotIn("<h3", p.statement_html)
        self.assertEqual(p.statement_text, "Find P.")
        self.assertEqual(p.boxed_answer, "B")

    def test_variant_h3_ends_statement(self):
        # 2024 AMC 10B #3: a variant problem (with its own choices) under the Problem heading.
        def choices(n):
            return ('<p><img class="latex" alt="$\\textbf{(A) } 1 \\qquad\\textbf{(B) } 2 \\qquad\\textbf{(C) } 3'
                    ' \\qquad\\textbf{(D) } 4 \\qquad\\textbf{(E) } ' + n + '$"/></p>')
        html = ('<div class="mw-parser-output">' + self.h(2, "Problem") + '<p>Find P.</p>' + choices("5")
                + self.h(3, "Modified Problem in Certain China Testpapers") + '<p>Find Q.</p>' + choices("9")
                + self.h(3, "Solution for Certain China Testpapers") + "<p>q</p>"
                + self.h(2, "Solution 1") + "<p>one</p></div>")
        p = parse_problem_page(html, [])
        self.assertEqual(p.statement_text, "Find P.")
        self.assertEqual([c.tex for c in p.choices], ["1", "2", "3", "4", "5"])
        self.assertEqual([s.heading for s in p.solutions],
                         ["Modified Problem in Certain China Testpapers", "Solution for Certain China Testpapers",
                          "Solution 1"])
        self.assertIn("Find Q.", p.solutions[0].html)
        self.assertIn("(E) } 9", p.solutions[0].html)

    def test_diagram_and_note_h3_stay_in_statement(self):
        html = ('<div class="mw-parser-output">' + self.h(2, "Problem") + '<p>Find P.</p>'
                + self.h(3, "Three-Dimensional Diagram") + '<p>pic</p>' + self.h(3, "Diagrams") + '<p>moved</p>'
                + self.h(3, "Note") + '<p>careful</p>' + self.h(3, "Solution 1") + "<p>one</p></div>")
        p = parse_problem_page(html, [])
        self.assertIn("<h3>Three-Dimensional Diagram</h3><p>pic</p>", p.statement_html)
        self.assertIn("<h3>Diagrams</h3><p>moved</p>", p.statement_html)
        self.assertIn("<h3>Note</h3><p>careful</p>", p.statement_html)
        self.assertEqual([s.heading for s in p.solutions], ["Solution 1"])


class ProseChoices(unittest.TestCase):
    @staticmethod
    def img(tex):
        return f'<img class="latex" alt="${tex}$"/>'

    @classmethod
    def label(cls, letter):
        return cls.img(r"\textbf{(" + letter + ") }")

    def test_label_images_followed_by_prose(self):
        rows = ["It is a negative number ending with a 1.", "It is a positive number ending with a 1.",
                "It is a negative number ending with a 5.", "It is 50% of " + self.img("x^2") + " & more.",
                "It is a negative number ending with a 0."]
        body = "".join(f"\n{self.label(l)} {r} <br/>" for l, r in zip("ABCDE", rows))
        html = ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>'
                '<p>What is greater than ' + self.img("-2015") + "?\n<br/>" + body + "\n</p>"
                '<h2><span class="mw-headline">Solution</span></h2><p>' + self.img("\\boxed{\\textbf{(C)}}")
                + "</p></div>")
        p = parse_problem_page(html, [])
        self.assertEqual([c.label for c in p.choices], list("ABCDE"))
        self.assertEqual(p.choices[0].tex, r"\text{It is a negative number ending with a 1.}")
        self.assertEqual(p.choices[3].tex, r"\text{It is 50\% of } x^2 \text{ \& more.}")
        self.assertNotIn("(A)", p.statement_html)
        self.assertNotIn("negative", p.statement_html)
        self.assertEqual(p.statement_html.replace("\n", ""), '<p>What is greater than <span class="tex">-2015</span>?</p>')
        self.assertEqual(p.boxed_answer, "C")
        self.assertEqual(p.warnings, [])

    def test_each_label_in_its_own_paragraph(self):
        rows = ["Liliane has " + self.img(str(n) + "\\%") + " more soda than Alice." for n in (20, 25, 45, 75, 100)]
        body = "".join(f"<p>{self.label(l)} {r}\n</p>" for l, r in zip("ABCDE", rows))
        html = ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>'
                '<p>Who has more soda?\n</p>' + body
                + '<h2><span class="mw-headline">Solution</span></h2><p>' + self.img("\\boxed{\\textbf{(A)}}")
                + "</p></div>")
        p = parse_problem_page(html, [])
        self.assertEqual([c.label for c in p.choices], list("ABCDE"))
        self.assertEqual(p.choices[0].tex, r"\text{Liliane has } 20\% \text{ more soda than Alice.}")
        self.assertEqual(p.statement_html.replace("\n", ""), "<p>Who has more soda?</p>")

    def test_own_paragraphs_must_be_consecutive(self):
        body = "".join(f"<p>{self.label(l)} choice {l}</p>" + ("<p>gap</p>" if l == "B" else "")
                       for l in "ABCDE")
        html = ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>'
                '<p>Pick one.</p>' + body + "</div>")
        p = parse_problem_page(html, [])
        self.assertIsNone(p.choices)
        self.assertIn("choice E", p.statement_html)


class TrailingLabelChoices(unittest.TestCase):
    def test_last_label_body_follows_the_math(self):
        # 2025 AMC 10A #9: the (E) label closes the image; its body is the rest of the paragraph.
        tex = r"\textbf{(A) } 1 \qquad\textbf{(B) } 2 \qquad\textbf{(C) } 3 \qquad\textbf{(D) } 4 \qquad\textbf{(E) }"
        html = ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>'
                '<p>For how many <img class="latex" alt="$a$"/>?\n</p>'
                f'<p><img class="latex" alt="${tex}$"/>more than <img class="latex" alt="$4$"/>\n</p>'
                '<h2><span class="mw-headline">Solution</span></h2><p><img class="latex" alt="$\\boxed{\\textbf{(D) } 4}$"/></p></div>')
        p = parse_problem_page(html, [])
        self.assertEqual([c.tex for c in p.choices], ["1", "2", "3", "4", r"\text{more than } 4"])
        self.assertEqual(p.statement_html.replace("\n", ""), '<p>For how many <span class="tex">a</span>?</p>')
        self.assertEqual(p.warnings, [])


class LowercaseLabelTypo(unittest.TestCase):
    def test_lowercase_label_retried(self):
        tex = r"\textbf{(a) } \frac16 \qquad \textbf{(B) }\frac15 \qquad \textbf{(C) } \frac14 \qquad \textbf{(D) } \frac13 \qquad \textbf{(E) } \frac12"
        self.assertIsNone(split_choices(tex))
        got = [(c.label, c.tex) for c in split_choices(tex, ignore_case=True)]
        self.assertEqual(got, [("A", r"\frac16"), ("B", r"\frac15"), ("C", r"\frac14"), ("D", r"\frac13"), ("E", r"\frac12")])
        html = ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2><p>Probability?</p>'
                f'<p><img class="latex" alt="${tex}$"/></p></div>')
        p = parse_problem_page(html, [])
        self.assertEqual([c.label for c in p.choices], list("ABCDE"))
        self.assertEqual(p.statement_text, "Probability?")


class EscapedDollarAlt(unittest.TestCase):
    def test_unclosed_escaped_dollar(self):
        self.assertEqual(strip_math_delims(r"$\$"), (r"\$", False))
        self.assertEqual(strip_math_delims(r"$5\$"), (r"5\$", False))
        self.assertEqual(strip_math_delims(r"$\$5$"), (r"\$5", False))  # properly closed: unchanged
        self.assertEqual(strip_math_delims(r"$a\\$"), (r"a\\", False))  # '\\' is a line break, '$' closes
        html = ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>'
                '<p>A pill costs <img class="latex" alt="$\\$"/><img class="latex" alt="$1$"/> more.</p></div>')
        self.assertIn('<span class="tex">\\$</span><span class="tex">1</span>', parse_problem_page(html, []).statement_html)


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


class SectioningVariants(unittest.TestCase):
    def test_note_before_solutions_is_statement_and_sections_after_see_also_are_kept(self):
        html = '''<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>
<p>Find x. <img class="latex" alt="$\\textbf{(A) } 1 \\qquad \\textbf{(B) } 2 \\qquad \\textbf{(C) } 3 \\qquad \\textbf{(D) } 4 \\qquad \\textbf{(E) } 5$"/></p>
<h2><span class="mw-headline">Note</span></h2><p>The figure is not to scale.</p>
<h2><span class="mw-headline">Solution 1</span></h2><p>Answer <img class="latex" alt="$\\boxed{\\textbf{(C) } 3}$"/>.</p>
<h2><span class="mw-headline">Remark</span></h2><p>A remark.</p>
<h2><span class="mw-headline">See Also</span></h2><table><tr><td>Preceded by</td></tr></table>
<h2><span class="mw-headline">Video Solution</span></h2><p><a href="https://youtu.be/x">video</a></p></div>'''
        p = parse_problem_page(html, [])
        self.assertIn("not to scale", p.statement_text)
        self.assertEqual([s.heading for s in p.solutions], ["Solution 1", "Remark", "Video Solution"])
        self.assertNotIn("Preceded by", json.dumps([s.html for s in p.solutions]))
        self.assertIn("kept section after See Also: Video Solution", p.warnings)
        self.assertEqual(p.boxed_answer, "C")

    def test_section_after_see_also_is_cut_at_nav_box_and_maa_notice(self):
        nav = ('<table class="wikitable"><tr><td>Preceded&#160;by<br/>Problem 3</td><td>Followed&#160;by<br/>Problem 5</td></tr>'
               '<tr><td><a href="/wiki/index.php?title=AMC_10_Problems_and_Solutions"> All AMC 10 Problems and Solutions</a></td></tr></table>')
        maa = ('<div class="print"><div><div><p><a href="/wiki/index.php?title=File:AMC_Logo.png">'
               '<img src="https://artofproblemsolving.com/wiki/images/d/d1/AMC_Logo.png"/></a></p></div>'
               '<div><p>These problems are copyrighted &#169; by the <a href="https://www.maa.org">Mathematical Association of America</a>.</p></div></div></div>')
        html = ('<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2><p>Q</p>'
                '<h2><span class="mw-headline">Solution</span></h2><p>x</p>'
                '<h2><span class="mw-headline">See also</span></h2>' + nav +
                '<h2><span class="mw-headline">Video Solution</span></h2><p><a href="https://youtu.be/x">video</a></p>'
                '<p>by someone</p>' + maa + nav + '</div>')
        p = parse_problem_page(html, [])
        self.assertEqual([s.heading for s in p.solutions], ["Solution", "Video Solution"])
        video = p.solutions[1].html
        self.assertIn("youtu.be/x", video)
        self.assertIn("by someone", video)
        for junk in ("AMC_Logo", "Mathematical Association", "Preceded", "Followed", "All AMC 10"):
            self.assertNotIn(junk, video)

    def test_redirect_notice_under_problem_heading_is_dropped(self):
        html = '''<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>
<p>The following problem is from both the 2019 AMC 10A #13 and 2019 AMC 12A #10, so both problems redirect to this page.</p>
<p>Real statement.</p><h2><span class="mw-headline">Solution</span></h2><p>x</p></div>'''
        p = parse_problem_page(html, [])
        self.assertEqual(p.statement_text, "Real statement.")

    def test_nested_solutions_are_split_by_h3_but_cases_are_not(self):
        html = '''<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2><p>Q</p>
<h2><span class="mw-headline">Solutions</span></h2>
<h3><span class="mw-headline">Solution 1</span></h3><p>First.</p>
<h3><span class="mw-headline">Solution 2 (Fast)</span></h3><p>Second.</p>
<h2><span class="mw-headline">Solution 3 (Casework)</span></h2>
<h3><span class="mw-headline">Case 1</span></h3><p>c1</p><h3><span class="mw-headline">Case 2</span></h3><p>c2</p></div>'''
        p = parse_problem_page(html, [])
        self.assertEqual([s.heading for s in p.solutions], ["Solution 1", "Solution 2 (Fast)", "Solution 3 (Casework)"])
        self.assertIn("First.", p.solutions[0].html)
        self.assertIn("<h3>Case 1</h3>", p.solutions[2].html)

    def test_unsplit_choices_fallback_keeps_the_whole_line(self):
        html = '''<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>
<p>Which figure? <img class="latex" alt="$\\textbf{(A)}$"/> <img class="asy-image" alt="[asy]a[/asy]" src="//latex.artofproblemsolving.com/a.png"/>
<img class="latex" alt="$\\textbf{(B)}$"/> <img class="asy-image" alt="[asy]b[/asy]" src="//latex.artofproblemsolving.com/b.png"/>
<img class="latex" alt="$\\textbf{(C)}$"/> <img class="latex" alt="$\\textbf{(D)}$"/> <img class="latex" alt="$\\textbf{(E)}$"/></p>
<h2><span class="mw-headline">Solution</span></h2><p>x</p></div>'''
        p = parse_problem_page(html, [])
        self.assertIsNone(p.choices)
        for letter in "ABCDE":
            self.assertIn("(%s)" % letter, p.choices_tex)
        self.assertIn("(A)", p.statement_html)  # nothing was removed from the statement

    def test_fragment_and_script_links_are_unwrapped(self):
        html = '''<div class="mw-parser-output"><h2><span class="mw-headline">Problem</span></h2>
<p>See <a href="#Solution_2">below</a>, <a href="javascript:alert(1)">this</a>, <a href="/wiki/index.php/Circle">circle</a>
and <img src="data:image/png;base64,AAAA" alt="x"/>.</p><h2><span class="mw-headline">Solution</span></h2><p>x</p></div>'''
        p = parse_problem_page(html, [])
        self.assertNotIn("#Solution_2", p.statement_html)
        self.assertNotIn("javascript:", p.statement_html)
        self.assertNotIn("data:", p.statement_html)
        self.assertIn("below", p.statement_html)
        self.assertIn('<a href="https://artofproblemsolving.com/wiki/index.php/Circle">circle</a>', p.statement_html)


class CategoryMappingMore(unittest.TestCase):
    def test_contest_categories_are_not_subjects(self):
        self.assertEqual(map_categories(["AMC 10 Problems", "Introductory Geometry Problems"]), ["geometry"])
        self.assertEqual(map_categories(["AMC 10 Problems"]), [])
        self.assertEqual(map_categories(["2019 AMC 10A Problems", "AMC Problems"]), [])
        self.assertEqual(map_categories(["Intermediate Number Theory Problems"]), ["number_theory"])


class GuessCategoriesMore(unittest.TestCase):
    def test_review_cases(self):
        cases = [
            ("What is the value of \\log_2 32 + \\log_{10} 1000?", ["algebra"]),
            ("A triangle has base 10 and height 4. What is its area?", ["geometry"]),
            ("How many positive integers less than 50 can be written as the sum of two squares?", ["number_theory"]),
            ("Mary has 20 coins, all nickels and dimes, worth $1.65 in total. How many dimes does she have?", ["algebra"]),
            ("A bag has 10 red and 6 blue balls. What is the smallest number of balls that must be drawn to guarantee 3 of one color?", ["combinatorics"]),
            ("A knight is on a chessboard. In how many ways can the knight reach the opposite corner in 4 moves?", ["combinatorics"]),
        ]
        for text, want in cases:
            self.assertEqual(guess_categories(text), want, text)

    def test_boilerplate_and_weak_words_do_not_decide(self):
        self.assertNotIn("other", guess_categories("Which of the following statements is true for all real numbers x and y?"))
        # Weak words alone still yield a single best guess, never a second tag.
        self.assertEqual(len(guess_categories("Team A scored 3 points, then 2 points, then 4 points.")), 1)
        self.assertNotIn("geometry", guess_categories("The World Series is played in 7 games."))
