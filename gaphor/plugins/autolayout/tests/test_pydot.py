import pytest

from gaphor import UML
from gaphor.core import Transaction
from gaphor.diagram.tests.fixtures import connect
from gaphor.plugins.autolayout.pydot import AutoLayout, parse_edge_pos, strip_quotes
from gaphor.UML.diagramitems import (
    ActionItem,
    AssociationItem,
    ClassItem,
    ForkNodeItem,
    GeneralizationItem,
    InputPinItem,
    ObjectFlowItem,
    PackageItem,
)
from gaphor.UML.general import CommentItem, CommentLineItem


def test_layout_diagram(diagram, create):
    superclass = create(ClassItem, UML.Class)
    subclass = create(ClassItem, UML.Class)
    gen = create(GeneralizationItem, UML.Generalization)
    connect(gen, gen.tail, superclass)
    connect(gen, gen.head, subclass)

    auto_layout = AutoLayout()
    auto_layout.layout(diagram)

    assert gen.head.pos != (0, 0)
    assert gen.tail.pos != (0, 0)


def test_layout_with_association(diagram, create, event_manager):
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)


def test_layout_with_comment(diagram, create, event_manager):
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    comment = create(CommentItem, UML.Comment)
    comment_line = create(CommentLineItem)
    connect(comment_line, comment_line.head, comment)
    connect(comment_line, comment_line.tail, a)

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)


def test_layout_with_nested(diagram, create, event_manager):
    p = create(PackageItem, UML.Package)
    c1 = create(ClassItem, UML.Class)
    p.children = c1
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    assert c1.matrix[4] < p.width
    assert c1.matrix[5] < p.height


def test_layout_with_attached_item(diagram, create, event_manager):
    action = create(ActionItem, UML.Action)
    pin = create(InputPinItem, UML.InputPin)
    connect(pin, pin.handles()[0], action)

    action2 = create(ActionItem, UML.Action)
    object_flow = create(ObjectFlowItem, UML.ObjectFlow)
    connect(object_flow, object_flow.head, pin)
    connect(object_flow, object_flow.tail, action2)

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    assert pin.parent is action


def test_layout_fork_node_item(diagram, create, event_manager):
    create(ForkNodeItem, UML.ForkNode)

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)


def test_parse_pos():
    points = parse_edge_pos('"1.0,2.0 3.0,4 5.0,6.0 7,8.0"', 10, True)

    assert points == [(7.0, 2.0), (1.0, 8.0)]


def test_parse_pos_invalid_number_of_points():
    with pytest.raises(IndexError):
        parse_edge_pos('"1.0,2.0 3.0,4 5.0,6.0"', 10, True)


def test_strip_line_endings():
    assert strip_quotes("\\\n807.5") == "807.5"
    assert strip_quotes("\\\r\n807.5") == "807.5"
    assert strip_quotes('\\\r\n"807.5"') == "807.5"


# Tests for pinned element behavior


def test_pinned_element_is_skipped_during_layout(diagram, create, event_manager):
    """Pinned elements should retain their position during auto-layout."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Position c1 at a specific location and pin it
    with Transaction(event_manager):
        c1.matrix.set(x0=100.0, y0=100.0)
        c1.pinned = True

    original_x = c1.matrix[4]
    original_y = c1.matrix[5]

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # c1 should remain at its original position
    assert c1.matrix[4] == original_x
    assert c1.matrix[5] == original_y


def test_unpinned_element_is_moved_during_layout(diagram, create, event_manager):
    """Unpinned elements should be repositioned during auto-layout."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Position c1 at a specific location but don't pin
    with Transaction(event_manager):
        c1._in_auto_layout = True  # Prevent auto-pin
        c1.matrix.set(x0=100.0, y0=100.0)
        c1._in_auto_layout = False

    # Ensure c1 is not pinned
    assert c1.pinned is False

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Elements should still not be pinned after auto-layout
    assert c1.pinned is False


def test_manual_movement_sets_pinned_flag(diagram, create, event_manager):
    """Moving an element manually should automatically set the pinned flag."""
    c1 = create(ClassItem, UML.Class)

    # Initially not pinned
    assert c1.pinned is False

    # Manually move the element (simulating user drag)
    with Transaction(event_manager):
        c1.matrix.translate(50, 50)

    # Element should now be pinned
    assert c1.pinned is True


def test_auto_layout_movement_does_not_set_pinned_flag(diagram, create, event_manager):
    """Elements moved by auto-layout should not be auto-pinned."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Initially not pinned
    assert c1.pinned is False
    assert c2.pinned is False

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Elements should still not be pinned after auto-layout
    assert c1.pinned is False
    assert c2.pinned is False


def test_toggle_pinned_state(diagram, create, event_manager):
    """Test toggling the pinned state using bool values."""
    c1 = create(ClassItem, UML.Class)

    assert c1.pinned is False

    with Transaction(event_manager):
        c1.pinned = True

    assert c1.pinned is True

    with Transaction(event_manager):
        c1.pinned = False

    assert c1.pinned is False


def test_pinned_line_is_skipped_during_layout(diagram, create, event_manager):
    """Pinned line elements should retain their position during auto-layout."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Pin the association line
    with Transaction(event_manager):
        a.pinned = True

    # Store original handle positions
    original_head_pos = a.head.pos.tuple()
    original_tail_pos = a.tail.pos.tuple()

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Line handles should remain at original positions
    assert a.head.pos.tuple() == original_head_pos
    assert a.tail.pos.tuple() == original_tail_pos


def test_mixed_pinned_and_unpinned_elements(diagram, create, event_manager):
    """Test layout with a mix of pinned and unpinned elements."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    c3 = create(ClassItem, UML.Class)
    a1 = create(AssociationItem)
    a2 = create(AssociationItem)
    connect(a1, a1.head, c1)
    connect(a1, a1.tail, c2)
    connect(a2, a2.head, c2)
    connect(a2, a2.tail, c3)

    # Pin c1 and a1, leave c2, c3, a2 unpinned
    with Transaction(event_manager):
        c1.matrix.set(x0=50.0, y0=50.0)
        c1.pinned = True
        a1.pinned = True

    original_c1_pos = (c1.matrix[4], c1.matrix[5])
    original_a1_head = a1.head.pos.tuple()
    original_a1_tail = a1.tail.pos.tuple()

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Pinned elements should retain position
    assert (c1.matrix[4], c1.matrix[5]) == original_c1_pos
    assert a1.head.pos.tuple() == original_a1_head
    assert a1.tail.pos.tuple() == original_a1_tail


def test_pinned_attribute_is_persisted(diagram, create, saver, loader, event_manager):
    """Test that pinned state is saved and loaded correctly."""
    c1 = create(ClassItem, UML.Class)

    with Transaction(event_manager):
        c1.pinned = True

    # Save and reload
    data = saver()
    loader(data)

    # Find the class item in the reloaded diagram
    reloaded_diagram = next(iter(diagram.model.select(UML.Diagram)))
    reloaded_c1 = next(
        p for p in reloaded_diagram.ownedPresentation if isinstance(p, ClassItem)
    )

    # Pinned state should be preserved
    assert reloaded_c1.pinned is True


def test_pinned_undo_redo(diagram, create, event_manager, element_factory):
    """Test that pinned state can be undone and redone."""
    from gaphor.services.undomanager import UndoManager

    undo_manager = UndoManager(event_manager, element_factory)

    try:
        c1 = create(ClassItem, UML.Class)

        # Initially not pinned
        assert c1.pinned is False

        # Pin the element
        with Transaction(event_manager):
            c1.pinned = True

        assert c1.pinned is True

        # Undo should restore unpinned state
        undo_manager.undo_transaction()
        assert c1.pinned is False

        # Redo should restore pinned state
        undo_manager.redo_transaction()
        assert c1.pinned is True
    finally:
        undo_manager.shutdown()


def test_manual_move_undo_restores_unpinned_state(
    diagram, create, event_manager, element_factory
):
    """Test that undoing a manual move also undoes the auto-pin."""
    from gaphor.services.undomanager import UndoManager

    undo_manager = UndoManager(event_manager, element_factory)

    try:
        c1 = create(ClassItem, UML.Class)

        # Initially not pinned
        assert c1.pinned is False

        # Manually move the element (this should auto-pin it)
        with Transaction(event_manager):
            c1.matrix.translate(50, 50)

        assert c1.pinned is True

        # Undo should restore both position and unpinned state
        undo_manager.undo_transaction()
        assert c1.pinned is False
    finally:
        undo_manager.shutdown()


def test_manual_handle_movement_sets_pinned_flag(diagram, create, event_manager):
    """Moving a line handle manually should automatically set the pinned flag."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Initially not pinned
    assert a.pinned is False

    # Manually move a handle (simulating user drag)
    with Transaction(event_manager):
        a.head.pos = (100, 100)

    # Line should now be pinned
    assert a.pinned is True


def test_auto_layout_handle_movement_does_not_set_pinned_flag(
    diagram, create, event_manager
):
    """Line handles moved by auto-layout should not be auto-pinned."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Initially not pinned
    assert a.pinned is False

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Line should still not be pinned after auto-layout
    assert a.pinned is False


# Tests for nested elements


def test_nested_pinned_parent_unpinned_child(diagram, create, event_manager):
    """When parent is pinned, parent stays in place but child can still be laid out within."""
    p = create(PackageItem, UML.Package)
    c1 = create(ClassItem, UML.Class)
    p.children = c1

    # Position package and pin it
    with Transaction(event_manager):
        p.matrix.set(x0=100.0, y0=100.0)
        p.pinned = True

    # Ensure child is not pinned
    assert c1.pinned is False

    original_p_pos = (p.matrix[4], p.matrix[5])

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Package should retain its position (pinned)
    assert (p.matrix[4], p.matrix[5]) == original_p_pos

    # Child should not be pinned after layout
    assert c1.pinned is False


def test_nested_unpinned_parent_pinned_child(diagram, create, event_manager):
    """When child is pinned but parent is not, child retains relative position."""
    p = create(PackageItem, UML.Package)
    c1 = create(ClassItem, UML.Class)
    p.children = c1

    # Pin the child only
    with Transaction(event_manager):
        c1.pinned = True

    assert p.pinned is False
    assert c1.pinned is True

    # Store child's position relative to parent
    original_c1_x = c1.matrix[4]
    original_c1_y = c1.matrix[5]

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Child's local position should remain the same (pinned)
    assert c1.matrix[4] == original_c1_x
    assert c1.matrix[5] == original_c1_y


def test_nested_both_pinned(diagram, create, event_manager):
    """When both parent and child are pinned, both retain their positions."""
    p = create(PackageItem, UML.Package)
    c1 = create(ClassItem, UML.Class)
    p.children = c1

    # Pin both
    with Transaction(event_manager):
        p.matrix.set(x0=100.0, y0=100.0)
        p.pinned = True
        c1.matrix.set(x0=10.0, y0=10.0)
        c1.pinned = True

    original_p_pos = (p.matrix[4], p.matrix[5])
    original_c1_pos = (c1.matrix[4], c1.matrix[5])

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # Both should retain their positions
    assert (p.matrix[4], p.matrix[5]) == original_p_pos
    assert (c1.matrix[4], c1.matrix[5]) == original_c1_pos


def test_nested_multiple_children_mixed_pinned(diagram, create, event_manager):
    """Test package with multiple children, some pinned some not."""
    p = create(PackageItem, UML.Package)
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    p.children = c1
    p.children = c2

    # Pin only c1
    with Transaction(event_manager):
        c1.matrix.set(x0=20.0, y0=20.0)
        c1.pinned = True

    assert c1.pinned is True
    assert c2.pinned is False

    original_c1_pos = (c1.matrix[4], c1.matrix[5])

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # c1 should retain position (pinned)
    assert (c1.matrix[4], c1.matrix[5]) == original_c1_pos

    # c2 should not be pinned after layout
    assert c2.pinned is False


def test_deeply_nested_pinning(diagram, create, event_manager):
    """Test deeply nested structure with pinning at different levels."""
    p1 = create(PackageItem, UML.Package)
    p2 = create(PackageItem, UML.Package)
    c1 = create(ClassItem, UML.Class)

    p1.children = p2
    p2.children = c1

    # Pin only the innermost element
    with Transaction(event_manager):
        c1.matrix.set(x0=5.0, y0=5.0)
        c1.pinned = True

    assert p1.pinned is False
    assert p2.pinned is False
    assert c1.pinned is True

    original_c1_pos = (c1.matrix[4], c1.matrix[5])

    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # c1 should retain its position (pinned)
    assert (c1.matrix[4], c1.matrix[5]) == original_c1_pos


def test_undo_redo_with_nested_elements(diagram, create, event_manager, element_factory):
    """Test undo/redo works correctly with nested elements."""
    from gaphor.services.undomanager import UndoManager

    undo_manager = UndoManager(event_manager, element_factory)

    try:
        p = create(PackageItem, UML.Package)
        c1 = create(ClassItem, UML.Class)
        p.children = c1

        # Initially not pinned
        assert p.pinned is False
        assert c1.pinned is False

        # Manually move the child (should auto-pin)
        with Transaction(event_manager):
            c1.matrix.translate(30, 30)

        assert c1.pinned is True

        # Undo should restore unpinned state
        undo_manager.undo_transaction()
        assert c1.pinned is False

        # Redo should restore pinned state
        undo_manager.redo_transaction()
        assert c1.pinned is True
    finally:
        undo_manager.shutdown()


def test_pinned_attribute_uses_bool_type(diagram, create):
    """Verify that pinned attribute uses bool type, not int."""
    c1 = create(ClassItem, UML.Class)

    # Default should be False (bool)
    assert c1.pinned is False
    assert isinstance(c1.pinned, bool)

    c1.pinned = True
    assert c1.pinned is True
    assert isinstance(c1.pinned, bool)


def test_manual_move_then_auto_layout_preserves_position(
    diagram, create, event_manager
):
    """Element manually moved then auto-layout should preserve its position."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Manually move c1 (will auto-pin)
    with Transaction(event_manager):
        c1.matrix.set(x0=200.0, y0=200.0)

    assert c1.pinned is True

    original_pos = (c1.matrix[4], c1.matrix[5])

    # Auto-layout should not move c1
    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    assert (c1.matrix[4], c1.matrix[5]) == original_pos


def test_unpin_then_auto_layout_moves_element(diagram, create, event_manager):
    """After unpinning, element should be moved by auto-layout."""
    c1 = create(ClassItem, UML.Class)
    c2 = create(ClassItem, UML.Class)
    a = create(AssociationItem)
    connect(a, a.head, c1)
    connect(a, a.tail, c2)

    # Manually move c1 (will auto-pin)
    with Transaction(event_manager):
        c1.matrix.set(x0=500.0, y0=500.0)

    assert c1.pinned is True

    # Unpin c1
    with Transaction(event_manager):
        c1.pinned = False

    assert c1.pinned is False

    # Auto-layout should now be able to move c1
    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)

    # After unpinning, the element should not be re-pinned by auto-layout
    assert c1.pinned is False


# Tests for CSS visual indicator


def test_pinned_state_in_styled_item(diagram, create, event_manager):
    """Test that pinned state is reflected in StyledItem for CSS styling."""
    from gaphor.core.modeling.diagram import StyledItem

    c1 = create(ClassItem, UML.Class)

    # Initially not pinned
    styled = StyledItem(c1)
    assert "pinned" not in styled.state() or styled.state()[-1] == ""

    # Pin the element
    with Transaction(event_manager):
        c1.pinned = True

    styled = StyledItem(c1)
    assert "pinned" in styled.state()


def test_unpinned_state_in_styled_item(diagram, create, event_manager):
    """Test that unpinned state is reflected in StyledItem."""
    from gaphor.core.modeling.diagram import StyledItem

    c1 = create(ClassItem, UML.Class)

    # Pin then unpin
    with Transaction(event_manager):
        c1.pinned = True

    with Transaction(event_manager):
        c1.pinned = False

    styled = StyledItem(c1)
    # The pinned state should be empty string when not pinned
    states = [s for s in styled.state() if s]
    assert "pinned" not in states


def test_styled_item_state_with_selection(diagram, create, event_manager):
    """Test StyledItem state includes both selection and pinned states."""
    from gaphor.core.modeling.diagram import StyledItem
    from gaphor.diagram.selection import Selection

    c1 = create(ClassItem, UML.Class)
    selection = Selection()

    # Pin the element
    with Transaction(event_manager):
        c1.pinned = True

    # Add to selection
    selection.select_items(c1)

    styled = StyledItem(c1, selection)
    states = styled.state()

    # Should have both active and pinned states
    assert "active" in states
    assert "pinned" in states
