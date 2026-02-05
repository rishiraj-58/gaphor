from gaphor.core.modeling import Diagram
from gaphor.diagram.general import Line
from gaphor.diagram.propertypages import (
    AutoLayoutPropertyPage,
    InternalsPropertyPage,
    LineStylePage,
    NamePropertyPage,
    NotePropertyPage,
)
from gaphor.diagram.tests.fixtures import find
from gaphor.UML import Class, Comment
from gaphor.UML.classes import ClassItem
from gaphor.UML.general import CommentItem


def test_name_page(element_factory, event_manager):
    diagram = element_factory.create(Diagram)
    property_page = NamePropertyPage(diagram, event_manager)
    widget = property_page.construct()
    name = find(widget, "name-entry")
    name.set_text("A new note")

    assert diagram.name == "A new note"


def test_line_style_page_rectilinear(diagram, event_manager):
    item = diagram.create(Line)
    property_page = LineStylePage(item, event_manager)
    widget = property_page.construct()
    line_rectangular = find(widget, "line-rectilinear")

    line_rectangular.set_active(True)

    assert item.orthogonal


def test_line_style_page_orientation(diagram, event_manager):
    item = diagram.create(Line)
    property_page = LineStylePage(item, event_manager)
    widget = property_page.construct()
    flip_orientation = find(widget, "flip-orientation")
    flip_orientation.set_active(True)

    assert item.horizontal


def test_note_page_with_item_without_subject(diagram, event_manager):
    item = diagram.create(Line)
    property_page = NotePropertyPage(item, event_manager)
    widget = property_page.construct()

    assert not widget


def test_note_page_with_item_with_subject(create, event_manager):
    item = create(CommentItem, Comment)
    property_page = NotePropertyPage(item, event_manager)
    widget = property_page.construct()

    note = find(widget, "note")
    note.get_buffer().set_text("A new note")

    assert item.subject.note == "A new note"


def test_note_page_with_subject(element_factory, event_manager):
    comment = element_factory.create(Comment)
    property_page = NotePropertyPage(comment, event_manager)
    widget = property_page.construct()

    note = find(widget, "note")
    note.get_buffer().set_text("A new note")

    assert comment.note == "A new note"


def test_internals_page_for_presentation(create):
    subject = create(CommentItem, Comment)
    property_page = InternalsPropertyPage(subject)
    widget = property_page.construct()

    internals = find(widget, "internals")
    text = internals.get_label()

    assert "CommentItem" in text
    assert "gaphor.UML.Comment" in text


def test_auto_layout_page_for_presentation(create, event_manager):
    """Test that auto-layout property page shows pinned switch."""
    item = create(ClassItem, Class)
    property_page = AutoLayoutPropertyPage(item, event_manager)
    widget = property_page.construct()

    assert widget is not None
    pinned_switch = find(widget, "pinned-switch")
    assert pinned_switch is not None
    assert pinned_switch.get_active() is False


def test_auto_layout_page_toggle_pinned(create, event_manager):
    """Test toggling pinned state via property page."""
    item = create(ClassItem, Class)
    property_page = AutoLayoutPropertyPage(item, event_manager)
    widget = property_page.construct()

    pinned_switch = find(widget, "pinned-switch")

    # Initially not pinned
    assert item.pinned is False
    assert pinned_switch.get_active() is False

    # Toggle pinned on
    pinned_switch.set_active(True)
    assert item.pinned is True

    # Toggle pinned off
    pinned_switch.set_active(False)
    assert item.pinned is False


def test_auto_layout_page_reflects_pinned_state(create, event_manager):
    """Test that property page reflects current pinned state."""
    item = create(ClassItem, Class)

    # Pre-set pinned state
    item.pinned = True

    property_page = AutoLayoutPropertyPage(item, event_manager)
    widget = property_page.construct()

    pinned_switch = find(widget, "pinned-switch")
    assert pinned_switch.get_active() is True


def test_auto_layout_page_for_line(diagram, event_manager):
    """Test that auto-layout property page works for line items."""
    item = diagram.create(Line)
    property_page = AutoLayoutPropertyPage(item, event_manager)
    widget = property_page.construct()

    assert widget is not None
    pinned_switch = find(widget, "pinned-switch")
    assert pinned_switch is not None


def test_auto_layout_page_for_non_presentation(element_factory, event_manager):
    """Test that auto-layout property page returns None for non-presentations."""
    comment = element_factory.create(Comment)
    property_page = AutoLayoutPropertyPage(comment, event_manager)
    widget = property_page.construct()

    # Non-presentation items don't have pinned attribute
    assert widget is None
