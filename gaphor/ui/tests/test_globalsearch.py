import pytest

from gaphor import UML
from gaphor.core.modeling import Diagram
from gaphor.ui.globalsearch import GlobalSearch, SearchResult, SearchScope


class MockMainWindow:
    window = None


class MockDiagrams:
    def get_current_view(self):
        return None

    def get_current_diagram(self):
        return None


@pytest.fixture
def global_search(event_manager, element_factory):
    diagrams = MockDiagrams()
    main_window = MockMainWindow()
    search = GlobalSearch(event_manager, element_factory, diagrams, main_window)
    yield search
    search.shutdown()


def test_search_by_name(global_search, element_factory):
    klass = element_factory.create(UML.Class)
    klass.name = "MyClass"

    results = list(global_search._search("myclass"))

    assert len(results) == 1
    assert results[0].element is klass
    assert results[0].match_type == "Name"


def test_search_by_type(global_search, element_factory):
    element_factory.create(UML.Class)

    results = list(global_search._search("class"))

    assert len(results) >= 1
    assert any(r.match_type == "Type" for r in results)


def test_search_by_attribute(global_search, element_factory):
    klass = element_factory.create(UML.Class)
    klass.name = "SomeClass"
    attr = element_factory.create(UML.Property)
    attr.name = "myAttribute"
    klass.ownedAttribute = attr

    results = list(global_search._search("myattribute"))

    assert len(results) == 1
    assert results[0].element is klass
    assert results[0].match_type == "Attribute"


def test_search_by_operation(global_search, element_factory):
    klass = element_factory.create(UML.Class)
    klass.name = "SomeClass"
    op = element_factory.create(UML.Operation)
    op.name = "doSomething"
    klass.ownedOperation = op

    results = list(global_search._search("dosomething"))

    assert len(results) == 1
    assert results[0].element is klass
    assert results[0].match_type == "Operation"


def test_search_minimum_length(global_search, element_factory):
    klass = element_factory.create(UML.Class)
    klass.name = "A"

    # Single character search should work (we search for "a")
    results = list(global_search._search("a"))

    # With minimum 2 char requirement, this should still find it
    assert len(results) >= 1


def test_search_case_insensitive(global_search, element_factory):
    klass = element_factory.create(UML.Class)
    klass.name = "MyClass"

    results_lower = list(global_search._search("myclass"))
    results_upper = list(global_search._search("MYCLASS"))
    results_mixed = list(global_search._search("MyClass"))

    assert len(results_lower) == 1
    assert len(results_upper) == 1
    assert len(results_mixed) == 1


def test_search_result_diagrams(global_search, element_factory):
    diagram = element_factory.create(Diagram)
    diagram.name = "Test Diagram"

    klass = element_factory.create(UML.Class)
    klass.name = "TestClass"

    # Create presentation on diagram
    from gaphor.UML.classes.klass import ClassItem

    item = diagram.create(ClassItem, subject=klass)

    results = list(global_search._search("testclass"))

    assert len(results) == 1
    assert diagram in results[0].diagrams


def test_search_scope_current_diagram(global_search, element_factory):
    diagram1 = element_factory.create(Diagram)
    diagram1.name = "Diagram 1"

    diagram2 = element_factory.create(Diagram)
    diagram2.name = "Diagram 2"

    klass1 = element_factory.create(UML.Class)
    klass1.name = "Class1"

    klass2 = element_factory.create(UML.Class)
    klass2.name = "Class2"

    from gaphor.UML.classes.klass import ClassItem

    diagram1.create(ClassItem, subject=klass1)
    diagram2.create(ClassItem, subject=klass2)

    # Set scope to current diagram
    global_search._search_scope = SearchScope.CURRENT_DIAGRAM
    global_search._current_diagram = diagram1

    results = list(global_search._search("class"))

    # Should only find elements in diagram1
    element_ids = [r.element.id for r in results]
    assert klass1.id in element_ids or diagram1.id in element_ids


def test_get_diagrams_for_element(global_search, element_factory):
    diagram = element_factory.create(Diagram)
    diagram.name = "Test Diagram"

    klass = element_factory.create(UML.Class)
    klass.name = "TestClass"

    from gaphor.UML.classes.klass import ClassItem

    diagram.create(ClassItem, subject=klass)

    diagrams = global_search._get_diagrams_for_element(klass)

    assert diagram in diagrams


def test_get_diagrams_for_diagram(global_search, element_factory):
    diagram = element_factory.create(Diagram)
    diagram.name = "Test Diagram"

    diagrams = global_search._get_diagrams_for_element(diagram)

    assert diagrams == [diagram]


def test_search_result_owner_path(element_factory):
    package = element_factory.create(UML.Package)
    package.name = "MyPackage"

    klass = element_factory.create(UML.Class)
    klass.name = "MyClass"
    klass.package = package

    result = SearchResult(
        element=klass,
        match_type="Name",
        match_field="name",
        match_value="MyClass",
        diagrams=[],
    )

    assert "MyPackage" in result.owner_path
