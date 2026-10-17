"""Turn the AoPS wiki's rendered HTML for a problem page into structured data.

Everything here is pure (no network): it takes the `text` field of a MediaWiki
`action=parse` response and the page's category list, and returns the problem
statement, answer choices, solutions and tags.

The wiki renders LaTeX as <img class="latex" alt="$...$"> (inline) or
<img class="latexcenter" alt="\\[...\\]"> (display); the alt text is the LaTeX
source. Asymptote diagrams are <img alt="[asy]...[/asy]"> with a PNG src.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

WIKI_ORIGIN = "https://artofproblemsolving.com"

# Tags kept in stored HTML. Everything else is unwrapped (children kept).
ALLOWED_TAGS = {
    "p", "br", "b", "i", "u", "s", "strong", "em", "sup", "sub", "small",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tr", "td", "th", "caption",
    "a", "img", "div", "span", "h3", "h4", "h5", "pre", "code", "blockquote", "hr",
}
ALLOWED_ATTRS = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height", "class"},
    "span": {"class"},
    "div": {"class"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
# Only these class values survive on span/div (they are ours).
OWN_CLASSES = {"tex", "tex-display", "diagram"}

# Wiki category keyword -> tag. Order matters only for readability.
CATEGORY_KEYWORDS = [
    ("number theory", "number_theory"),
    ("combinatorics", "combinatorics"),
    ("probability", "probability"),
    ("geometry", "geometry"),
    ("algebra", "algebra"),
]
CATEGORY_ORDER = ["algebra", "geometry", "number_theory", "combinatorics", "probability", "other"]
_CONTEST_CATEGORY = re.compile(r"(?:\d{4}\s+(?:fall\s+|spring\s+)?)?(?:amc|aime|aimo|ajhsme|ahsme|usa|usamo|usajmo|imo|hmmt|arml|mathcounts|putnam|jbmo)\b")

_FACTORY = BeautifulSoup("", "html.parser")

_CMD = r"\\(?:textbf|mathbf|mathrm|textrm|text|bf|rm|mathit|textit|textsf|mathsf|boldsymbol)"
_SP = r"(?:\s|\\[ ,:;!])*"
LABEL_RE = re.compile(
    r"(?:"
    + _CMD + r"\s*\{" + _SP + r"\(?" + _SP + r"(?P<l1>[A-E])" + _SP + r"\)?" + _SP + r"\}"  # \textbf{(A) }
    + r"|\(\s*" + _CMD + r"\s*\{\s*(?P<l2>[A-E])\s*\}\s*\)"                                 # (\textbf{A})
    + r"|\{\s*" + _CMD + r"\s*\(?\s*(?P<l3>[A-E])\s*\)?\s*\}"                                # {\bf (A)}
    + r"|\(\s*(?P<l4>[A-E])\s*\)"                                                            # (A)
    + r")"
)
_SPACING_TOKEN = (
    r"(?:\s+|\\(?:qquad|quad|,|;|:|!|\s)|\\\\|~|\\hspace\*?\{[^}]*\}|\\phantom\{[^}]*\}"
    r"|\\vspace\*?\{[^}]*\}|\\newline|\\hfill|\\hfil)"
)
_LEADING_SPACING = re.compile(r"^(?:" + _SPACING_TOKEN + r")+")
_TRAILING_SPACING = re.compile(r"(?:" + _SPACING_TOKEN + r")+$")

PROBLEM_HEADING = re.compile(r"^\s*problem\b", re.I)
SOLUTION_HEADING = re.compile(r"solution|answer|video|method", re.I)
SEE_ALSO_HEADING = re.compile(r"^\s*see\s*also\b", re.I)
REDIRECT_NOTICE = re.compile(r"redirects? to this page|is from both the", re.I)


@dataclass
class Choice:
    label: str
    tex: str


@dataclass
class Solution:
    heading: str
    html: str


@dataclass
class ParsedProblem:
    statement_html: str
    statement_text: str
    choices: list[Choice] | None
    choices_tex: str | None
    solutions: list[Solution]
    boxed_answer: str | None
    categories: list[str]
    wiki_categories: list[str]
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- helpers

def absolutize(url: str) -> str:
    if not url:
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return WIKI_ORIGIN + url
    return url


def strip_math_delims(alt: str) -> tuple[str, bool]:
    """'$x$' -> ('x', False); '\\[x\\]' -> ('x', True)."""
    s = alt.strip()
    if len(s) >= 4 and s.startswith("$$") and s.endswith("$$"):
        return s[2:-2].strip(), True
    if len(s) >= 4 and s.startswith("\\[") and s.endswith("\\]"):
        return s[2:-2].strip(), True
    if len(s) >= 4 and s.startswith("\\(") and s.endswith("\\)"):
        return s[2:-2].strip(), False
    if len(s) >= 2 and s.startswith("$") and s.endswith("$"):
        return s[1:-1].strip(), False
    return s, False


def looks_like_math(alt: str) -> bool:
    s = alt.strip()
    return (s.startswith("$") and s.endswith("$")) or s.startswith("\\[") or s.startswith("\\(")


def is_asy(img: Tag) -> bool:
    alt = (img.get("alt") or "").strip()
    classes = " ".join(img.get("class") or [])
    return alt.startswith("[asy]") or "asy" in classes


def is_math_img(img: Tag) -> bool:
    classes = " ".join(img.get("class") or [])
    alt = img.get("alt") or ""
    return not is_asy(img) and ("latex" in classes or looks_like_math(alt))


def heading_text(h: Tag) -> str:
    span = h.find("span", class_="mw-headline")
    txt = (span or h).get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt)


def _wrap(nodes: list) -> Tag:
    box = _FACTORY.new_tag("div")
    for n in nodes:
        box.append(n)
    return box


# --------------------------------------------------------------------------- sanitizing

def _replace_img(img: Tag) -> None:
    alt = img.get("alt") or ""
    src = absolutize((img.get("src") or "").strip())
    if not src.lower().startswith(("http://", "https://")) and not is_math_img(img):
        img.decompose()
        return
    if is_asy(img):
        new = _FACTORY.new_tag("img", src=src, alt="diagram")
        new["class"] = "diagram"
        for k in ("width", "height"):
            if img.get(k):
                new[k] = img[k]
        img.replace_with(new)
    elif is_math_img(img):
        tex, display = strip_math_delims(alt)
        new = _FACTORY.new_tag("div" if display else "span")
        new["class"] = "tex-display" if display else "tex"
        new.string = tex
        img.replace_with(new)
    else:
        new = _FACTORY.new_tag("img", src=src, alt=alt)
        img.replace_with(new)


def sanitize(tag: Tag) -> None:
    """In place: drop scripts/comments/edit links, convert math images,
    unwrap unknown tags, strip attributes."""
    for child in list(tag.children):
        if isinstance(child, Comment):
            child.extract()
            continue
        if isinstance(child, NavigableString):
            continue
        name = child.name
        classes = child.get("class") or []
        if name in ("script", "style", "noscript"):
            child.decompose()
            continue
        if name == "span" and "mw-editsection" in classes:
            child.decompose()
            continue
        if name == "div" and ("toc" in classes or child.get("id") == "toc"):
            child.decompose()
            continue
        if name == "img":
            _replace_img(child)
            continue
        sanitize(child)
        if name in ALLOWED_TAGS:
            keep = ALLOWED_ATTRS.get(name, set())
            attrs = {k: v for k, v in child.attrs.items() if k in keep}
            if name in ("span", "div"):
                cls = attrs.get("class")
                if isinstance(cls, list):
                    cls = " ".join(cls)
                if cls not in OWN_CLASSES:
                    attrs.pop("class", None)
                    if not attrs and name == "span":
                        child.unwrap()
                        continue
            if "href" in attrs:
                href = absolutize((attrs["href"] or "").strip())
                if not href.lower().startswith(("http://", "https://")):
                    child.unwrap()  # in-page anchors, javascript:, mailto: ... keep the text only
                    continue
                attrs["href"] = href
            child.attrs = attrs
        else:
            child.unwrap()


def _is_blank(node) -> bool:
    if isinstance(node, Comment):
        return True
    if isinstance(node, NavigableString):
        return not str(node).strip()
    if isinstance(node, Tag):
        if node.name == "br":
            return True
        if node.name in ("img", "span", "div") and node.get("class"):
            return False
        return not node.get_text(strip=True) and not node.find("img")
    return True


def serialize(nodes: list) -> str:
    nodes = [n for n in nodes if not _is_blank(n)]
    if not nodes:
        return ""
    box = _wrap(nodes)
    sanitize(box)
    html = box.decode_contents()
    return re.sub(r"\n{2,}", "\n", html).strip()


def plain_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for d in soup.find_all("img"):
        d.replace_with(" [diagram] ")
    text = soup.get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- choices

def _label_letter(m: re.Match) -> str:
    return m.group("l1") or m.group("l2") or m.group("l3") or m.group("l4")


def find_labels(tex: str) -> list[tuple[str, int, int]] | None:
    """Positions of (A)..(E) labels in order, or None if not all five appear."""
    found = []
    expected = "A"
    for m in LABEL_RE.finditer(tex):
        letter = m.group("l1") or m.group("l2") or m.group("l3") or m.group("l4")
        if letter == expected:
            found.append((letter, m.start(), m.end()))
            if expected == "E":
                break
            expected = chr(ord(expected) + 1)
    return found if len(found) == 5 else None


def clean_choice(tex: str) -> str:
    prev = None
    while prev != tex:
        prev = tex
        tex = _LEADING_SPACING.sub("", tex)
        tex = _TRAILING_SPACING.sub("", tex)
    return tex.strip()


def split_choices(tex: str) -> list[Choice] | None:
    labels = find_labels(tex)
    if not labels:
        return None
    out = []
    for i, (letter, _start, end) in enumerate(labels):
        nxt = labels[i + 1][1] if i + 1 < len(labels) else len(tex)
        body = clean_choice(tex[end:nxt])
        if not body:
            return None
        out.append(Choice(letter, body))
    return out


def extract_choices(statement_nodes: list) -> tuple[list[Choice] | None, str | None]:
    """Find the answer-choice math in the statement, remove it from the tree,
    and return (choices, raw_tex). Tries the last math image first, then
    prepends earlier ones in case the choices span several <math> blocks."""
    candidates: list[tuple[Tag, str]] = []
    for node in statement_nodes:
        if not isinstance(node, Tag):
            continue
        imgs = [node] if node.name == "img" else node.find_all("img")
        for img in imgs:
            if not is_math_img(img):
                continue
            tex, _ = strip_math_delims(img.get("alt") or "")
            if LABEL_RE.search(tex):
                candidates.append((img, tex))
    if not candidates:
        return None, None
    for start in range(len(candidates) - 1, -1, -1):
        used = candidates[start:]
        joined = " ".join(t for _, t in used)
        choices = split_choices(joined)
        if choices:
            for img, _ in used:
                parent = img.parent
                img.decompose()
                while parent is not None and isinstance(parent, Tag) and parent.name in ("p", "div", "center", "span") \
                        and not parent.get_text(strip=True) and not parent.find(("img", "table", "ul", "ol")):
                    grand = parent.parent
                    parent.decompose()
                    parent = grand
            return choices, joined
    # Could not split; return the raw tex from the last candidate that carries
    # an (A) label onwards, so the whole choice line is displayed as one piece.
    start = 0
    for i, (_, t) in enumerate(candidates):
        if any(_label_letter(m) == "A" for m in LABEL_RE.finditer(t)):
            start = i
    return None, " ".join(t for _, t in candidates[start:])


# --------------------------------------------------------------------------- boxed answer

def _balanced(s: str, start: int) -> str | None:
    """Content of the {...} group starting at s[start] == '{'."""
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{" and (i == 0 or s[i - 1] != "\\"):
            depth += 1
        elif s[i] == "}" and (i == 0 or s[i - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return s[start + 1:i]
    return None


def boxed_letter(tex: str) -> str | None:
    for m in re.finditer(r"\\boxed\s*", tex):
        inner = _balanced(tex, m.end())
        if inner is None:
            continue
        lm = LABEL_RE.search(inner)
        if lm:
            return lm.group("l1") or lm.group("l2") or lm.group("l3") or lm.group("l4")
        bare = re.fullmatch(r"\s*\(?\s*(?:" + _CMD + r"\s*\{)?\s*([A-E])\s*\}?\s*\)?\s*", inner)
        if bare:
            return bare.group(1)
    return None


def find_boxed_answer(solution_nodes: list) -> str | None:
    for node in solution_nodes:
        if not isinstance(node, Tag):
            continue
        for img in node.find_all("img"):
            if is_math_img(img):
                tex, _ = strip_math_delims(img.get("alt") or "")
                letter = boxed_letter(tex)
                if letter:
                    return letter
        for el in node.find_all(["span", "div"], class_=["tex", "tex-display"]):
            letter = boxed_letter(el.get_text())
            if letter:
                return letter
    return None


# --------------------------------------------------------------------------- categories

def map_categories(wiki_categories: list[str]) -> list[str]:
    tags: list[str] = []
    for raw in wiki_categories:
        name = raw.replace("_", " ").strip()
        low = name.lower()
        if not low.endswith("problems"):
            continue  # maintenance categories etc.
        if _CONTEST_CATEGORY.match(low):
            continue  # "AMC 10 Problems", "2019 AMC 10A Problems": a contest, not a subject
        hit = None
        for kw, tag in CATEGORY_KEYWORDS:
            if kw in low:
                hit = tag
                break
        tags.append(hit or "other")
    uniq = [t for t in CATEGORY_ORDER if t in tags]
    return uniq


# --------------------------------------------------------------------------- sections

def split_sections(root: Tag) -> list[tuple[str | None, list]]:
    sections: list[tuple[str | None, list]] = []
    heading: str | None = None
    nodes: list = []
    for child in list(root.children):
        if isinstance(child, Tag) and child.name == "h2":
            sections.append((heading, nodes))
            heading, nodes = heading_text(child), []
        else:
            nodes.append(child)
    sections.append((heading, nodes))
    return sections


def _drop_redirect_notice(nodes: list) -> list:
    out = []
    for n in nodes:
        if isinstance(n, Tag) and n.name == "p" and REDIRECT_NOTICE.search(n.get_text(" ")):
            continue
        out.append(n)
    return out


def _split_nested_solutions(heading: str, nodes: list) -> list[tuple[str, list]]:
    """A page written as one "Solutions" h2 with "Solution 1", "Solution 2" h3
    children becomes one section per h3. Sub-headings that are not solutions
    ("Case 1" under "Solution 2 (Casework)") leave the section alone."""
    h3s = [n for n in nodes if isinstance(n, Tag) and n.name == "h3"]
    if not any(SOLUTION_HEADING.search(heading_text(h)) for h in h3s):
        return [(heading, nodes)]
    out: list[tuple[str, list]] = []
    cur_heading, cur_nodes = heading, []
    for n in nodes:
        if isinstance(n, Tag) and n.name == "h3":
            if any(not _is_blank(x) for x in cur_nodes):
                out.append((cur_heading, cur_nodes))
            cur_heading, cur_nodes = heading_text(n), []
        else:
            cur_nodes.append(n)
    if any(not _is_blank(x) for x in cur_nodes):
        out.append((cur_heading, cur_nodes))
    return out


def parse_problem_page(html: str, wiki_categories: list[str] | None = None) -> ParsedProblem:
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("div", class_="mw-parser-output") or soup.body or soup
    warnings: list[str] = []

    sections = split_sections(root)
    statement_nodes: list = []
    solution_sections: list[tuple[str, list]] = []
    phase = "lead"
    for heading, nodes in sections:
        if heading is None:
            lead = _drop_redirect_notice(nodes)
            if any(not _is_blank(n) for n in lead):
                statement_nodes.extend(lead)  # pages with no "Problem" heading
            continue
        if SEE_ALSO_HEADING.match(heading):
            phase = "after_see_also"
            continue
        if phase == "after_see_also":
            # Editors sometimes append a solution below the nav box; keep it, skip the rest.
            if SOLUTION_HEADING.search(heading):
                solution_sections.append((heading, nodes))
                warnings.append(f"kept section after See Also: {heading}")
            continue
        if phase == "lead" and PROBLEM_HEADING.match(heading):
            # A real Problem heading supersedes any lead text.
            statement_nodes = [n for n in nodes]
            phase = "statement"
            continue
        if phase in ("lead", "statement") and not SOLUTION_HEADING.search(heading):
            statement_nodes.extend(nodes)  # e.g. a "Diagram" or "Note" section before the solutions
            phase = "statement"
            continue
        phase = "solutions"
        solution_sections.append((heading, nodes))

    statement_nodes = _drop_redirect_notice(statement_nodes)
    solution_sections = [part for heading, nodes in solution_sections for part in _split_nested_solutions(heading, nodes)]

    if not statement_nodes:
        warnings.append("no problem statement found")

    choices, choices_tex = extract_choices(statement_nodes)
    if choices is None:
        warnings.append("could not split answer choices" if choices_tex else "no answer choices found")

    boxed = find_boxed_answer([n for _, nodes in solution_sections for n in nodes])

    statement_html = serialize(statement_nodes)
    solutions = []
    for heading, nodes in solution_sections:
        shtml = serialize(nodes)
        if shtml:
            solutions.append(Solution(heading, shtml))
    if not solutions:
        warnings.append("no solutions found")

    wiki_cats = [c.replace("_", " ") for c in (wiki_categories or [])]
    cats = map_categories(wiki_cats)

    return ParsedProblem(
        statement_html=statement_html,
        statement_text=plain_text(statement_html),
        choices=choices,
        choices_tex=choices_tex,
        solutions=solutions,
        boxed_answer=boxed,
        categories=cats,
        wiki_categories=wiki_cats,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- images

IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"')


def image_urls(html: str) -> list[str]:
    """Remote image URLs referenced by stored HTML (diagrams and wiki uploads)."""
    seen: list[str] = []
    for url in IMG_SRC_RE.findall(html or ""):
        if url.startswith("http") and url not in seen:
            seen.append(url)
    return seen


def rewrite_image_srcs(html: str, mapping: dict[str, str]) -> str:
    """Replace remote src values with local paths from mapping (url -> path)."""
    def rep(m: re.Match) -> str:
        url = m.group(1)
        local = mapping.get(url)
        if not local:
            return m.group(0)
        return m.group(0).replace('src="%s"' % url, 'src="%s"' % local)
    return IMG_SRC_RE.sub(rep, html or "")


# --------------------------------------------------------------------------- category guessing

# Keyword hints for problems the wiki has not categorized. Weights are per
# pattern; repeated hits of one pattern count at most three times. Applied to
# the statement plus the answer choices, lower-cased, LaTeX included.
_GEOMETRY_NOISE = re.compile(
    r"perfect (?:square|cube)s?|square roots?|squared|(?:sum|difference) of (?:the |two |three )?squares"
    r"|square numbers?|(?:two|three|four|consecutive|distinct|positive|odd|even) squares")
CATEGORY_HINTS: dict[str, list[tuple[str, int]]] = {
    "geometry": [
        (r"\\triangle|\btriangles?\b", 3), (r"\bcircles?\b|\bcircular\b|\bsemicircle", 3),
        (r"\\angle|\bangles?\b", 3), (r"\bsquares?\b", 2),
        (r"\brectangles?\b|\brectangular\b", 3),
        (r"\bpolygon|\bhexagon|\bpentagon|\boctagon|\bquadrilateral|\btrapezoid|\brhombus|\bparallelogram", 3),
        (r"\bperpendicular|\bparallel\b", 2), (r"\bdiameter|\bradius|\bradii|\bchord|\btangent\b", 3),
        (r"\barea\b|\bperimeter|\bvolume|\bsurface area", 3), (r"\bcubes?\b", 1),
        (r"\bsphere|\bcylinder|\bcone\b|\bpyramid|\bprism|\btetrahedron", 3),
        (r"\bvertex|\bvertices", 2), (r"\bdiagonals?\b", 2), (r"\bmidpoint", 3),
        (r"\binscribed|\bcircumscribed", 3),
        (r"\bisosceles|\bequilateral|\bright triangle|\bhypotenuse|\baltitude", 3),
        (r"\^\s*\{?\\circ|\bdegrees?\b", 2), (r"\bsegments?\b|\\overline", 2),
        (r"\bcollinear|\bcongruent|\bsimilar\b", 2), (r"\bcoordinate|\bplane\b|\bx-axis|\by-axis", 2),
        (r"\bdistance\b|\blength\b", 1), (r"\blines?\b|\bpoints?\b", 1), (r"\\pi\b", 1),
        (r"\breflect|\brotat|\bslope\b", 1), (r"\bshaded\b|\bregions?\b", 2),
    ],
    "number_theory": [
        (r"\bdivisible|\bdivisors?\b|\bdivides\b|\bdivisibility", 3), (r"\bprimes?\b", 3),
        (r"\bfactors?\b|\bfactorization", 2), (r"\bremainder|\bmodulo|\bmod\b|\\pmod|\\equiv", 3),
        (r"\bdigits?\b", 3), (r"\bgcd|\blcm|\bgreatest common|\bleast common|\bcommon multiple|\bcommon divisor", 3),
        (r"\bmultiples? of\b", 2),
        (r"\bin base\b|\bbase-\d+\b|\bbase (?:ten|two|three|four|five|six|seven|eight|nine|twelve|sixteen)\b", 3),
        (r"\bperfect (?:square|cube|power)|\b(?:sum|difference) of (?:two |the )?squares", 3), (r"\bpalindrome", 3),
        (r"\b(?:units|tens|hundreds|last|leading) digit", 3), (r"\brelatively prime|\bcoprime", 3),
        (r"\bpositive integers?\b|\bintegers?\b", 1), (r"\bodd\b|\beven\b", 1), (r"\bconsecutive", 1),
        (r"\bsum of (?:the |its )?digits|\bdigit sum", 3), (r"\d!", 1),
    ],
    "combinatorics": [
        (r"\bhow many ways|\bnumber of ways|\bin how many|\bhow many (?:different|distinct|possible)", 4),
        (r"\barrange|\barrangements?\b", 3), (r"\bpermutation|\bcombination", 3),
        (r"\bchoose|\bchosen|\bselect|\bselected", 2),
        (r"\bcommittee|\bsubsets?\b|\bhandshake|\btournament|\bseat", 3), (r"\bdistinct\b", 1),
        (r"\bguarantee|\bensure|\bpigeonhole|\bworst case", 3),
        (r"\bpaths?\b|\broutes?\b", 2), (r"\bgrid\b", 1), (r"\bcolou?r|\bpainted", 2),
        (r"\\binom|\\dbinom|\\choose", 3), (r"\bsequences? of\b|\bstrings?\b|\bbinary\b", 2),
        (r"\bcount\b|\bcounting", 2), (r"\bhow many\b", 1), (r"\bat least one\b", 1),
        (r"\bdifferent (?:ways|orders|arrangements)", 3), (r"\bteams?\b|\bgames? (?:are )?played", 1),
        (r"\bordered (?:pairs|triples)", 2), (r"\bpairs?\b", 1),
    ],
    "probability": [
        (r"\bprobabilit", 5), (r"\brandom|\bat random", 4), (r"\bexpected (?:value|number)", 4),
        (r"\bchance\b|\blikely\b|\bodds\b", 3), (r"\bfair (?:coin|die|dice)|\bflip|\btoss", 3),
        (r"\bcoins?\b", 1), (r"\bdice\b|\bdie\b|\brolled|\brolls?\b", 3),
        (r"\bdeck\b|\bcards?\b", 2), (r"\bdrawn\b|\bdraws?\b", 1),
        (r"\bspinner|\bmarbles?\b|\bballs?\b|\bbag\b|\burn\b", 1),
    ],
    "algebra": [
        (r"\bequations?\b|\bsolve\b|\bsolutions?\b", 2), (r"\bpolynomial|\broots?\b|\bquadratic|\bcubic\b", 3),
        (r"\bfunction|\bf\s*\(", 3),
        (r"\b(?:arithmetic|geometric) (?:sequence|progression|series)|\bsequence\b", 3),
        (r"\bmean\b|\bmedian|\bmode\b|\baverage|\bstandard deviation", 3), (r"\bpercent|%", 3),
        (r"\bspeed|\brate\b|\bmiles per hour|\bmph\b|\bper hour|\bminutes\b|\bhours\b", 2),
        (r"\bages?\b|\byears old|\bolder|\byounger", 3), (r"\bcost|\bprice|\bdollars|\bcents|\$\d", 3),
        (r"\bnickels?\b|\bdimes?\b|\bquarters?\b|\bpenn(?:y|ies)\b", 3),
        (r"\bratio\b|\bproportion", 2), (r"\blinear|\bexponents?\b|\blogarithm|\\log(?![a-z])|\\ln(?![a-z])", 3),
        (r"\\sqrt", 1), (r"\breal numbers?\b|\breal\b", 2), (r"\babsolute value|\\lvert|\\left\||\|x", 2),
        (r"\binequalit", 2), (r"\bsystem of\b", 2),
        (r"\bminimum|\bmaximum|\b(?:largest|smallest|least|greatest) possible", 1),
        (r"\\lfloor|\\lceil|\bfloor\b", 2), (r"\bsum\b|\bproduct\b", 1), (r"\bvalue of\b", 2),
        (r"\b[xy]\b", 1), (r"\bcompute|\bevaluate|\bsimplif", 2), (r"\\frac|\bfraction\b", 1),
        (r"\bnumber line", 2), (r"\bwork(?:s|ed|ing)?\b", 1),
    ],
    "other": [
        (r"\\sin\b|\\cos\b|\\tan\b|\bsine\b|\bcosine\b|\btrigonometr", 4),
        (r"\bknights? and knaves|\bknaves?\b|\bliars?\b|\balways lies|\balways tells? the truth|\btruth-?tellers?\b", 4),
        (r"\blogic\b", 3),
    ],
}
_HINTS_COMPILED = {cat: [(re.compile(pat), w) for pat, w in hints] for cat, hints in CATEGORY_HINTS.items()}


def guess_categories(text: str, has_diagram: bool = False) -> list[str]:
    """Keyword-based guess for an uncategorized problem. Returns [] when the
    evidence is too thin, so the problem stays visibly uncategorized."""
    low = (text or "").lower()
    geo_text = _GEOMETRY_NOISE.sub(" ", low)
    scores: dict[str, int] = {}
    for cat, hints in _HINTS_COMPILED.items():
        hay = geo_text if cat == "geometry" else low
        total = 0
        for pat, w in hints:
            n = len(pat.findall(hay))
            if n:
                total += w * min(n, 3 if w >= 2 else 2)  # weak words cannot clear the threshold alone
        scores[cat] = total
    if has_diagram:
        scores["geometry"] += 2
    # Ties go to the more specific subject; geometry's catch-alls make it the last resort.
    best = max(["algebra", "number_theory", "combinatorics", "probability", "other", "geometry"], key=lambda c: scores[c])
    if scores[best] < 3:
        return []
    out = [best]
    for cat, sc in sorted(scores.items(), key=lambda kv: -kv[1]):
        if cat != best and sc >= 6 and sc >= 0.7 * scores[best]:
            out.append(cat)
            break
    return [c for c in CATEGORY_ORDER if c in out]


# --------------------------------------------------------------------------- answer key

def parse_answer_key(html: str) -> dict[int, str]:
    """Answer-key page -> {problem_number: letter}. Accepts an <ol> of
    letters or lines like '13. D'."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("div", class_="mw-parser-output") or soup
    answers: dict[int, str] = {}
    for ol in root.find_all("ol"):
        items = ol.find_all("li", recursive=False)
        if len(items) < 20:
            continue
        start = int(ol.get("start", 1))
        for i, li in enumerate(items):
            m = re.search(r"\b([A-E])\b", li.get_text(" ", strip=True))
            if m:
                answers[start + i] = m.group(1)
        if len(answers) >= 20:
            return answers
    text = root.get_text("\n")
    for m in re.finditer(r"(?m)^\s*(\d{1,2})[.)]\s*\(?([A-E])\)?\s*$", text):
        answers[int(m.group(1))] = m.group(2)
    return answers
