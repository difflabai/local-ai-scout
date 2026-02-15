from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Post:
    """Normalized post from any source."""
    source: str        # "x", "reddit", "hackernews", "civitai"
    author: str
    text: str
    url: str           # direct link to original post
    timestamp: str     # ISO 8601
    score: int = 0     # upvotes, likes, etc.
    metadata: dict = field(default_factory=dict)  # source-specific extras


class SourceAdapter(ABC):
    @abstractmethod
    def fetch(self, topic: str, lookback_hours: int = 24, max_results: int = 100,
              queries: list[str] | None = None) -> list[Post]:
        """Fetch posts about a topic. Returns normalized Post objects."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
