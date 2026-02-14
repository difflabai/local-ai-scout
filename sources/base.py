"""Base classes for xscout source adapters."""

from dataclasses import dataclass, field, asdict
from abc import ABC, abstractmethod


@dataclass
class Post:
    """Normalized post from any source."""
    source: str              # e.g. "twitter", "hackernews", "reddit"
    id: str                  # unique ID within source
    title: str               # post title (empty for tweets)
    body: str                # post body / tweet text
    url: str                 # permalink to original
    author: str              # username / handle
    score: int = 0           # likes, points, upvotes
    created_at: str = ""     # ISO 8601
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class SourceAdapter(ABC):
    """Abstract base for source adapters."""

    name: str = ""

    @abstractmethod
    def fetch(self, queries: list[str], lookback_hours: int) -> list[Post]:
        """Fetch posts matching the given queries within the lookback window.

        Args:
            queries: Search query strings (interpreted per-source).
            lookback_hours: How far back to search.

        Returns:
            List of normalized Post objects.
        """
        ...
