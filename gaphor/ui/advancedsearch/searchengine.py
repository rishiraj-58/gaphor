"""Advanced search engine for comprehensive model searching."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING
from unicodedata import normalize

from gaphor.core.modeling import Base, Diagram
from gaphor.core.modeling.presentation import Presentation
from gaphor.ui.advancedsearch.searchresult import (
    DiagramLocation,
    SearchResult,
    SearchResultType,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory

log = logging.getLogger(__name__)

# Maximum results to prevent UI from freezing on large models
MAX_RESULTS = 500
# Timeout for search operations (not enforced here, but documented)
SEARCH_TIMEOUT_SECONDS = 5.0


class SearchScope:
    """Defines the scope of a search operation."""

    GLOBAL = "global"
    CURRENT_DIAGRAM = "current_diagram"


class AdvancedSearchEngine:
    """Comprehensive search engine for Gaphor models.

    Searches across:
    - Element names
    - Element types
    - Attribute names and values
    - Relationship types
    - Diagram names

    Supports filtering by:
    - Global scope (all packages) or current diagram
    - Element types
    """

    def __init__(self, element_factory: ElementFactory):
        if element_factory is None:
            raise ValueError("element_factory cannot be None")
        self._element_factory = element_factory
        self._cache_valid = False
        self._element_to_diagrams: dict[str, list[DiagramLocation]] = {}

    def invalidate_cache(self) -> None:
        """Invalidate the internal cache. Call when model changes."""
        self._cache_valid = False
        self._element_to_diagrams.clear()

    def _build_diagram_cache(self) -> None:
        """Build a cache mapping elements to their diagram locations."""
        if self._cache_valid:
            return

        self._element_to_diagrams.clear()

        try:
            for diagram in self._safe_select(Diagram):
                if diagram is None:
                    continue

                try:
                    presentations = getattr(diagram, "ownedPresentation", None)
                    if presentations is None:
                        continue

                    for presentation in presentations:
                        if presentation is None:
                            continue

                        subject = getattr(presentation, "subject", None)
                        if subject is None:
                            continue

                        element_id = getattr(subject, "id", None)
                        if element_id is None:
                            continue

                        if element_id not in self._element_to_diagrams:
                            self._element_to_diagrams[element_id] = []

                        self._element_to_diagrams[element_id].append(
                            DiagramLocation(diagram=diagram, presentation=presentation)
                        )
                except Exception as e:
                    log.debug(f"Error processing diagram: {e}")
                    continue

            self._cache_valid = True
        except Exception as e:
            log.warning(f"Failed to build diagram cache: {e}")
            self._cache_valid = False

    def _safe_select(self, type_or_filter=None) -> Iterator[Base]:
        """Safely select elements from the factory with error handling."""
        try:
            if type_or_filter is None:
                yield from self._element_factory.select(None)
            elif isinstance(type_or_filter, type):
                yield from self._element_factory.select(type_or_filter)
            else:
                yield from self._element_factory.select(type_or_filter)
        except Exception as e:
            log.warning(f"Error selecting elements: {e}")
            return

    def _get_diagram_locations(self, element: Base) -> list[DiagramLocation]:
        """Get all diagram locations for an element."""
        if element is None:
            return []

        self._build_diagram_cache()

        element_id = getattr(element, "id", None)
        if element_id is None:
            return []

        return self._element_to_diagrams.get(element_id, [])

    def _normalize_text(self, text: str | None) -> str:
        """Normalize text for case-insensitive comparison."""
        if text is None:
            return ""
        try:
            return normalize("NFC", str(text)).casefold()
        except Exception:
            return str(text).lower()

    def _calculate_relevance(
        self,
        search_text: str,
        match_value: str,
        result_type: SearchResultType,
    ) -> float:
        """Calculate a relevance score for a match (0.0 to 1.0)."""
        if not search_text or not match_value:
            return 0.5

        try:
            search_norm = self._normalize_text(search_text)
            match_norm = self._normalize_text(match_value)

            # Exact match gets highest score
            if search_norm == match_norm:
                return 1.0

            # Starts with search text
            if match_norm.startswith(search_norm):
                return 0.9

            # Contains search text
            if search_norm in match_norm:
                # Higher score for earlier position
                pos = match_norm.find(search_norm)
                return 0.7 - (pos / len(match_norm)) * 0.2

            # Type matches are slightly lower
            if result_type == SearchResultType.ELEMENT_TYPE:
                return 0.6

            return 0.5
        except Exception:
            return 0.5

    def _matches_search(self, text: str | None, search_text: str) -> bool:
        """Check if text matches the search query."""
        if text is None or search_text is None:
            return False
        try:
            return self._normalize_text(search_text) in self._normalize_text(text)
        except Exception:
            return False

    def _search_element_name(
        self, element: Base, search_text: str
    ) -> SearchResult | None:
        """Search for matches in element name."""
        try:
            name = getattr(element, "name", None)
            if name and self._matches_search(name, search_text):
                return SearchResult(
                    element=element,
                    result_type=SearchResultType.ELEMENT_NAME,
                    match_field="name",
                    match_value=str(name),
                    relevance_score=self._calculate_relevance(
                        search_text, name, SearchResultType.ELEMENT_NAME
                    ),
                    diagram_locations=self._get_diagram_locations(element),
                )
        except Exception as e:
            log.debug(f"Error searching element name: {e}")
        return None

    def _search_element_type(
        self, element: Base, search_text: str
    ) -> SearchResult | None:
        """Search for matches in element type name."""
        try:
            type_name = type(element).__name__
            if self._matches_search(type_name, search_text):
                element_name = getattr(element, "name", None) or f"<{type_name}>"
                return SearchResult(
                    element=element,
                    result_type=SearchResultType.ELEMENT_TYPE,
                    match_field="type",
                    match_value=type_name,
                    relevance_score=self._calculate_relevance(
                        search_text, type_name, SearchResultType.ELEMENT_TYPE
                    ),
                    diagram_locations=self._get_diagram_locations(element),
                )
        except Exception as e:
            log.debug(f"Error searching element type: {e}")
        return None

    def _search_element_attributes(
        self, element: Base, search_text: str
    ) -> Iterator[SearchResult]:
        """Search for matches in element attributes."""
        try:
            # Get all properties defined on the element
            properties = getattr(type(element), "__properties__", None)
            if properties is None:
                return

            for prop in properties:
                try:
                    prop_name = getattr(prop, "name", None)
                    if prop_name is None:
                        continue

                    # Skip internal properties
                    if prop_name.startswith("_"):
                        continue

                    # Check attribute name
                    if self._matches_search(prop_name, search_text):
                        yield SearchResult(
                            element=element,
                            result_type=SearchResultType.ATTRIBUTE_NAME,
                            match_field=prop_name,
                            match_value=prop_name,
                            relevance_score=self._calculate_relevance(
                                search_text, prop_name, SearchResultType.ATTRIBUTE_NAME
                            ),
                            diagram_locations=self._get_diagram_locations(element),
                        )

                    # Check attribute value
                    try:
                        value = getattr(element, prop_name, None)
                        if value is None:
                            continue

                        # Handle simple values
                        if isinstance(value, (str, int, float, bool)):
                            value_str = str(value)
                            if self._matches_search(value_str, search_text):
                                yield SearchResult(
                                    element=element,
                                    result_type=SearchResultType.ATTRIBUTE_VALUE,
                                    match_field=prop_name,
                                    match_value=value_str,
                                    relevance_score=self._calculate_relevance(
                                        search_text,
                                        value_str,
                                        SearchResultType.ATTRIBUTE_VALUE,
                                    ),
                                    diagram_locations=self._get_diagram_locations(
                                        element
                                    ),
                                )
                    except Exception:
                        # Some properties may raise errors when accessed
                        continue

                except Exception as e:
                    log.debug(f"Error processing property: {e}")
                    continue

        except Exception as e:
            log.debug(f"Error searching element attributes: {e}")

    def _search_relationships(
        self, element: Base, search_text: str
    ) -> Iterator[SearchResult]:
        """Search for relationship type matches."""
        try:
            # Check if the element is a relationship
            from gaphor.UML import uml as UML

            if isinstance(element, UML.Relationship):
                type_name = type(element).__name__
                if self._matches_search(type_name, search_text):
                    yield SearchResult(
                        element=element,
                        result_type=SearchResultType.RELATIONSHIP_TYPE,
                        match_field="relationship_type",
                        match_value=type_name,
                        relevance_score=self._calculate_relevance(
                            search_text, type_name, SearchResultType.RELATIONSHIP_TYPE
                        ),
                        diagram_locations=self._get_diagram_locations(element),
                    )
        except ImportError:
            log.debug("UML module not available for relationship search")
        except Exception as e:
            log.debug(f"Error searching relationships: {e}")

    def _search_diagrams(
        self, diagram: Diagram, search_text: str
    ) -> SearchResult | None:
        """Search for matches in diagram names."""
        try:
            name = getattr(diagram, "name", None)
            if name and self._matches_search(name, search_text):
                return SearchResult(
                    element=diagram,
                    result_type=SearchResultType.DIAGRAM_NAME,
                    match_field="name",
                    match_value=str(name),
                    relevance_score=self._calculate_relevance(
                        search_text, name, SearchResultType.DIAGRAM_NAME
                    ),
                    diagram_locations=[DiagramLocation(diagram=diagram)],
                )
        except Exception as e:
            log.debug(f"Error searching diagram: {e}")
        return None

    def _get_elements_in_diagram(self, diagram: Diagram) -> set[str]:
        """Get all element IDs that appear in a specific diagram."""
        element_ids: set[str] = set()

        if diagram is None:
            return element_ids

        try:
            presentations = getattr(diagram, "ownedPresentation", None)
            if presentations is None:
                return element_ids

            for presentation in presentations:
                if presentation is None:
                    continue

                subject = getattr(presentation, "subject", None)
                if subject is None:
                    continue

                element_id = getattr(subject, "id", None)
                if element_id is not None:
                    element_ids.add(element_id)

            # Also add the diagram itself
            diagram_id = getattr(diagram, "id", None)
            if diagram_id is not None:
                element_ids.add(diagram_id)

        except Exception as e:
            log.debug(f"Error getting elements in diagram: {e}")

        return element_ids

    def search(
        self,
        search_text: str,
        scope: str = SearchScope.GLOBAL,
        current_diagram: Diagram | None = None,
        include_names: bool = True,
        include_types: bool = True,
        include_attributes: bool = True,
        include_relationships: bool = True,
    ) -> list[SearchResult]:
        """Perform a comprehensive search across the model.

        Args:
            search_text: The text to search for
            scope: SearchScope.GLOBAL or SearchScope.CURRENT_DIAGRAM
            current_diagram: The current diagram (required if scope is CURRENT_DIAGRAM)
            include_names: Search in element names
            include_types: Search in element type names
            include_attributes: Search in attribute names and values
            include_relationships: Search in relationship types

        Returns:
            List of SearchResult objects sorted by relevance
        """
        if not search_text:
            return []

        search_text = search_text.strip()
        if not search_text:
            return []

        # Validate scope
        if scope == SearchScope.CURRENT_DIAGRAM and current_diagram is None:
            log.warning("Current diagram scope requested but no diagram provided")
            scope = SearchScope.GLOBAL

        # Get elements to search based on scope
        diagram_element_ids: set[str] | None = None
        if scope == SearchScope.CURRENT_DIAGRAM and current_diagram is not None:
            diagram_element_ids = self._get_elements_in_diagram(current_diagram)

        results: dict[tuple, SearchResult] = {}
        result_count = 0

        try:
            for element in self._safe_select(None):
                if element is None:
                    continue

                if result_count >= MAX_RESULTS:
                    log.info(f"Search result limit ({MAX_RESULTS}) reached")
                    break

                # Filter by scope
                if diagram_element_ids is not None:
                    element_id = getattr(element, "id", None)
                    if element_id not in diagram_element_ids:
                        continue

                # Search element name
                if include_names:
                    if result := self._search_element_name(element, search_text):
                        key = (result.element_id, result.result_type, result.match_field)
                        if key not in results:
                            results[key] = result
                            result_count += 1
                            if result_count >= MAX_RESULTS:
                                break

                # Search element type
                if include_types:
                    if result := self._search_element_type(element, search_text):
                        key = (result.element_id, result.result_type, result.match_field)
                        if key not in results:
                            results[key] = result
                            result_count += 1
                            if result_count >= MAX_RESULTS:
                                break

                # Search attributes
                if include_attributes:
                    for result in self._search_element_attributes(element, search_text):
                        if result_count >= MAX_RESULTS:
                            break
                        key = (result.element_id, result.result_type, result.match_field)
                        if key not in results:
                            results[key] = result
                            result_count += 1

                # Search relationships
                if include_relationships:
                    for result in self._search_relationships(element, search_text):
                        if result_count >= MAX_RESULTS:
                            break
                        key = (result.element_id, result.result_type, result.match_field)
                        if key not in results:
                            results[key] = result
                            result_count += 1

                # Search diagrams
                if include_names and isinstance(element, Diagram):
                    if result := self._search_diagrams(element, search_text):
                        key = (result.element_id, result.result_type, result.match_field)
                        if key not in results:
                            results[key] = result
                            result_count += 1

        except Exception as e:
            log.error(f"Error during search: {e}")

        # Sort by relevance score (descending)
        sorted_results = sorted(
            results.values(), key=lambda r: r.relevance_score, reverse=True
        )

        return sorted_results

    def search_by_type(self, type_name: str) -> list[SearchResult]:
        """Search for all elements of a specific type.

        Args:
            type_name: The type name to search for (e.g., "Class", "Association")

        Returns:
            List of SearchResult objects
        """
        if not type_name:
            return []

        results: list[SearchResult] = []
        type_name_lower = type_name.lower()

        try:
            for element in self._safe_select(None):
                if element is None:
                    continue

                if len(results) >= MAX_RESULTS:
                    break

                element_type_name = type(element).__name__
                if element_type_name.lower() == type_name_lower:
                    results.append(
                        SearchResult(
                            element=element,
                            result_type=SearchResultType.ELEMENT_TYPE,
                            match_field="type",
                            match_value=element_type_name,
                            relevance_score=1.0,
                            diagram_locations=self._get_diagram_locations(element),
                        )
                    )
        except Exception as e:
            log.error(f"Error during type search: {e}")

        return results

    def search_relationships_of_type(self, relationship_type: str) -> list[SearchResult]:
        """Search for all relationships of a specific type.

        Args:
            relationship_type: The relationship type name (e.g., "Association", "Dependency")

        Returns:
            List of SearchResult objects
        """
        if not relationship_type:
            return []

        results: list[SearchResult] = []
        type_lower = relationship_type.lower()

        try:
            from gaphor.UML import uml as UML

            for element in self._safe_select(UML.Relationship):
                if element is None:
                    continue

                if len(results) >= MAX_RESULTS:
                    break

                element_type_name = type(element).__name__
                if element_type_name.lower() == type_lower:
                    results.append(
                        SearchResult(
                            element=element,
                            result_type=SearchResultType.RELATIONSHIP_TYPE,
                            match_field="relationship_type",
                            match_value=element_type_name,
                            relevance_score=1.0,
                            diagram_locations=self._get_diagram_locations(element),
                        )
                    )
        except ImportError:
            log.debug("UML module not available for relationship search")
        except Exception as e:
            log.error(f"Error during relationship type search: {e}")

        return results
