"""Which contests to scrape and how their AoPS wiki pages are titled."""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

WIKI_PAGE = "https://artofproblemsolving.com/wiki/index.php/"

FIRST_AB_YEAR = 2002  # AMC 10 split into A and B versions in 2002


@dataclass(frozen=True)
class Contest:
    year: int
    version: str  # "A" or "B"
    fall: bool = False

    @property
    def id(self) -> str:
        season = "_Fall" if self.fall else ""
        return f"{self.year}{season}_AMC_10{self.version}"

    @property
    def name(self) -> str:
        season = " Fall" if self.fall else ""
        return f"{self.year}{season} AMC 10{self.version}"

    @property
    def answer_key_title(self) -> str:
        return f"{self.name} Answer Key"

    @property
    def problems_title(self) -> str:
        return f"{self.name} Problems"

    def problem_title(self, number: int) -> str:
        return f"{self.problems_title}/Problem {number}"

    def problem_id(self, number: int) -> str:
        return f"{self.id}_{number}"

    @property
    def url(self) -> str:
        return page_url(self.problems_title)


def page_url(title: str) -> str:
    return WIKI_PAGE + title.replace(" ", "_")


def all_contests(first_year: int = FIRST_AB_YEAR, last_year: int | None = None) -> list[Contest]:
    """Every AMC 10A/10B from first_year to last_year inclusive (plus 2021 Fall)."""
    if last_year is None:
        last_year = _dt.date.today().year
    out: list[Contest] = []
    for year in range(first_year, last_year + 1):
        for version in ("A", "B"):
            out.append(Contest(year, version))
        if year == 2021:
            for version in ("A", "B"):
                out.append(Contest(year, version, fall=True))
    return out


def parse_contest_id(cid: str) -> Contest:
    """'2021_Fall_AMC_10B' -> Contest(2021, 'B', fall=True)."""
    parts = cid.split("_")
    year = int(parts[0])
    fall = "Fall" in parts
    version = parts[-1][-1].upper()
    if version not in ("A", "B") or not parts[-1].startswith("10"):
        raise ValueError(f"not an AMC 10A/10B contest id: {cid}")
    return Contest(year, version, fall)
