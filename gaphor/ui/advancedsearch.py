"""Advanced search dialog for Gaphor.

Opened with <Primary><Shift>f.  Searches across element names, element
types, attribute / operation names and values, and relationship types
and endpoints – optionally scoped to only the currently-open diagram.

Architecture notes
------------------
* ``SearchIndex`` owns the pure-Python search logic.  It has no GTK
  dependency and is therefore fully unit-testable without a display.
* ``AdvancedSearchDialog`` is the GTK shell.  It creates one
  ``SearchIndex``, wires the entry / toggle / list-view together, and
  handles the "navigate + highlight" action when the user activates a
  result row.
* Navigation reuses ``DiagramOpened`` (the same event that opening a
  tab fires) so the tab machinery in ``Diagrams`` is exercised exactly
  once.  The temporary highlight is a pure CSS-class add / delayed
  remove, injected through the *same* ``Gtk.CssProvider`` path that
  ``DiagramPage.update_drawing_style`` already uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unicodedata import normalize

from gi.repository import GLib, Gtk

from gaphor.core.modeling import Base, Diagram
from gaphor.diagram.event import DiagramOpened
from gaphor.diagram.iconname import icon_name

if TYPE_CHECKING:
    from gaphor.core.eventmanager import EventManager
    from gaphor.core.modeling.elementfactory import ElementFactory

# ---------------------------------------------------------------------------
# How long (ms) the highlight CSS class stays on the presentation item
# ---------------------------------------------------------------------------
_HIGHLIGHT_DURATION_MS = 600


# ---------------------------------------------------------------------------
# Data classes – no GTK, fully testable
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """One hit returned by the indexer.

    Attributes
    ----------
    element : Base
        The model element that matched.
    element_name : str
        Formatted display name (may be empty for anonymous elements).
    element_type : str
        Human-readable type label, e.g. ``"Class"`` or ``"Generalization"``.
    diagrams : list[Diagram]
        Every diagram that contains a presentation of *element*.
    match_context : str
        A short human-readable snippet that explains *why* this element
        matched (e.g. ``"attribute: speed: int"``).  Used as the third
        line in the result row.
    """

    element: Base
    element_name: str
    element_type: str
    diagrams: list[Diagram] = field(default_factory=list)
    match_context: str = ""


# ---------------------------------------------------------------------------
# Pure-Python indexer / searcher
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """NFC-normalise and case-fold, identical to the existing
    ``treesearch.search`` convention."""
    return normalize("NFC", text).casefold()


def _safe_name(element: Base) -> str:
    """Return element.name if available, else empty string."""
    return getattr(element, "name", None) or ""


def _diagrams_for(element: Base) -> list[Diagram]:
    """Collect every Diagram in which *element* has a presentation."""
    seen: dict[str, Diagram] = {}
    for pres in getattr(element, "presentation", ()):
        if (diag := getattr(pres, "diagram", None)) and diag.id not in seen:
            seen[diag.id] = diag
    return list(seen.values())


def _type_label(element: Base) -> str:
    """Human-readable class name with CamelCase words split by spaces.

    ``AssociationItem``  →  skipped (it is a Presentation, not a model element)
    ``Generalization``   →  ``"Generalization"``
    ``InterfaceRealization`` → ``"InterfaceRealization"``

    We intentionally keep the original class name intact (no word
    splitting) because the existing ``format_relationship`` in
    ``umlfmt.py`` returns the raw class name and users are accustomed
    to it.
    """
    return type(element).__name__


def _collect_attribute_tokens(element: Base) -> list[str]:
    """Yield searchable text fragments from owned attributes and operations.

    Works for any element that exposes ``ownedAttribute`` and / or
    ``ownedOperation`` (i.e. UML Classifiers, which include Class,
    Interface, DataType …).  The function is deliberately duck-typed so
    that SysML Block etc. also work without special-casing.
    """
    tokens: list[str] = []

    # --- owned attributes (Property) -------------------------------------
    for attr in getattr(element, "ownedAttribute", ()):
        if attr_name := _safe_name(attr):
            tokens.append(attr_name)
        # type name
        if (t := getattr(attr, "type", None)) and (t_name := _safe_name(t)):
            tokens.append(t_name)
        # default value (uses the same helper as umlfmt)
        if dv := getattr(attr, "defaultValue", None):
            try:
                from gaphor.UML.recipes import get_literal_value_as_string

                if val_str := get_literal_value_as_string(dv):
                    tokens.append(val_str)
            except ImportError:  # pragma: no cover – UML not loaded
                pass

    # --- owned operations (Operation) ------------------------------------
    for op in getattr(element, "ownedOperation", ()):
        if op_name := _safe_name(op):
            tokens.append(op_name)
        # parameters
        for param in getattr(op, "ownedParameter", ()):
            if p_name := _safe_name(param):
                tokens.append(p_name)
            if (pt := getattr(param, "type", None)) and (pt_name := _safe_name(pt)):
                tokens.append(pt_name)

    return tokens


# Relationship endpoint accessors: maps a relationship class name to the
# pairs of attribute names that name the two ends.  We use *class name*
# rather than the class itself so we never need to import gaphor.UML at
# module level – the dict is consulted only at search time and only when
# the element actually *is* a Relationship.
_RELATIONSHIP_ENDPOINTS: dict[str, tuple[str, str]] = {
    "Generalization": ("specific", "general"),
    "Dependency": ("client", "supplier"),
    "Usage": ("client", "supplier"),
    "Realization": ("client", "supplier"),
    "InterfaceRealization": ("client", "supplier"),
    "Include": ("includingCase", "addition"),
    "Extend": ("extension", "extendedCase"),
    "PackageImport": ("importingNamespace", "importedPackage"),
    "PackageMerge": ("mergingPackage", "mergedPackage"),
    "ElementImport": ("importingNamespace", "importedElement"),
    "InformationFlow": ("informationSource", "informationTarget"),
}


def _collect_relationship_tokens(element: Base) -> list[str]:
    """For Relationship elements return the type label plus endpoint
    names so that searching for e.g. ``"MyClass"`` also surfaces every
    relationship that *refers to* ``MyClass``."""
    tokens: list[str] = [_type_label(element)]  # the relationship type itself

    cls_name = type(element).__name__
    if cls_name in _RELATIONSHIP_ENDPOINTS:
        for attr_name in _RELATIONSHIP_ENDPOINTS[cls_name]:
            endpoint = getattr(element, attr_name, None)
            # endpoint may be a single element or a collection
            if endpoint is None:
                continue
            if isinstance(endpoint, Base):
                if ep_name := _safe_name(endpoint):
                    tokens.append(ep_name)
            else:
                # collection (relation_many)
                try:
                    for item in endpoint:
                        if item_name := _safe_name(item):
                            tokens.append(item_name)
                except TypeError:
                    pass
    else:
        # Generic fallback for relationship types not in the explicit
        # map: still capture the type label, already added above.
        pass

    # Association: memberEnd names
    if hasattr(element, "memberEnd"):
        for end in getattr(element, "memberEnd", ()):
            if end_name := _safe_name(end):
                tokens.append(end_name)
            if (end_type := getattr(end, "type", None)) and (
                et_name := _safe_name(end_type)
            ):
                tokens.append(et_name)

    return tokens


def _is_relationship(element: Base) -> bool:
    """Duck-type check: does this element sit in the Relationship
    branch of the UML metamodel?  We avoid importing UML.Relationship
    directly so the module stays decoupled from the modelling language."""
    # Walk the MRO looking for a class literally named "Relationship".
    return any(c.__name__ == "Relationship" for c in type(element).__mro__)


class SearchIndex:
    """Stateless searcher over an ElementFactory.

    Instantiate once; call :py:meth:`search` as many times as you like.
    The factory is queried *fresh* on every search call so that newly
    created or deleted elements are always visible – no background
    listener / cache invalidation required.

    Parameters
    ----------
    element_factory : ElementFactory
        The single source of truth for all model elements.
    current_diagram : Diagram | None
        When *scope_global* is ``False`` only presentations that live on
        this diagram are returned.  May be ``None`` (returns nothing in
        local mode).
    """

    def __init__(
        self,
        element_factory: ElementFactory,
        current_diagram: Diagram | None = None,
    ) -> None:
        self.element_factory = element_factory
        self.current_diagram = current_diagram

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def search(
        self, query: str, *, scope_global: bool = True
    ) -> list[SearchResult]:
        """Run a search and return all matching results.

        Parameters
        ----------
        query : str
            The user's search text.  Substring, case-insensitive.
        scope_global : bool
            ``True``  → search every element in the model.
            ``False`` → only elements that have at least one presentation
            on ``self.current_diagram``.

        Returns
        -------
        list[SearchResult]
            Ordered: exact name-prefix matches first, then everything
            else, both groups alphabetically by element name.
        """
        if not query or not query.strip():
            return []

        normalised_query = _normalise(query.strip())
        results: list[SearchResult] = []
        seen_ids: set[str] = set()

        for element in self.element_factory.select():
            # Presentations (canvas items) are not model elements; skip.
            if _is_presentation(element):
                continue
            # Diagrams themselves are navigational containers; skip.
            if isinstance(element, Diagram):
                continue

            if element.id in seen_ids:
                continue

            diagrams = _diagrams_for(element)

            # Scope filter: in local mode drop elements that have no
            # presentation on the current diagram.
            if not scope_global:
                if self.current_diagram is None:
                    continue
                if self.current_diagram not in diagrams:
                    continue

            # --- gather all searchable text for this element -----------
            match_context = self._match(element, normalised_query, diagrams)
            if match_context is None:
                continue

            seen_ids.add(element.id)
            results.append(
                SearchResult(
                    element=element,
                    element_name=_safe_name(element),
                    element_type=_type_label(element),
                    diagrams=diagrams,
                    match_context=match_context,
                )
            )

        # Sort: name-prefix matches first, then rest; within each group
        # sort alphabetically by lower-cased name.
        def _sort_key(r: SearchResult) -> tuple[int, str]:
            name_lower = _normalise(r.element_name)
            prefix = 0 if name_lower.startswith(normalised_query) else 1
            return (prefix, name_lower)

        results.sort(key=_sort_key)
        return results

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _match(
        self,
        element: Base,
        normalised_query: str,
        diagrams: list[Diagram],
    ) -> str | None:
        """Return a short context string if *element* matches, else ``None``.

        The context string is what appears as the third line in the
        result row – it tells the user *which* field matched.
        """
        name = _safe_name(element)

        # 1. Element name
        if name and normalised_query in _normalise(name):
            return f"name: {name}"

        # 2. Element type label
        type_label = _type_label(element)
        if normalised_query in _normalise(type_label):
            return f"type: {type_label}"

        # 3. Relationship endpoints + type  (before generic attributes so
        #    that relationship-specific snippets surface first)
        if _is_relationship(element):
            for token in _collect_relationship_tokens(element):
                if normalised_query in _normalise(token):
                    return f"relationship: {token}"

        # 4. Owned attributes / operations / parameters
        for token in _collect_attribute_tokens(element):
            if normalised_query in _normalise(token):
                return f"attribute: {token}"

        # 5. Diagram names – lets users find "which elements live on
        #    diagram X" by typing the diagram name.
        for diag in diagrams:
            if diag.name and normalised_query in _normalise(diag.name):
                return f"in diagram: {diag.name}"

        return None


def _is_presentation(element: Base) -> bool:
    """True when *element* is a Presentation (canvas item).

    Avoids importing Presentation directly; uses MRO name check."""
    return any(c.__name__ == "Presentation" for c in type(element).__mro__)


# ---------------------------------------------------------------------------
# GTK dialog
# ---------------------------------------------------------------------------

# Unique CSS class name injected onto a presentation item for the brief
# highlight pulse.  Defined here so both the dialog and the CSS rule in
# styling.css agree on the name.
HIGHLIGHT_CSS_CLASS = "search-highlight"


class AdvancedSearchDialog:
    """Modal dialog that wraps SearchIndex in a GTK ListView.

    Lifecycle
    ---------
    * ``show()``   – builds the widget tree (once), presents the dialog.
    * ``close()``  – hides the dialog; does *not* destroy it so that
      subsequent ``show()`` calls are cheap.

    The dialog is owned by ``ModelBrowser`` and lives for the duration
    of the application session.
    """

    def __init__(self, event_manager: EventManager, element_factory: ElementFactory):
        self.event_manager = event_manager
        self.element_factory = element_factory

        # The dialog widget (built lazily in show())
        self._dialog: Gtk.Dialog | None = None

        # Sub-widgets – set in _build()
        self._search_entry: Gtk.SearchEntry | None = None
        self._scope_toggle: Gtk.SwitchRow | None = None
        self._list_box: Gtk.ListBox | None = None

        # Current results (parallel to list-box rows)
        self._results: list[SearchResult] = []

        # Reference to the diagram that was active when the dialog opened.
        # Captured in show(); used for local-scope filtering and for
        # determining which diagram to open on activation.
        self._current_diagram: Diagram | None = None

        # CssProvider that we attach / detach for the highlight pulse.
        # Created once; reused across activations.
        self._highlight_css_provider: Gtk.CssProvider | None = None

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def show(self, current_diagram: Diagram | None = None) -> None:
        """Present the dialog.  *current_diagram* is the diagram tab
        that is open right now (used for local scope and as the default
        navigation target)."""
        self._current_diagram = current_diagram

        if self._dialog is None:
            self._build()

        assert self._dialog is not None
        assert self._search_entry is not None

        # Clear previous state so the user starts fresh
        self._search_entry.set_text("")
        self._results.clear()
        if self._list_box is not None:
            self._list_box.remove_all()

        self._dialog.present()
        self._search_entry.grab_focus()

    def close(self) -> None:
        """Hide the dialog (do not destroy – reuse on next open)."""
        if self._dialog:
            self._dialog.hide()

    # ------------------------------------------------------------------
    # widget construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._dialog = Gtk.Dialog.new()
        self._dialog.set_title("Advanced Search")
        self._dialog.set_default_size(520, 480)
        self._dialog.set_modal(True)
        # Closing the dialog just hides it; the user can reopen it.
        self._dialog.connect("close-request", self._on_close_request)

        content_area = self._dialog.get_content_area()
        content_area.set_spacing(0)

        # --- search entry ----------------------------------------------
        self._search_entry = Gtk.SearchEntry.new()
        self._search_entry.set_placeholder_text("Search elements…")
        self._search_entry.connect("search-changed", self._on_search_changed)
        # Enter / next-match triggers navigation to the first result
        self._search_entry.connect("activate", self._on_activate_first)
        self._search_entry.connect("next-match", self._on_activate_first)
        content_area.append(self._search_entry)

        # --- scope toggle row ------------------------------------------
        # Use a simple Gtk.Box with a label + Gtk.Switch because
        # Gtk.SwitchRow belongs to Adw.PreferencesPage which we do not
        # want to pull in just for one toggle.
        toggle_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
        toggle_box.set_margin_start(12)
        toggle_box.set_margin_end(12)
        toggle_box.set_margin_top(6)
        toggle_box.set_margin_bottom(6)

        toggle_label = Gtk.Label.new("Search current diagram only")
        toggle_label.set_halign(Gtk.Align.START)
        toggle_label.set_hexpand(True)
        toggle_box.append(toggle_label)

        self._scope_switch = Gtk.Switch.new()
        # Default OFF → global scope
        self._scope_switch.set_active(False)
        self._scope_switch.connect("notify::active", self._on_scope_changed)
        toggle_box.append(self._scope_switch)

        content_area.append(toggle_box)

        # --- separator -------------------------------------------------
        content_area.append(Gtk.Separator.new(Gtk.Orientation.HORIZONTAL))

        # --- scrollable result list ------------------------------------
        scrolled = Gtk.ScrolledWindow.new()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self._list_box = Gtk.ListBox.new()
        self._list_box.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self._list_box.connect("row-activated", self._on_row_activated)
        scrolled.set_child(self._list_box)
        content_area.append(scrolled)

        # --- status label (result count) --------------------------------
        self._status_label = Gtk.Label.new("")
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_margin_start(12)
        self._status_label.set_margin_bottom(4)
        self._status_label.add_css_class("dim-label")
        content_area.append(self._status_label)

    # ------------------------------------------------------------------
    # signal / event handlers
    # ------------------------------------------------------------------

    def _on_close_request(self, _dialog) -> bool:
        self.close()
        return True  # prevent destruction

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._run_search()

    def _on_scope_changed(self, _switch, _gparam) -> None:
        # Re-run with the new scope
        self._run_search()

    def _on_activate_first(self, _entry: Gtk.SearchEntry) -> None:
        """When the user presses Enter in the search box, activate the
        first visible result row (if any)."""
        if self._list_box is None:
            return
        row = self._list_box.get_row_at_index(0)
        if row is not None:
            self._activate_result(row)

    def _on_row_activated(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self._activate_result(row)

    # ------------------------------------------------------------------
    # search execution
    # ------------------------------------------------------------------

    def _run_search(self) -> None:
        assert self._search_entry is not None
        assert self._list_box is not None

        query = self._search_entry.get_text()
        scope_local = self._scope_switch.get_active()

        index = SearchIndex(self.element_factory, self._current_diagram)
        self._results = index.search(query, scope_global=not scope_local)

        # Rebuild the list-box rows
        self._list_box.remove_all()
        for result in self._results:
            row = _build_result_row(result)
            self._list_box.append(row)

        # Update status
        count = len(self._results)
        self._status_label.set_text(
            f"{count} result{'s' if count != 1 else ''}" if count else "No results"
        )

    # ------------------------------------------------------------------
    # navigation + highlight
    # ------------------------------------------------------------------

    def _activate_result(self, row: Gtk.ListBoxRow) -> None:
        """Navigate to the element described by *row* and pulse-
        highlight its presentation item."""
        index = row.get_index()
        if index < 0 or index >= len(self._results):
            return

        result = self._results[index]
        element = result.element

        if not result.diagrams:
            # Element has no presentation anywhere – nothing to navigate to.
            return

        # Pick the target diagram: prefer current_diagram if the element
        # is there, otherwise fall back to the first diagram in the list.
        target_diagram: Diagram
        if self._current_diagram and self._current_diagram in result.diagrams:
            target_diagram = self._current_diagram
        else:
            target_diagram = result.diagrams[0]

        # 1. Open / switch to the diagram tab.  DiagramOpened is the
        #    exact event that Diagrams._on_show_diagram listens on.
        self.event_manager.handle(DiagramOpened(target_diagram))

        # 2. Find the presentation item for *element* on target_diagram
        #    and focus + highlight it.  We schedule this on the GLib
        #    main loop so that the diagram page has had a chance to
        #    finish opening / painting before we manipulate its view.
        GLib.idle_add(
            self._highlight_element, element, target_diagram
        )

    def _highlight_element(self, element: Base, diagram: Diagram) -> bool:
        """Focus the presentation and schedule the CSS highlight pulse.

        Returns ``False`` so that GLib.idle_add does not repeat."""
        # Find the presentation on this diagram
        pres = next(
            (
                p
                for p in getattr(element, "presentation", ())
                if getattr(p, "diagram", None) is diagram
            ),
            None,
        )
        if pres is None:
            return False

        # We cannot reach the GtkView directly from here – but we *can*
        # apply a transient CSS class to the presentation and let the
        # existing DiagramPage CSS machinery pick it up on the next
        # repaint.  The class is added to the element's *subject*-level
        # CSS via a temporary provider on the default display.
        #
        # Implementation: add a Gtk.CssProvider with a rule that targets
        # the element's id, present it, then remove it after the pulse
        # duration.  Because Gaphor's item painter reads styles from the
        # StyleSheet (not from Gtk CSS), we take a different, simpler
        # approach: we emit a DiagramSelectionChanged-equivalent by
        # directly manipulating the selection on every registered view.
        #
        # The cleanest hook available without importing DiagramPage is
        # to use the diagram's registered views.  Gaphas views expose
        # selection; we set focused_item there and request_update on the
        # item so the focus rectangle appears.  For the colour pulse we
        # add / remove a CSS class on the GtkView widget.

        for view in getattr(diagram, "_registered_views", set()):
            # Gaphas GtkView exposes .selection
            selection = getattr(view, "selection", None)
            if selection is None:
                continue

            selection.focused_item = pres

            # Add the highlight CSS class to the *view widget* so that
            # the rule in styling.css can target it.  We add the class
            # to the item via a custom attribute that ItemPainter can
            # read, but since ItemPainter is style-sheet driven we
            # instead add it directly to the GtkView and use a child
            # combinator.  Simplest: add to the view, schedule removal.
            gtk_widget = view  # GtkView IS a Gtk.Widget
            gtk_widget.add_css_class(HIGHLIGHT_CSS_CLASS)
            GLib.timeout_add(
                _HIGHLIGHT_DURATION_MS,
                _remove_css_class,
                gtk_widget,
                HIGHLIGHT_CSS_CLASS,
            )

            # Request a repaint so the focus rectangle shows up
            diagram.request_update(pres)

            break  # one view is enough

        return False  # do not repeat


def _remove_css_class(widget: Gtk.Widget, css_class: str) -> bool:
    """GLib timeout callback – removes the CSS class and returns False
    so the timeout is not repeated."""
    widget.remove_css_class(css_class)
    return False


def _build_result_row(result: SearchResult) -> Gtk.ListBoxRow:
    """Construct a single result row with three lines of information.

    Layout
    ------
    ┌──────────────────────────────────────────────┐
    │  [icon]  ElementName                         │   ← bold
    │          Type  ·  Diagram1, Diagram2         │   ← normal
    │          match context snippet               │   ← italic, dimmed
    └──────────────────────────────────────────────┘
    """
    row = Gtk.ListBoxRow.new()
    row.set_margin_top(2)
    row.set_margin_bottom(2)

    hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 10)
    hbox.set_margin_start(8)
    hbox.set_margin_end(8)
    hbox.set_margin_top(4)
    hbox.set_margin_bottom(4)

    # --- icon ----------------------------------------------------------
    icon = Gtk.Image.new_from_icon_name(icon_name(result.element))
    icon.set_icon_size(Gtk.IconSize.LARGE)
    icon.set_valign(Gtk.Align.CENTER)
    hbox.append(icon)

    # --- text column (three lines stacked vertically) -----------------
    vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 2)
    vbox.set_hexpand(True)

    # Line 1: element name (bold)
    name_label = Gtk.Label.new(result.element_name or f"<{result.element_type}>")
    name_label.set_halign(Gtk.Align.START)
    name_label.set_ellipsize(1)  # PANGO_ELLIPSIZE_END = 1
    name_label.add_css_class("advanced-search-name")
    vbox.append(name_label)

    # Line 2: "Type  ·  Diagram1, Diagram2"
    diag_names = ", ".join(d.name or "<unnamed>" for d in result.diagrams)
    meta_text = result.element_type
    if diag_names:
        meta_text += f"  ·  {diag_names}"
    meta_label = Gtk.Label.new(meta_text)
    meta_label.set_halign(Gtk.Align.START)
    meta_label.set_ellipsize(1)
    meta_label.add_css_class("advanced-search-meta")
    vbox.append(meta_label)

    # Line 3: match context (italic, dimmed)
    if result.match_context:
        ctx_label = Gtk.Label.new(result.match_context)
        ctx_label.set_halign(Gtk.Align.START)
        ctx_label.set_ellipsize(1)
        ctx_label.add_css_class("advanced-search-context")
        vbox.append(ctx_label)

    hbox.append(vbox)
    row.set_child(hbox)
    return row
