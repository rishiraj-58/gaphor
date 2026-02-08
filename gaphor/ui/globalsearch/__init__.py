"""Global search module for Gaphor.

This module provides advanced search capabilities across the entire model,
including searching by element names, types, attributes, values, and
relationship types.
"""

from gaphor.ui.globalsearch.service import GlobalSearchService
from gaphor.ui.globalsearch.engine import SearchEngine, SearchScope, SearchResult
from gaphor.ui.globalsearch.indexer import SearchIndexer

__all__ = [
    "GlobalSearchService",
    "SearchEngine",
    "SearchScope",
    "SearchResult",
    "SearchIndexer",
]
