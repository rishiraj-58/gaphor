"""Performance tests for auto-layout with pinned elements.

These tests verify that the pinned attribute access is efficient
even with many elements.
"""

import time

from gaphor import UML
from gaphor.core import Transaction
from gaphor.diagram.tests.fixtures import connect
from gaphor.plugins.autolayout.pydot import AutoLayout
from gaphor.UML.diagramitems import AssociationItem, ClassItem


def test_layout_performance_with_many_elements(diagram, create, event_manager):
    """Test that auto-layout performs well with many elements.
    
    This test creates a moderate number of elements and verifies
    the layout completes in reasonable time.
    """
    # Create 50 classes and connections (moderate test)
    classes = []
    for i in range(50):
        c = create(ClassItem, UML.Class)
        classes.append(c)
    
    # Create associations between consecutive classes
    associations = []
    for i in range(len(classes) - 1):
        a = create(AssociationItem)
        connect(a, a.head, classes[i])
        connect(a, a.tail, classes[i + 1])
        associations.append(a)
    
    # Pin half the elements
    with Transaction(event_manager):
        for i, c in enumerate(classes):
            if i % 2 == 0:
                c.pinned = True
    
    # Time the layout
    start_time = time.time()
    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)
    elapsed = time.time() - start_time
    
    # Layout should complete in reasonable time (< 10 seconds)
    # This is a generous limit for CI environments
    assert elapsed < 10.0, f"Layout took too long: {elapsed:.2f}s"


def test_is_pinned_check_is_efficient(diagram, create):
    """Test that checking pinned state is efficient."""
    # Create elements
    classes = [create(ClassItem, UML.Class) for _ in range(100)]
    
    auto_layout = AutoLayout()
    
    # Time many pinned checks
    start_time = time.time()
    for _ in range(1000):
        for c in classes:
            auto_layout._is_pinned(c)
    elapsed = time.time() - start_time
    
    # 100,000 checks should be very fast (< 1 second)
    assert elapsed < 1.0, f"Pinned checks too slow: {elapsed:.2f}s for 100k checks"


def test_pinned_elements_are_skipped_efficiently(diagram, create, event_manager):
    """Test that pinned elements are properly skipped without overhead."""
    # Create elements, all pinned
    classes = []
    for _ in range(20):
        c = create(ClassItem, UML.Class)
        c.pinned = True
        classes.append(c)
    
    # Create some connections
    for i in range(len(classes) - 1):
        a = create(AssociationItem)
        a.pinned = True
        connect(a, a.head, classes[i])
        connect(a, a.tail, classes[i + 1])
    
    # Store original positions
    original_positions = {c.id: (c.matrix[4], c.matrix[5]) for c in classes}
    
    # Layout should be fast when all elements are pinned (nothing to do)
    start_time = time.time()
    auto_layout = AutoLayout(event_manager)
    auto_layout.layout(diagram)
    elapsed = time.time() - start_time
    
    # Verify positions unchanged
    for c in classes:
        assert (c.matrix[4], c.matrix[5]) == original_positions[c.id]
    
    # Should be very fast since everything is pinned
    assert elapsed < 5.0, f"Layout with all pinned took too long: {elapsed:.2f}s"
