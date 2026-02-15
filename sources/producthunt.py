"""Product Hunt source adapter — uses the public Atom feed (no auth required).

Product Hunt retired their public API in 2024. This adapter uses the public
Atom feed at https://www.producthunt.com/feed which returns ~50 recent launches.
Posts are filtered client-side against topic keywords.

Stdlib only: xml.etree.ElementTree for Atom parsing, urllib for HTTP.
"""

import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from xml.etree.ElementTree import fromstring

from .base import Post, SourceAdapter

FEED_URL = "https://www.producthunt.com/feed"
USER_AGENT = "xscout/1.0 (local-ai-scout; stdlib)"
ATOM_NS = "http://www.w3.org/2005/Atom"


class _TaglineExtractor(HTMLParser):
    """Extract the tagline (first <p> text) from Atom entry content HTML."""

    def __init__(self):
        super().__init__()
        self._in_p = False
        self._depth = 0
        self.tagline = ""

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._depth += 1
            if self._depth == 1:
                self._in_p = True

    def handle_endtag(self, tag):
        if tag == "p":
            if self._in_p:
                self._in_p = False
            self._depth -= 1

    def handle_data(self, data):
        if self._in_p and not self.tagline:
            self.tagline = data.strip()


def _extract_tagline(html_content: str) -> str:
    """Parse HTML content from an Atom entry to get the product tagline."""
    parser = _TaglineExtractor()
    parser.feed(html_content)
    return parser.tagline


def _parse_atom_date(date_str: str) -> datetime:
    """Parse Atom date string (ISO 8601 with timezone offset) to UTC datetime.

    Handles formats like: 2026-02-13T07:47:47-08:00
    """
    # Python 3.7+ fromisoformat handles timezone offsets
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _extract_post_id(entry_id: str) -> str:
    """Extract numeric post ID from Atom entry ID.

    Entry IDs look like: tag:www.producthunt.com,2005:Post/1078316
    """
    match = re.search(r"Post/(\d+)", entry_id)
    return match.group(1) if match else ""


def _topic_matches(title: str, tagline: str, topic: str) -> bool:
    """Check if a product matches the topic query (case-insensitive keyword match).

    Splits the topic on commas and spaces into individual keywords.
    A product matches if ANY keyword appears in its title or tagline.
    """
    text = f"{title} {tagline}".lower()
    # Split on commas first (for multi-topic like "AI, machine learning")
    terms = [t.strip().lower() for t in topic.split(",") if t.strip()]
    # If no commas, treat the whole topic as a single search term
    if not terms:
        terms = [topic.lower().strip()]

    for term in terms:
        # Match the term as a whole phrase first
        if term in text:
            return True
        # Also try individual words for multi-word terms
        words = term.split()
        if len(words) > 1 and any(w in text for w in words if len(w) > 2):
            return True

    return False


def _fetch_feed() -> str:
    """Fetch the Product Hunt Atom feed."""
    req = Request(FEED_URL)
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except Exception as e:
        print(f"  ⚠ Product Hunt feed request failed: {e}", file=sys.stderr)
        return ""


class ProductHuntAdapter(SourceAdapter):
    @property
    def name(self) -> str:
        return "producthunt"

    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        print(f"  [producthunt] Fetching feed, filtering for: {topic[:60]}", file=sys.stderr)

        xml_text = _fetch_feed()
        if not xml_text:
            return []

        root = fromstring(xml_text)
        entries = root.findall(f"{{{ATOM_NS}}}entry")
        print(f"  [producthunt] {len(entries)} entries in feed", file=sys.stderr)

        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if lookback_hours > 0:
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        # Build search terms from topic + queries
        search_terms = []
        if queries:
            search_terms.extend(queries)
        if topic:
            search_terms.append(topic)
        combined_topic = ", ".join(search_terms) if search_terms else ""

        posts: list[Post] = []

        for entry in entries:
            title_el = entry.find(f"{{{ATOM_NS}}}title")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""

            content_el = entry.find(f"{{{ATOM_NS}}}content")
            content_html = content_el.text or "" if content_el is not None else ""
            tagline = _extract_tagline(content_html)

            # Filter by topic if provided
            if combined_topic and not _topic_matches(title, tagline, combined_topic):
                continue

            # Parse date and check lookback window
            published_el = entry.find(f"{{{ATOM_NS}}}published")
            published_str = published_el.text if published_el is not None else ""
            published = _parse_atom_date(published_str) if published_str else datetime.now(timezone.utc)

            if published < cutoff:
                continue

            # Extract URL
            link_el = entry.find(f"{{{ATOM_NS}}}link")
            url = link_el.get("href", "") if link_el is not None else ""

            # Extract author
            author_el = entry.find(f"{{{ATOM_NS}}}author/{{{ATOM_NS}}}name")
            author = author_el.text.strip() if author_el is not None and author_el.text else ""

            # Extract post ID
            id_el = entry.find(f"{{{ATOM_NS}}}id")
            entry_id = id_el.text if id_el is not None else ""
            post_id = _extract_post_id(entry_id)

            # Combine title + tagline for the text field
            text = f"{title}\n\n{tagline}" if tagline else title

            posts.append(Post(
                source="producthunt",
                author=author,
                text=text,
                url=url,
                timestamp=published.isoformat(),
                score=0,  # Atom feed doesn't include vote counts
                metadata={
                    "tagline": tagline,
                    "post_id": post_id,
                    "product_url": url,
                },
            ))

            if len(posts) >= max_results:
                break

        print(f"  -> {len(posts)} products from Product Hunt", file=sys.stderr)
        return posts
