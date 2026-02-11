"""Diagram collaboration integration."""

import logging

from gi.repository import GLib, Gtk

from gaphor.core import event_handler
from gaphor.services.collaboration.cursors import RemoteCursorPainter
from gaphor.services.collaboration.events import UserCursorMoved

log = logging.getLogger(__name__)


class DiagramCollaborationMixin:
    """Mixin for DiagramPage to add collaboration features."""

    def setup_collaboration(self, collaboration_service):
        self._collaboration = collaboration_service
        self._cursor_painter = None
        self._motion_controller = None

        if self.view and self.diagram:
            self._setup_cursor_tracking()

    def _setup_cursor_tracking(self):
        if not self._collaboration or not self.view:
            return

        # Add cursor painter to view
        self._cursor_painter = RemoteCursorPainter(
            self._collaboration.cursor_manager,
            self.diagram.id,
        )

        # Track local cursor movement
        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_cursor_motion)
        self.view.add_controller(motion)
        self._motion_controller = motion

        # Listen for remote cursor updates
        self._collaboration.event_manager.subscribe(self._on_remote_cursor)

    def _on_cursor_motion(self, controller, x, y):
        if not self._collaboration or not self._collaboration.enabled:
            return

        # Convert to diagram coordinates
        view = controller.get_widget()
        m = view.matrix
        ix, iy = m.inverse().transform_point(x, y)

        self._collaboration.send_cursor_position(self.diagram.id, ix, iy)

    @event_handler(UserCursorMoved)
    def _on_remote_cursor(self, event: UserCursorMoved):
        if event.diagram_id != self.diagram.id:
            return

        # Request redraw to show updated cursor
        if self.view:
            GLib.idle_add(self.view.queue_draw)

    def teardown_collaboration(self):
        if self._collaboration:
            self._collaboration.event_manager.unsubscribe(self._on_remote_cursor)
        if self._motion_controller and self.view:
            self.view.remove_controller(self._motion_controller)
        self._cursor_painter = None
        self._motion_controller = None
