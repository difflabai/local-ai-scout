from .base import Post, SourceAdapter
from .x import XAdapter
from .reddit import RedditAdapter
from .civitai import CivitAIAdapter
from .arxiv import ArxivAdapter

ADAPTERS = {
    "x": XAdapter,
    "reddit": RedditAdapter,
    "civitai": CivitAIAdapter,
    "arxiv": ArxivAdapter,
}

__all__ = ["Post", "SourceAdapter", "XAdapter", "RedditAdapter", "CivitAIAdapter", "ArxivAdapter", "ADAPTERS"]
