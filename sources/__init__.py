from .base import Post, SourceAdapter
from .x import XAdapter
from .reddit import RedditAdapter
from .civitai import CivitAIAdapter
from .arxiv import ArxivAdapter
from .lobsters import LobstersAdapter
from .hackernews import HackerNewsAdapter

ADAPTERS = {
    "x": XAdapter,
    "reddit": RedditAdapter,
    "civitai": CivitAIAdapter,
    "arxiv": ArxivAdapter,
    "lobsters": LobstersAdapter,
    "hackernews": HackerNewsAdapter,
}

__all__ = ["Post", "SourceAdapter", "XAdapter", "RedditAdapter", "CivitAIAdapter", "ArxivAdapter", "LobstersAdapter", "HackerNewsAdapter", "ADAPTERS"]
