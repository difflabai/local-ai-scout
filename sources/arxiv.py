"""Arxiv source adapter — searches recent papers via the public Arxiv API."""

import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .base import Post, SourceAdapter

ARXIV_API = "http://export.arxiv.org/api/query"
USER_AGENT = "xscout/1.0 (local-ai-scout; stdlib)"

# Arxiv Atom XML namespaces
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# Max abstract snippet length in the text field
ABSTRACT_MAX_CHARS = 500


def _arxiv_get(url: str) -> str:
    """Fetch Arxiv API endpoint and return raw XML."""
    req = Request(url)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except Exception as e:
        print(f"  ⚠ Arxiv request failed: {e}", file=sys.stderr)
        return ""


class ArxivAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "arxiv"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        search_terms = self._build_search_terms(topic, queries)
        posts: list[Post] = []
        seen_ids: set[str] = set()

        for i, term in enumerate(search_terms, 1):
            print(f"  [arxiv {i}/{len(search_terms)}] {term[:60]}...", file=sys.stderr)
            results = self._search(term, min(max_results, 20))
            for post in results:
                if post.url not in seen_ids:
                    seen_ids.add(post.url)
                    posts.append(post)

        print(f"  -> {len(posts)} papers from Arxiv", file=sys.stderr)
        return posts

    def _build_search_terms(self, topic: str, queries: list[str] | None) -> list[str]:
        """Split comma-separated topics into individual search terms."""
        if queries:
            return queries
        terms = [t.strip() for t in topic.split(",") if t.strip()]
        return terms or [topic]

    def _search(self, query: str, max_results: int) -> list[Post]:
        """Search Arxiv and return normalized Post objects."""
        encoded = quote_plus(query)
        url = (
            f"{ARXIV_API}?search_query=all:{encoded}"
            f"&sortBy=submittedDate&sortOrder=descending"
            f"&max_results={max_results}"
        )
        xml_text = _arxiv_get(url)
        if not xml_text:
            return []
        return self._parse(xml_text)

    def _parse(self, xml_text: str) -> list[Post]:
        """Parse Arxiv Atom XML into Post objects."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"  ⚠ Arxiv XML parse error: {e}", file=sys.stderr)
            return []

        posts = []
        for entry in root.findall("atom:entry", NS):
            title = (entry.findtext("atom:title", "", NS) or "").strip()
            # Collapse whitespace in title (Arxiv titles span multiple lines)
            title = " ".join(title.split())

            abstract = (entry.findtext("atom:summary", "", NS) or "").strip()
            abstract = " ".join(abstract.split())
            snippet = abstract[:ABSTRACT_MAX_CHARS]
            if len(abstract) > ABSTRACT_MAX_CHARS:
                snippet += "..."

            # Prefer the abs link; fall back to first link
            url = ""
            for link in entry.findall("atom:link", NS):
                href = link.get("href", "")
                if link.get("title") == "pdf":
                    continue
                if "/abs/" in href:
                    url = href
                    break
                if not url:
                    url = href

            published = (entry.findtext("atom:published", "", NS) or "").strip()
            # Normalize to ISO 8601
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    timestamp = dt.isoformat()
                except ValueError:
                    timestamp = published
            else:
                timestamp = ""

            # Collect authors
            authors = []
            for author_el in entry.findall("atom:author", NS):
                name = (author_el.findtext("atom:name", "", NS) or "").strip()
                if name:
                    authors.append(name)
            author_str = ", ".join(authors) if authors else "Unknown"

            # Categories
            categories = []
            for cat in entry.findall("atom:category", NS):
                term = cat.get("term", "")
                if term:
                    categories.append(term)

            # Arxiv ID from the <id> element (e.g. http://arxiv.org/abs/2401.12345v1)
            arxiv_id = (entry.findtext("atom:id", "", NS) or "").strip()

            text = f"{title}\n\n{snippet}"

            posts.append(Post(
                source="arxiv",
                author=author_str,
                text=text,
                url=url or arxiv_id,
                timestamp=timestamp,
                score=0,
                metadata={
                    "arxiv_id": arxiv_id,
                    "categories": categories,
                    "title": title,
                    "abstract": abstract,
                },
            ))

        return posts
