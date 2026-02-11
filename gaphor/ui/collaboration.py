"""Collaboration UI components."""

import logging

from gi.repository import Adw, Gio, GLib, Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.core import event_handler, gettext
from gaphor.i18n import translated_ui_string
from gaphor.services.collaboration.events import (
    CollaborationConnected,
    CollaborationDisconnected,
    UserCursorMoved,
    UserJoined,
    UserLeft,
)

log = logging.getLogger(__name__)


class CollaborationUI(Service, ActionProvider):
    """UI service for collaboration features."""

    def __init__(self, event_manager, collaboration_service, main_window):
        self.event_manager = event_manager
        self.collaboration = collaboration_service
        self.main_window = main_window

        self._users_popover: Gtk.Popover | None = None
        self._users_list: Gtk.ListBox | None = None
        self._status_button: Gtk.Button | None = None
        self._connect_dialog: Adw.MessageDialog | None = None

        event_manager.subscribe(self._on_user_joined)
        event_manager.subscribe(self._on_user_left)
        event_manager.subscribe(self._on_connected)
        event_manager.subscribe(self._on_disconnected)

    def shutdown(self) -> None:
        self.event_manager.unsubscribe(self._on_user_joined)
        self.event_manager.unsubscribe(self._on_user_left)
        self.event_manager.unsubscribe(self._on_connected)
        self.event_manager.unsubscribe(self._on_disconnected)

    def create_header_button(self) -> Gtk.Widget:
        button = Gtk.MenuButton()
        button.set_icon_name("system-users-symbolic")
        button.set_tooltip_text(gettext("Collaboration"))

        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        # Status label
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_icon = Gtk.Image.new_from_icon_name("network-offline-symbolic")
        status_label = Gtk.Label(label=gettext("Not connected"))
        status_box.append(status_icon)
        status_box.append(status_label)
        box.append(status_box)

        box.append(Gtk.Separator())

        # Users list
        users_label = Gtk.Label(label=gettext("Connected users:"))
        users_label.set_xalign(0)
        box.append(users_label)

        users_list = Gtk.ListBox()
        users_list.set_selection_mode(Gtk.SelectionMode.NONE)
        users_list.add_css_class("boxed-list")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(100)
        scrolled.set_max_content_height(200)
        scrolled.set_child(users_list)
        box.append(scrolled)

        self._users_list = users_list

        box.append(Gtk.Separator())

        # Connect/Disconnect button
        connect_btn = Gtk.Button(label=gettext("Connect..."))
        connect_btn.connect("clicked", self._on_connect_clicked)
        box.append(connect_btn)

        self._status_button = connect_btn

        popover.set_child(box)
        button.set_popover(popover)

        self._users_popover = popover

        return button

    def _on_connect_clicked(self, button: Gtk.Button) -> None:
        if self.collaboration.connected:
            import asyncio
            asyncio.create_task(self.collaboration.disconnect())
        else:
            self._show_connect_dialog()

    def _show_connect_dialog(self) -> None:
        window = self.main_window.window
        if not window:
            return

        dialog = Adw.MessageDialog.new(window)
        dialog.set_heading(gettext("Connect to Collaboration Server"))
        dialog.set_body(gettext("Enter the server URL and session details."))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Server URL
        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("ws://localhost:8765")
        url_entry.set_text("ws://localhost:8765")
        url_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        url_label = Gtk.Label(label=gettext("Server URL"))
        url_label.set_xalign(0)
        url_box.append(url_label)
        url_box.append(url_entry)
        box.append(url_box)

        # Session ID
        session_entry = Gtk.Entry()
        session_entry.set_placeholder_text("my-session")
        session_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        session_label = Gtk.Label(label=gettext("Session ID"))
        session_label.set_xalign(0)
        session_box.append(session_label)
        session_box.append(session_entry)
        box.append(session_box)

        # Username
        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("Your name")
        name_entry.set_text(self.collaboration.username)
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        name_label = Gtk.Label(label=gettext("Your name"))
        name_label.set_xalign(0)
        name_box.append(name_label)
        name_box.append(name_entry)
        box.append(name_box)

        dialog.set_extra_child(box)
        dialog.add_response("cancel", gettext("Cancel"))
        dialog.add_response("connect", gettext("Connect"))
        dialog.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)

        def on_response(dialog, response):
            if response == "connect":
                url = url_entry.get_text()
                session_id = session_entry.get_text()
                username = name_entry.get_text()
                if url and session_id:
                    import asyncio
                    asyncio.create_task(
                        self.collaboration.connect(url, session_id, username)
                    )
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    def _add_user_row(self, user_id: str, username: str, color: str) -> None:
        if not self._users_list:
            return

        row = Adw.ActionRow()
        row.set_title(username)
        row.set_name(user_id)

        # Color indicator
        color_box = Gtk.Box()
        color_box.set_size_request(16, 16)
        color_box.add_css_class("collab-user-color")
        css = Gtk.CssProvider()
        css.load_from_string(f".collab-user-color {{ background-color: {color}; border-radius: 8px; }}")
        Gtk.StyleContext.add_provider_for_display(
            color_box.get_display(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        row.add_prefix(color_box)

        self._users_list.append(row)

    def _remove_user_row(self, user_id: str) -> None:
        if not self._users_list:
            return

        row = self._users_list.get_first_child()
        while row:
            next_row = row.get_next_sibling()
            if hasattr(row, "get_name") and row.get_name() == user_id:
                self._users_list.remove(row)
                break
            row = next_row

    @event_handler(UserJoined)
    def _on_user_joined(self, event: UserJoined) -> None:
        GLib.idle_add(self._add_user_row, event.user_id, event.username, event.color)

    @event_handler(UserLeft)
    def _on_user_left(self, event: UserLeft) -> None:
        GLib.idle_add(self._remove_user_row, event.user_id)

    @event_handler(CollaborationConnected)
    def _on_connected(self, event: CollaborationConnected) -> None:
        if self._status_button:
            GLib.idle_add(self._status_button.set_label, gettext("Disconnect"))

    @event_handler(CollaborationDisconnected)
    def _on_disconnected(self, event: CollaborationDisconnected) -> None:
        if self._status_button:
            GLib.idle_add(self._status_button.set_label, gettext("Connect..."))
        if self._users_list:
            def clear_users():
                while row := self._users_list.get_first_child():
                    self._users_list.remove(row)
            GLib.idle_add(clear_users)
