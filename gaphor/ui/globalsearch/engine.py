"""Search engine for comprehensive model searching."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Iterator
from unicodedata import normalize

if TYPE_CHECKING:
    from gaphor.core.modeling import Base, Diagram
    from gaphor.core.modeling.presentation import Presentation


class SearchScope(Enum):
    GLOBAL = auto()
    CURRENT_DIAGRAM = auto()


class SearchCategory(Enum):
    NAME = "name"
    TYPE = "type"
    ATTRIBUTE = "attribute"
    ATTRIBUTE_VALUE = "attribute_value"
    RELATIONSHIP = "relationship"


@dataclass
class DiagramLocation:
    diagram: Diagram
    presentation: Presentation

    @property
    def diagram_name(self) -> str:
        return self.diagram.name or "<Unnamed Diagram>"


@dataclass
class SearchResult:
    element: Base
    match_category: SearchCategory
    match_field: str
    match_value: str
    relevance_score: float = 0.0
    diagram_locations: list[DiagramLocation] = field(default_factory=list)

    @property
    def element_name(self) -> str:
        return getattr(self.element, "name", None) or f"<{self.element_type}>"

    @property
    def element_type(self) -> str:
        return type(self.element).__name__

    @property
    def element_id(self) -> str:
        return self.element.id

    def __hash__(self):
        return hash((self.element.id, self.match_category, self.match_field))

    def __eq__(self, other):
        if not isinstance(other, SearchResult):
            return False
        return (
            self.element.id == other.element.id
            and self.match_category == other.match_category
            and self.match_field == other.match_field
        )


class SearchEngine:
    def __init__(self, element_factory, modeling_language):
        self.element_factory = element_factory
        self.modeling_language = modeling_language

    def search(
        self,
        query: str,
        scope: SearchScope = SearchScope.GLOBAL,
        current_diagram: Diagram | None = None,
        search_names: bool = True,
        search_types: bool = True,
        search_attributes: bool = True,
        search_relationships: bool = True,
        max_results: int = 100,
    ) -> list[SearchResult]:
        if not query or len(query.strip()) < 1:
            return []

        query_normalized = normalize("NFC", query.strip()).casefold()
        results: dict[tuple, SearchResult] = {}

        if scope == SearchScope.CURRENT_DIAGRAM and current_diagram:
            elements = self._get_diagram_elements(current_diagram)
        else:
            elements = self._get_all_elements()

        for element in elements:
            element_results = self._search_element(
                element,
                query_normalized,
                search_names,
                search_types,
                search_attributes,
                search_relationships,
            )

            for result in element_results:
                key = (result.element.id, result.match_category, result.match_field)
                if key not in results:
                    result.diagram_locations = self._find_diagram_locations(
                        result.element
                    )
                    results[key] = result

            if len(results) >= max_results:
                break

        sorted_results = sorted(
            results.values(), key=lambda r: (-r.relevance_score, r.element_name.lower())
        )

        return sorted_results[:max_results]

    def _get_all_elements(self) -> Iterator[Base]:
        yield from self.element_factory.select(None)

    def _get_diagram_elements(self, diagram: Diagram) -> Iterator[Base]:
        seen = set()
        for presentation in diagram.ownedPresentation:
            if presentation.subject and presentation.subject.id not in seen:
                seen.add(presentation.subject.id)
                yield presentation.subject

    def _search_element(
        self,
        element: Base,
        query: str,
        search_names: bool,
        search_types: bool,
        search_attributes: bool,
        search_relationships: bool,
    ) -> Iterator[SearchResult]:
        if search_names:
            yield from self._search_name(element, query)

        if search_types:
            yield from self._search_type(element, query)

        if search_attributes:
            yield from self._search_attributes(element, query)

        if search_relationships:
            yield from self._search_relationships(element, query)

    def _search_name(self, element: Base, query: str) -> Iterator[SearchResult]:
        name = getattr(element, "name", None)
        if name:
            name_normalized = normalize("NFC", str(name)).casefold()
            if query in name_normalized:
                score = self._calculate_relevance(query, name_normalized)
                yield SearchResult(
                    element=element,
                    match_category=SearchCategory.NAME,
                    match_field="name",
                    match_value=str(name),
                    relevance_score=score,
                )

    def _search_type(self, element: Base, query: str) -> Iterator[SearchResult]:
        type_name = type(element).__name__
        type_normalized = normalize("NFC", type_name).casefold()

        if query in type_normalized:
            score = self._calculate_relevance(query, type_normalized) * 0.8
            yield SearchResult(
                element=element,
                match_category=SearchCategory.TYPE,
                match_field="type",
                match_value=type_name,
                relevance_score=score,
            )

    def _search_attributes(self, element: Base, query: str) -> Iterator[SearchResult]:
        for prop in element.__properties__:
            prop_name = prop.name
            if prop_name.startswith("_"):
                continue

            try:
                value = getattr(element, prop_name, None)
            except Exception:
                continue

            if value is None:
                continue

            if isinstance(value, str):
                value_normalized = normalize("NFC", value).casefold()
                if query in value_normalized:
                    score = self._calculate_relevance(query, value_normalized) * 0.7
                    yield SearchResult(
                        element=element,
                        match_category=SearchCategory.ATTRIBUTE_VALUE,
                        match_field=prop_name,
                        match_value=str(value)[:100],
                        relevance_score=score,
                    )

            prop_name_normalized = normalize("NFC", prop_name).casefold()
            if query in prop_name_normalized:
                display_value = self._format_property_value(value)
                if display_value:
                    score = self._calculate_relevance(query, prop_name_normalized) * 0.6
                    yield SearchResult(
                        element=element,
                        match_category=SearchCategory.ATTRIBUTE,
                        match_field=prop_name,
                        match_value=display_value[:100],
                        relevance_score=score,
                    )

    def _search_relationships(
        self, element: Base, query: str
    ) -> Iterator[SearchResult]:
        from gaphor.UML import uml as UML

        if not isinstance(element, UML.Relationship):
            return

        relationship_type = type(element).__name__
        type_normalized = normalize("NFC", relationship_type).casefold()

        if query in type_normalized:
            related_info = self._get_relationship_info(element)
            score = self._calculate_relevance(query, type_normalized) * 0.75
            yield SearchResult(
                element=element,
                match_category=SearchCategory.RELATIONSHIP,
                match_field="relationship_type",
                match_value=f"{relationship_type}: {related_info}",
                relevance_score=score,
            )

    def _get_relationship_info(self, element: Base) -> str:
        parts = []

        for attr_name in ["source", "target", "client", "supplier", "general", "specific"]:
            value = getattr(element, attr_name, None)
            if value:
                if hasattr(value, "__iter__") and not isinstance(value, str):
                    for item in value:
                        name = getattr(item, "name", None)
                        if name:
                            parts.append(f"{attr_name}={name}")
                else:
                    name = getattr(value, "name", None)
                    if name:
                        parts.append(f"{attr_name}={name}")

        return ", ".join(parts) if parts else "<no endpoints>"

    def _format_property_value(self, value) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value if value else None
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, Base):
            return getattr(value, "name", None) or type(value).__name__
        if hasattr(value, "__iter__"):
            items = list(value)
            if not items:
                return None
            names = [getattr(i, "name", None) or type(i).__name__ for i in items[:3]]
            suffix = "..." if len(items) > 3 else ""
            return ", ".join(names) + suffix
        return str(value)

    def _calculate_relevance(self, query: str, text: str) -> float:
        if query == text:
            return 1.0
        if text.startswith(query):
            return 0.9
        if query in text:
            return 0.7 * (len(query) / len(text))
        return 0.5

    def _find_diagram_locations(self, element: Base) -> list[DiagramLocation]:
        locations = []

        if hasattr(element, "presentation"):
            for presentation in element.presentation:
                if presentation.diagram:
                    locations.append(
                        DiagramLocation(
                            diagram=presentation.diagram, presentation=presentation
                        )
                    )

        return locations
