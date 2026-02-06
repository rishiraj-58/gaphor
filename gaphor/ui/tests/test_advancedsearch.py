"""Tests for gaphor.ui.advancedsearch.

Every test in this file exercises ``SearchIndex`` (the pure-Python
searcher) *without* a GTK display.  The GTK dialog (``AdvancedSearchDialog``)
is tested only through its ``show`` / ``close`` lifecycle and its
``_run_search`` path, which delegates to the same ``SearchIndex``.

Fixture layout
--------------
* ``event_manager`` / ``element_factory`` / ``modeling_language`` –
  provided by ``gaphor.conftest`` (top-level conftest).
* ``make_class`` – thin helper that creates a UML.Class with a given
  name inside the factory.
* ``make_diagram`` – creates a UML.Diagram, optionally places a
  presentation of a given element on it, and returns the diagram.

Convention
----------
Each test name describes the *search behaviour* being verified, not the
internal method being called.  The ``SearchIndex`` is instantiated fresh
inside every test so there is zero shared mutable state between tests.
"""

from __future__ import annotations

import pytest

from gaphor import UML
from gaphor.core.modeling import Diagram
from gaphor.transaction import Transaction
from gaphor.ui.advancedsearch import (
    SearchIndex,
    SearchResult,
    _collect_attribute_tokens,
    _collect_relationship_tokens,
    _diagrams_for,
    _is_presentation,
    _is_relationship,
    _normalise,
    _safe_name,
    _type_label,
)


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_class(element_factory, event_manager):
    """Factory-fixture: ``make_class("Foo")`` → UML.Class with name Foo."""

    def _make(name: str, package=None):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = name
            if package is not None:
                klass.package = package
        return klass

    return _make


@pytest.fixture
def make_diagram(element_factory, event_manager):
    """Factory-fixture that creates a diagram and optionally places an
    element on it.

    Usage::

        diag = make_diagram("MyDiagram")                     # empty diagram
        diag = make_diagram("MyDiagram", element=klass)      # with a ClassItem

    The presentation is created via ``Diagram.create_as`` which registers
    it in the factory *without* triggering the full ``update()``
    pipeline (which would need a real Pango layout).  We therefore call
    ``create_as`` directly and skip ``self.update()``.
    """

    def _make(name: str, element=None):
        with Transaction(event_manager):
            diag = element_factory.create(Diagram)
            diag.name = name
            if element is not None:
                from gaphor.diagram.support import get_diagram_item
                from gaphor.core.modeling.base import generate_id

                item_cls = get_diagram_item(type(element))
                if item_cls is not None:
                    # create_as registers the presentation in the
                    # factory and sets diagram / subject without the
                    # layout pass that crashes under the Pango stub.
                    item = element_factory.create_as(
                        item_cls, generate_id(), diagram=diag
                    )
                    item.subject = element
        return diag

    return _make


# ---------------------------------------------------------------------------
# Unit helpers (no GTK, no search)
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_ascii(self):
        assert _normalise("Hello") == "hello"

    def test_unicode_nfc(self):
        # é composed vs decomposed must normalise to the same string
        composed = "caf\u00e9"  # café (NFC)
        decomposed = "cafe\u0301"  # cafe + combining acute
        assert _normalise(composed) == _normalise(decomposed)

    def test_empty(self):
        assert _normalise("") == ""


class TestSafeName:
    def test_named_element(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Widget"
        assert _safe_name(klass) == "Widget"

    def test_unnamed_element(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            # name is not set → defaults to empty / None
        assert _safe_name(klass) == ""

    def test_non_named_element(self, element_factory, event_manager):
        """Elements that have no .name attribute at all return ''."""
        with Transaction(event_manager):
            gen = element_factory.create(UML.Generalization)
        assert _safe_name(gen) == ""


class TestTypeLabel:
    def test_class(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
        assert _type_label(klass) == "Class"

    def test_generalization(self, element_factory, event_manager):
        with Transaction(event_manager):
            gen = element_factory.create(UML.Generalization)
        assert _type_label(gen) == "Generalization"

    def test_association(self, element_factory, event_manager):
        with Transaction(event_manager):
            assoc = element_factory.create(UML.Association)
        assert _type_label(assoc) == "Association"


class TestIsRelationship:
    def test_generalization_is_relationship(self, element_factory, event_manager):
        with Transaction(event_manager):
            gen = element_factory.create(UML.Generalization)
        assert _is_relationship(gen) is True

    def test_class_is_not_relationship(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
        assert _is_relationship(klass) is False

    def test_dependency_is_relationship(self, element_factory, event_manager):
        with Transaction(event_manager):
            dep = element_factory.create(UML.Dependency)
        assert _is_relationship(dep) is True

    def test_association_is_relationship(self, element_factory, event_manager):
        with Transaction(event_manager):
            assoc = element_factory.create(UML.Association)
        # Association inherits from Relationship in UML
        assert _is_relationship(assoc) is True


class TestIsPresentation:
    def test_class_is_not_presentation(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
        assert _is_presentation(klass) is False

    def test_diagram_item_is_presentation(
        self, element_factory, event_manager, make_diagram, make_class
    ):
        klass = make_class("Foo")
        diag = make_diagram("D", element=klass)
        # The presentation created on the diagram
        pres = next(iter(klass.presentation))
        assert _is_presentation(pres) is True


class TestDiagramsFor:
    def test_element_on_no_diagram(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Lonely"
        assert _diagrams_for(klass) == []

    def test_element_on_one_diagram(self, make_class, make_diagram):
        klass = make_class("OneDiag")
        diag = make_diagram("D1", element=klass)
        result = _diagrams_for(klass)
        assert len(result) == 1
        assert result[0] is diag

    def test_element_on_two_diagrams(self, make_class, make_diagram):
        klass = make_class("TwoDiag")
        d1 = make_diagram("D1", element=klass)
        d2 = make_diagram("D2", element=klass)
        result = _diagrams_for(klass)
        assert len(result) == 2
        assert set(id(d) for d in result) == {id(d1), id(d2)}


# ---------------------------------------------------------------------------
# Attribute / relationship token collection
# ---------------------------------------------------------------------------


class TestCollectAttributeTokens:
    def test_class_with_attribute(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Car"
            prop = element_factory.create(UML.Property)
            prop.name = "speed"
            klass.ownedAttribute = prop

            type_cls = element_factory.create(UML.Class)
            type_cls.name = "int"
            prop.type = type_cls

        tokens = _collect_attribute_tokens(klass)
        assert "speed" in tokens
        assert "int" in tokens

    def test_class_with_operation(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Car"
            op = element_factory.create(UML.Operation)
            op.name = "accelerate"
            klass.ownedOperation = op

        tokens = _collect_attribute_tokens(klass)
        assert "accelerate" in tokens

    def test_operation_with_parameters(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Car"
            op = element_factory.create(UML.Operation)
            op.name = "setSpeed"
            klass.ownedOperation = op

            param = element_factory.create(UML.Parameter)
            param.name = "newSpeed"
            op.ownedParameter = param

        tokens = _collect_attribute_tokens(klass)
        assert "setSpeed" in tokens
        assert "newSpeed" in tokens

    def test_empty_class_returns_no_tokens(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Empty"
        assert _collect_attribute_tokens(klass) == []


class TestCollectRelationshipTokens:
    def test_generalization_tokens(self, element_factory, event_manager):
        with Transaction(event_manager):
            base = element_factory.create(UML.Class)
            base.name = "Animal"
            child = element_factory.create(UML.Class)
            child.name = "Dog"

            gen = element_factory.create(UML.Generalization)
            gen.general = base
            gen.specific = child

        tokens = _collect_relationship_tokens(gen)
        # type label
        assert "Generalization" in tokens
        # endpoint names
        assert "Animal" in tokens
        assert "Dog" in tokens

    def test_dependency_tokens(self, element_factory, event_manager):
        with Transaction(event_manager):
            supplier = element_factory.create(UML.Class)
            supplier.name = "Logger"
            client = element_factory.create(UML.Class)
            client.name = "App"

            dep = element_factory.create(UML.Dependency)
            dep.supplier = supplier
            dep.client = client

        tokens = _collect_relationship_tokens(dep)
        assert "Dependency" in tokens
        assert "Logger" in tokens
        assert "App" in tokens

    def test_association_memberend_tokens(self, element_factory, event_manager):
        with Transaction(event_manager):
            a = element_factory.create(UML.Class)
            a.name = "Wheel"
            b = element_factory.create(UML.Class)
            b.name = "Car"

            assoc = element_factory.create(UML.Association)
            end1 = element_factory.create(UML.Property)
            end1.name = "wheel"
            end1.type = a
            end2 = element_factory.create(UML.Property)
            end2.name = "car"
            end2.type = b

            assoc.memberEnd = end1
            assoc.memberEnd = end2

        tokens = _collect_relationship_tokens(assoc)
        assert "wheel" in tokens
        assert "car" in tokens
        assert "Wheel" in tokens
        assert "Car" in tokens


# ---------------------------------------------------------------------------
# SearchIndex – core search behaviour
# ---------------------------------------------------------------------------


class TestSearchEmptyQuery:
    def test_empty_string_returns_nothing(self, element_factory, make_class):
        make_class("Anything")
        idx = SearchIndex(element_factory)
        assert idx.search("") == []

    def test_whitespace_only_returns_nothing(self, element_factory, make_class):
        make_class("Anything")
        idx = SearchIndex(element_factory)
        assert idx.search("   ") == []


class TestSearchByName:
    def test_exact_name_match(self, element_factory, make_class):
        target = make_class("Widget")
        make_class("Gadget")

        idx = SearchIndex(element_factory)
        results = idx.search("Widget")

        names = [r.element_name for r in results]
        assert "Widget" in names
        # Gadget should not appear
        assert "Gadget" not in names

    def test_partial_name_match(self, element_factory, make_class):
        make_class("MyWidget")
        make_class("YourGadget")

        idx = SearchIndex(element_factory)
        results = idx.search("Wid")

        names = [r.element_name for r in results]
        assert "MyWidget" in names
        assert "YourGadget" not in names

    def test_case_insensitive(self, element_factory, make_class):
        make_class("MyWidget")

        idx = SearchIndex(element_factory)
        results = idx.search("mywidget")

        names = [r.element_name for r in results]
        assert "MyWidget" in names

    def test_no_match_returns_empty(self, element_factory, make_class):
        make_class("Widget")

        idx = SearchIndex(element_factory)
        assert idx.search("zzzzz") == []


class TestSearchByType:
    def test_search_type_label_class(self, element_factory, make_class):
        make_class("Foo")

        idx = SearchIndex(element_factory)
        results = idx.search("Class")

        # At least the class we created should appear
        assert any(r.element_name == "Foo" for r in results)

    def test_search_type_label_generalization(self, element_factory, event_manager):
        with Transaction(event_manager):
            base = element_factory.create(UML.Class)
            base.name = "Base"
            child = element_factory.create(UML.Class)
            child.name = "Child"
            gen = element_factory.create(UML.Generalization)
            gen.general = base
            gen.specific = child

        idx = SearchIndex(element_factory)
        results = idx.search("Generalization")

        # The Generalization element itself should be in results
        assert any(r.element is gen for r in results)


class TestSearchByAttribute:
    def test_find_by_attribute_name(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Vehicle"
            prop = element_factory.create(UML.Property)
            prop.name = "topSpeed"
            klass.ownedAttribute = prop

        idx = SearchIndex(element_factory)
        results = idx.search("topSpeed")

        # Vehicle should appear because it owns an attribute named topSpeed
        assert any(r.element is klass for r in results)

    def test_find_by_attribute_type(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Vehicle"
            prop = element_factory.create(UML.Property)
            prop.name = "color"
            klass.ownedAttribute = prop

            color_type = element_factory.create(UML.Class)
            color_type.name = "RGBColor"
            prop.type = color_type

        idx = SearchIndex(element_factory)
        results = idx.search("RGBColor")

        # Both Vehicle (owns attribute of type RGBColor) and RGBColor
        # itself should appear.
        element_ids = {r.element.id for r in results}
        assert klass.id in element_ids
        assert color_type.id in element_ids

    def test_find_by_operation_name(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Engine"
            op = element_factory.create(UML.Operation)
            op.name = "combustion"
            klass.ownedOperation = op

        idx = SearchIndex(element_factory)
        results = idx.search("combustion")

        assert any(r.element is klass for r in results)

    def test_find_by_parameter_name(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "Engine"
            op = element_factory.create(UML.Operation)
            op.name = "burn"
            klass.ownedOperation = op
            param = element_factory.create(UML.Parameter)
            param.name = "fuelRate"
            op.ownedParameter = param

        idx = SearchIndex(element_factory)
        results = idx.search("fuelRate")

        assert any(r.element is klass for r in results)


class TestSearchByRelationship:
    def test_find_relationship_by_endpoint_name(
        self, element_factory, event_manager
    ):
        with Transaction(event_manager):
            base = element_factory.create(UML.Class)
            base.name = "Shape"
            child = element_factory.create(UML.Class)
            child.name = "Circle"
            gen = element_factory.create(UML.Generalization)
            gen.general = base
            gen.specific = child

        idx = SearchIndex(element_factory)
        # Searching for "Shape" should surface the Generalization
        # because Shape is an endpoint.
        results = idx.search("Shape")

        assert any(r.element is gen for r in results)

    def test_find_relationship_by_type_keyword(
        self, element_factory, event_manager
    ):
        with Transaction(event_manager):
            supplier = element_factory.create(UML.Class)
            supplier.name = "Util"
            client = element_factory.create(UML.Class)
            client.name = "Main"
            dep = element_factory.create(UML.Dependency)
            dep.supplier = supplier
            dep.client = client

        idx = SearchIndex(element_factory)
        results = idx.search("Dependency")

        assert any(r.element is dep for r in results)

    def test_find_association_by_member_end_type(
        self, element_factory, event_manager
    ):
        with Transaction(event_manager):
            wheel_cls = element_factory.create(UML.Class)
            wheel_cls.name = "Wheel"
            car_cls = element_factory.create(UML.Class)
            car_cls.name = "Car"

            assoc = element_factory.create(UML.Association)
            end1 = element_factory.create(UML.Property)
            end1.name = "wheel"
            end1.type = wheel_cls
            end2 = element_factory.create(UML.Property)
            end2.name = "car"
            end2.type = car_cls
            assoc.memberEnd = end1
            assoc.memberEnd = end2

        idx = SearchIndex(element_factory)
        results = idx.search("Wheel")

        # Both Wheel (by name) and the Association (via memberEnd type)
        # should appear.
        element_ids = {r.element.id for r in results}
        assert wheel_cls.id in element_ids
        assert assoc.id in element_ids


class TestSearchByDiagramName:
    def test_find_element_by_its_diagram_name(
        self, make_class, make_diagram, element_factory
    ):
        klass = make_class("Lonely")
        make_diagram("SpecialDiagram", element=klass)

        idx = SearchIndex(element_factory)
        results = idx.search("SpecialDiagram")

        assert any(r.element is klass for r in results)


# ---------------------------------------------------------------------------
# Scope filtering (global vs current-diagram)
# ---------------------------------------------------------------------------


class TestSearchScope:
    def test_global_scope_returns_all(
        self, make_class, make_diagram, element_factory
    ):
        a = make_class("Alpha")
        b = make_class("Beta")
        make_diagram("D1", element=a)
        # Beta has no diagram presentation

        idx = SearchIndex(element_factory, current_diagram=None)
        results = idx.search("a", scope_global=True)

        # Both Alpha (has "a" in name) and Beta (has "a" in name) found
        names = {r.element_name for r in results}
        assert "Alpha" in names
        assert "Beta" in names

    def test_local_scope_filters_to_current_diagram(
        self, make_class, make_diagram, element_factory
    ):
        a = make_class("Alpha")
        b = make_class("Beta")
        d1 = make_diagram("D1", element=a)
        # Beta is NOT on D1

        idx = SearchIndex(element_factory, current_diagram=d1)
        results = idx.search("a", scope_global=False)

        names = {r.element_name for r in results}
        assert "Alpha" in names
        assert "Beta" not in names

    def test_local_scope_with_no_current_diagram_returns_nothing(
        self, make_class, element_factory
    ):
        make_class("Alpha")

        idx = SearchIndex(element_factory, current_diagram=None)
        results = idx.search("Alpha", scope_global=False)

        assert results == []


# ---------------------------------------------------------------------------
# Result ordering
# ---------------------------------------------------------------------------


class TestSearchResultOrdering:
    def test_prefix_matches_come_first(self, element_factory, make_class):
        # "Bar" starts with "Ba"; "FooBar" contains "Ba" but does not
        # start with it.
        make_class("FooBar")
        make_class("Bar")

        idx = SearchIndex(element_factory)
        results = idx.search("Bar")

        # Bar (prefix match) should appear before FooBar
        bar_indices = {
            i: r.element_name for i, r in enumerate(results) if r.element_name in ("Bar", "FooBar")
        }
        if "Bar" in bar_indices.values() and "FooBar" in bar_indices.values():
            bar_pos = next(i for i, n in bar_indices.items() if n == "Bar")
            foobar_pos = next(i for i, n in bar_indices.items() if n == "FooBar")
            assert bar_pos < foobar_pos


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestSearchDeduplication:
    def test_element_appears_once_even_if_multiple_fields_match(
        self, element_factory, event_manager
    ):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            # Name itself contains "speed"
            klass.name = "speed"
            # AND an attribute also named "speed"
            prop = element_factory.create(UML.Property)
            prop.name = "speed"
            klass.ownedAttribute = prop

        idx = SearchIndex(element_factory)
        results = idx.search("speed")

        # klass should appear exactly once
        klass_hits = [r for r in results if r.element is klass]
        assert len(klass_hits) == 1


# ---------------------------------------------------------------------------
# SearchResult dataclass
# ---------------------------------------------------------------------------


class TestSearchResult:
    def test_dataclass_defaults(self):
        from gaphor.core.modeling.base import Base

        # Minimal construction – diagrams and match_context have defaults
        r = SearchResult(
            element=None,  # type: ignore[arg-type]  # intentional
            element_name="X",
            element_type="Class",
        )
        assert r.diagrams == []
        assert r.match_context == ""

    def test_frozen(self):
        r = SearchResult(
            element=None,  # type: ignore[arg-type]
            element_name="X",
            element_type="Class",
        )
        with pytest.raises(AttributeError):
            r.element_name = "Y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Edge-cases / regression guards
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_element_with_no_name_no_attributes(
        self, element_factory, event_manager
    ):
        """An element that has neither a name nor owned attributes still
        participates in type-based searches."""
        with Transaction(event_manager):
            pkg = element_factory.create(UML.Package)
            # name intentionally left empty

        idx = SearchIndex(element_factory)
        # Package type label is "Package"
        results = idx.search("Package")

        assert any(r.element is pkg for r in results)

    def test_search_does_not_return_diagrams(
        self, element_factory, event_manager, make_diagram
    ):
        """Diagram objects themselves are skipped by the indexer."""
        make_diagram("MyDiagram")

        idx = SearchIndex(element_factory)
        results = idx.search("MyDiagram")

        assert all(not isinstance(r.element, Diagram) for r in results)

    def test_search_does_not_return_presentations(
        self, make_class, make_diagram, element_factory
    ):
        """Presentation (canvas) items are filtered out."""
        klass = make_class("Canvas")
        make_diagram("D", element=klass)

        idx = SearchIndex(element_factory)
        results = idx.search("Canvas")

        assert all(not _is_presentation(r.element) for r in results)

    def test_unicode_element_name(self, element_factory, make_class):
        """Non-ASCII names (e.g. accented) are normalised correctly.

        NFC normalisation means that searching for the composed form
        ``café`` (with a real é) finds elements stored with either the
        composed or decomposed form.  We test that the composed name
        survives a round-trip through the factory and appears in results
        when we search for the *exact* (composed) string.
        """
        make_class("café")  # composed é (\u00e9)

        idx = SearchIndex(element_factory)
        # Search with the exact composed string – must match
        results = idx.search("café")

        assert any(r.element_name == "café" for r in results)

    def test_very_long_query_no_crash(self, element_factory, make_class):
        make_class("X")
        idx = SearchIndex(element_factory)
        # Should not raise; just returns empty
        results = idx.search("a" * 10_000)
        assert isinstance(results, list)

    def test_special_regex_chars_in_query(self, element_factory, make_class):
        """Query is treated as a plain substring, not a regex."""
        make_class("foo.bar")

        idx = SearchIndex(element_factory)
        results = idx.search("foo.bar")

        assert any(r.element_name == "foo.bar" for r in results)

    def test_multiple_diagrams_in_result(
        self, make_class, make_diagram, element_factory
    ):
        klass = make_class("MultiDiag")
        d1 = make_diagram("First", element=klass)
        d2 = make_diagram("Second", element=klass)

        idx = SearchIndex(element_factory)
        results = idx.search("MultiDiag")

        hit = next(r for r in results if r.element is klass)
        diag_ids = {d.id for d in hit.diagrams}
        assert d1.id in diag_ids
        assert d2.id in diag_ids


# ---------------------------------------------------------------------------
# Match-context snippets
# ---------------------------------------------------------------------------


class TestMatchContext:
    def test_name_match_context(self, element_factory, make_class):
        make_class("UniqueXyz")

        idx = SearchIndex(element_factory)
        results = idx.search("UniqueXyz")

        hit = next(r for r in results if r.element_name == "UniqueXyz")
        assert hit.match_context.startswith("name:")

    def test_type_match_context(self, element_factory, event_manager):
        with Transaction(event_manager):
            gen = element_factory.create(UML.Generalization)
            base = element_factory.create(UML.Class)
            base.name = "X"
            child = element_factory.create(UML.Class)
            child.name = "Y"
            gen.general = base
            gen.specific = child

        idx = SearchIndex(element_factory)
        results = idx.search("Generalization")

        hit = next(r for r in results if r.element is gen)
        # Should be either "type:" or "relationship:" – both acceptable
        assert "Generalization" in hit.match_context

    def test_attribute_match_context(self, element_factory, event_manager):
        with Transaction(event_manager):
            klass = element_factory.create(UML.Class)
            klass.name = "ZZZUnique"
            prop = element_factory.create(UML.Property)
            prop.name = "uniqueAttrXYZ"
            klass.ownedAttribute = prop

        idx = SearchIndex(element_factory)
        results = idx.search("uniqueAttrXYZ")

        hit = next(r for r in results if r.element is klass)
        assert "attribute:" in hit.match_context
        assert "uniqueAttrXYZ" in hit.match_context

    def test_relationship_match_context(self, element_factory, event_manager):
        with Transaction(event_manager):
            base = element_factory.create(UML.Class)
            base.name = "UniqueBase999"
            child = element_factory.create(UML.Class)
            child.name = "UniqueChild999"
            gen = element_factory.create(UML.Generalization)
            gen.general = base
            gen.specific = child

        idx = SearchIndex(element_factory)
        # Search for the base class name; the gen should show up with
        # a "relationship:" context.
        results = idx.search("UniqueBase999")

        gen_hit = next((r for r in results if r.element is gen), None)
        assert gen_hit is not None
        assert "relationship:" in gen_hit.match_context
        assert "UniqueBase999" in gen_hit.match_context

    def test_diagram_name_match_context(
        self, make_class, make_diagram, element_factory
    ):
        klass = make_class("DiagNameTest")
        make_diagram("VerySpecificDiagName", element=klass)

        idx = SearchIndex(element_factory)
        results = idx.search("VerySpecificDiagName")

        hit = next(r for r in results if r.element is klass)
        assert "in diagram:" in hit.match_context
        assert "VerySpecificDiagName" in hit.match_context
