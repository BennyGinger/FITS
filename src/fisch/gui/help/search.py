"""Search the offline guide with page-title matches before body-text matches."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class GuidePage:
    """A Markdown page indexed for contextual guide search."""

    path: Path
    title: str
    text: str


def index_guide(root: Path) -> list[GuidePage]:
    """
    Read the guide once when a help window first needs a search index.
    """
    pages: list[GuidePage] = []
    for path in sorted(root.rglob('*.md')):
        text = path.read_text(encoding='utf-8')
        heading = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        title = heading.group(1).strip() if heading is not None else path.stem.replace('_', ' ')
        pages.append(GuidePage(path.relative_to(root), title, text.casefold()))
    return pages


def search_guide(pages: Sequence[GuidePage], query: str) -> list[GuidePage]:
    """
    Rank exact titles, title words, title substrings and finally body-text matches.
    """
    normalized = ' '.join(query.casefold().split())
    terms = normalized.split()
    if not terms:
        return []
    matches: list[tuple[int, GuidePage]] = []
    for page in pages:
        title = page.title.casefold()
        words = set(re.findall(r'\w+', title))
        if normalized == title:
            rank = 0
        elif all(term in words for term in terms):
            rank = 1
        elif all(term in title for term in terms):
            rank = 2
        elif all(term in page.text for term in terms):
            rank = 3
        else:
            continue
        matches.append((rank, page))
    matches.sort(key=lambda match: (match[0], match[1].title.casefold(), match[1].path.as_posix()))
    return [page for _, page in matches]
