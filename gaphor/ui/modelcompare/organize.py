"""Organize model comparison changes into a tree structure."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from gi.repository import Gio, GObject

from gaphor.i18n import gettext
from gaphor.ui.modelcompare.differ import (
    Change,
    ChangeCategory,
    ChangeType,
    DiffResult,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory


class CompareNode(GObject.Object):
    """A node in the comparison tree view."""

    def __init__(
        self,
        changes: list[Change],
        children: list[CompareNode],
        label: str,
        node_type: str = "group",
    ):
        super().__init__()
        self._changes = changes
        self._label = label
        self._node_type = node_type
        self.children: Gio.ListStore | None = (
            _as_list_store(children) if children else None
        )
        self._selected = False
        self._sync()

    @GObject.Property(type=str)
    def label(self) -> str:
        return self._label

    @GObject.Property(type=str)
    def node_type(self) -> str:
        return self._node_type

    @GObject.Property(type=bool, default=False)
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self._selected = value
        self._propagate_selection(value)

    @GObject.Property(type=str)
    def change_type_css(self) -> str:
        """CSS class for styling based on change type."""
        if not self._changes:
            return ""
        change_type = self._changes[0].change_type
        return f"change-{change_type.value}"

    @GObject.Property(type=int)
    def change_count(self) -> int:
        count = len(self._changes)
        if self.children:
            for child in self.children:
                count += child.change_count
        return count

    @property
    def changes(self) -> list[Change]:
        return self._changes

    def all_changes(self) -> list[Change]:
        """Get all changes including those from children."""
        result = list(self._changes)
        if self.children:
            for child in self.children:
                result.extend(child.all_changes())
        return result

    def _propagate_selection(self, value: bool):
        """Propagate selection state to children."""
        if self.children:
            for child in self.children:
                child._selected = value
                child.notify("selected")
                child._propagate_selection(value)

    def _sync(self):
        """Sync selection state from children."""
        if self.children:
            all_selected = all(c.selected for c in self.children)
            any_selected = any(c.selected for c in self.children)
            self._selected = all_selected
            self.notify("selected")


def _as_list_store(items: list[CompareNode]) -> Gio.ListStore:
    store = Gio.ListStore.new(CompareNode.__gtype__)
    for item in items:
        store.append(item)
    return store


def organize_diff_result(
    diff_result: DiffResult,
    base_factory: ElementFactory | None = None,
    compare_factory: ElementFactory | None = None,
) -> Gio.ListStore:
    """Organize diff result into a tree structure for display.

    Groups changes by:
    1. Change type (Added, Removed, Modified)
    2. Element type
    3. Individual changes
    """
    root_nodes: list[CompareNode] = []

    # Group by change type
    added_changes = diff_result.added
    removed_changes = diff_result.removed
    modified_changes = diff_result.modified

    if added_changes:
        added_node = _create_change_type_node(
            added_changes,
            ChangeType.ADDED,
            gettext("Added ({count})").format(count=len(added_changes)),
            base_factory,
            compare_factory,
        )
        root_nodes.append(added_node)

    if removed_changes:
        removed_node = _create_change_type_node(
            removed_changes,
            ChangeType.REMOVED,
            gettext("Removed ({count})").format(count=len(removed_changes)),
            base_factory,
            compare_factory,
        )
        root_nodes.append(removed_node)

    if modified_changes:
        modified_node = _create_change_type_node(
            modified_changes,
            ChangeType.MODIFIED,
            gettext("Modified ({count})").format(count=len(modified_changes)),
            base_factory,
            compare_factory,
        )
        root_nodes.append(modified_node)

    return _as_list_store(root_nodes)


def _create_change_type_node(
    changes: list[Change],
    change_type: ChangeType,
    label: str,
    base_factory: ElementFactory | None,
    compare_factory: ElementFactory | None,
) -> CompareNode:
    """Create a node for a change type (Added/Removed/Modified)."""
    # Group by element type
    by_element_type: dict[str, list[Change]] = {}
    for change in changes:
        element_type = change.element_type
        if element_type not in by_element_type:
            by_element_type[element_type] = []
        by_element_type[element_type].append(change)

    children: list[CompareNode] = []
    for element_type, type_changes in sorted(by_element_type.items()):
        type_node = _create_element_type_node(
            type_changes,
            element_type,
            change_type,
            base_factory,
            compare_factory,
        )
        children.append(type_node)

    return CompareNode([], children, label, f"change-type-{change_type.value}")


def _create_element_type_node(
    changes: list[Change],
    element_type: str,
    change_type: ChangeType,
    base_factory: ElementFactory | None,
    compare_factory: ElementFactory | None,
) -> CompareNode:
    """Create a node for an element type."""
    # Group by element id for modifications
    by_element: dict[str, list[Change]] = {}
    for change in changes:
        element_id = change.element_id
        if element_id not in by_element:
            by_element[element_id] = []
        by_element[element_id].append(change)

    children: list[CompareNode] = []
    for element_id, element_changes in by_element.items():
        element_node = _create_element_node(
            element_changes,
            element_id,
            change_type,
            base_factory,
            compare_factory,
        )
        children.append(element_node)

    label = gettext("{type} ({count})").format(
        type=element_type, count=len(by_element)
    )
    return CompareNode([], children, label, "element-type")


def _create_element_node(
    changes: list[Change],
    element_id: str,
    change_type: ChangeType,
    base_factory: ElementFactory | None,
    compare_factory: ElementFactory | None,
) -> CompareNode:
    """Create a node for an individual element."""
    first_change = changes[0]
    element_name = first_change.element_name or element_id[:8]

    # For modified elements, show property changes as children
    if change_type == ChangeType.MODIFIED and len(changes) > 1:
        property_children = [
            CompareNode(
                [c],
                [],
                _format_property_change(c),
                "property-change",
            )
            for c in changes
        ]
        return CompareNode(
            [],
            property_children,
            element_name,
            f"element-{change_type.value}",
        )

    return CompareNode(
        changes,
        [],
        f"{element_name}: {first_change.description}",
        f"element-{change_type.value}",
    )


def _format_property_change(change: Change) -> str:
    """Format a property change for display."""
    if change.category == ChangeCategory.PROPERTY:
        if change.change_type == ChangeType.ADDED:
            return gettext("{prop}: set to '{value}'").format(
                prop=change.property_name,
                value=_truncate(str(change.new_value)),
            )
        elif change.change_type == ChangeType.REMOVED:
            return gettext("{prop}: cleared (was '{value}')").format(
                prop=change.property_name,
                value=_truncate(str(change.old_value)),
            )
        else:
            return gettext("{prop}: '{old}' → '{new}'").format(
                prop=change.property_name,
                old=_truncate(str(change.old_value)),
                new=_truncate(str(change.new_value)),
            )
    elif change.category == ChangeCategory.RELATIONSHIP:
        if change.change_type == ChangeType.ADDED:
            return gettext("{prop}: added reference").format(prop=change.property_name)
        elif change.change_type == ChangeType.REMOVED:
            return gettext("{prop}: removed reference").format(prop=change.property_name)
        else:
            return gettext("{prop}: changed reference").format(prop=change.property_name)
    return change.description


def _truncate(value: str, max_length: int = 30) -> str:
    """Truncate a string value for display."""
    if len(value) > max_length:
        return value[: max_length - 3] + "..."
    return value


def organize_by_diagram(
    diff_result: DiffResult,
    base_factory: ElementFactory | None = None,
    compare_factory: ElementFactory | None = None,
) -> Gio.ListStore:
    """Organize changes by diagram."""
    root_nodes: list[CompareNode] = []

    # Group changes by diagram
    by_diagram: dict[str | None, list[Change]] = {}
    for change in diff_result.changes:
        diagram_id = change.diagram_id
        if diagram_id not in by_diagram:
            by_diagram[diagram_id] = []
        by_diagram[diagram_id].append(change)

    # Create nodes for each diagram
    for diagram_id, changes in by_diagram.items():
        if diagram_id is None:
            label = gettext("Model Elements ({count})").format(count=len(changes))
        else:
            # Try to get diagram name
            diagram = None
            if compare_factory:
                diagram = compare_factory.lookup(diagram_id)
            if not diagram and base_factory:
                diagram = base_factory.lookup(diagram_id)
            diagram_name = getattr(diagram, "name", None) or diagram_id[:8]
            label = gettext("Diagram: {name} ({count})").format(
                name=diagram_name, count=len(changes)
            )

        # Group by change type within diagram
        children: list[CompareNode] = []
        added = [c for c in changes if c.change_type == ChangeType.ADDED]
        removed = [c for c in changes if c.change_type == ChangeType.REMOVED]
        modified = [c for c in changes if c.change_type == ChangeType.MODIFIED]

        if added:
            children.append(
                CompareNode(
                    added,
                    [],
                    gettext("Added ({count})").format(count=len(added)),
                    "change-type-added",
                )
            )
        if removed:
            children.append(
                CompareNode(
                    removed,
                    [],
                    gettext("Removed ({count})").format(count=len(removed)),
                    "change-type-removed",
                )
            )
        if modified:
            children.append(
                CompareNode(
                    modified,
                    [],
                    gettext("Modified ({count})").format(count=len(modified)),
                    "change-type-modified",
                )
            )

        root_nodes.append(CompareNode([], children, label, "diagram"))

    return _as_list_store(root_nodes)
