"""Error handling utilities for presentation mode."""

from __future__ import annotations

import logging
import traceback
from functools import wraps
from typing import TYPE_CHECKING, Callable, TypeVar

from gi.repository import Adw, Gtk

from gaphor.i18n import gettext

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

T = TypeVar("T")


class PresentationError(Exception):
    """Base exception for presentation mode errors."""

    def __init__(self, message: str, details: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class SlideLoadError(PresentationError):
    """Error loading a slide."""

    pass


class DiagramNotFoundError(PresentationError):
    """Diagram referenced by slide not found."""

    pass


class PresentationSaveError(PresentationError):
    """Error saving presentation."""

    pass


class PresentationLoadError(PresentationError):
    """Error loading presentation."""

    pass


class AnimationError(PresentationError):
    """Error during animation."""

    pass


def show_error_dialog(
    parent: Gtk.Window | None,
    title: str,
    message: str,
    details: str | None = None,
) -> None:
    """Show an error dialog to the user."""
    dialog = Adw.AlertDialog.new(title, message)

    if details:
        dialog.set_body(f"{message}\n\n{gettext('Details')}: {details}")

    dialog.add_response("ok", gettext("OK"))
    dialog.set_default_response("ok")

    if parent:
        dialog.present(parent)
    else:
        log.error(f"{title}: {message}")
        if details:
            log.error(f"Details: {details}")


def show_warning_dialog(
    parent: Gtk.Window | None,
    title: str,
    message: str,
) -> None:
    """Show a warning dialog to the user."""
    dialog = Adw.AlertDialog.new(title, message)
    dialog.add_response("ok", gettext("OK"))
    dialog.set_default_response("ok")

    if parent:
        dialog.present(parent)
    else:
        log.warning(f"{title}: {message}")


async def show_confirmation_dialog(
    parent: Gtk.Window | None,
    title: str,
    message: str,
    confirm_label: str = None,
    cancel_label: str = None,
) -> bool:
    """Show a confirmation dialog and return True if confirmed."""
    dialog = Adw.AlertDialog.new(title, message)

    dialog.add_response("cancel", cancel_label or gettext("Cancel"))
    dialog.add_response("confirm", confirm_label or gettext("Confirm"))
    dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    result = {"confirmed": False}

    def on_response(dialog, response):
        result["confirmed"] = response == "confirm"

    dialog.connect("response", on_response)

    if parent:
        dialog.present(parent)

    return result["confirmed"]


def handle_errors(
    error_title: str = None,
    parent_getter: Callable[[], Gtk.Window | None] | None = None,
    reraise: bool = False,
):
    """Decorator to handle errors gracefully with user feedback.

    Args:
        error_title: Title for the error dialog
        parent_getter: Callable that returns the parent window
        reraise: Whether to reraise the exception after showing dialog
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T | None]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T | None:
            try:
                return func(*args, **kwargs)
            except PresentationError as e:
                log.error(f"{error_title or 'Error'}: {e.message}", exc_info=True)
                parent = parent_getter() if parent_getter else None
                show_error_dialog(
                    parent,
                    error_title or gettext("Presentation Error"),
                    e.message,
                    e.details,
                )
                if reraise:
                    raise
                return None
            except Exception as e:
                log.error(f"Unexpected error: {e}", exc_info=True)
                parent = parent_getter() if parent_getter else None
                show_error_dialog(
                    parent,
                    error_title or gettext("Unexpected Error"),
                    str(e),
                    traceback.format_exc(),
                )
                if reraise:
                    raise
                return None

        return wrapper

    return decorator


def handle_errors_async(
    error_title: str = None,
    parent_getter: Callable[[], Gtk.Window | None] | None = None,
    reraise: bool = False,
):
    """Decorator to handle errors in async functions."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except PresentationError as e:
                log.error(f"{error_title or 'Error'}: {e.message}", exc_info=True)
                parent = parent_getter() if parent_getter else None
                show_error_dialog(
                    parent,
                    error_title or gettext("Presentation Error"),
                    e.message,
                    e.details,
                )
                if reraise:
                    raise
                return None
            except Exception as e:
                log.error(f"Unexpected error: {e}", exc_info=True)
                parent = parent_getter() if parent_getter else None
                show_error_dialog(
                    parent,
                    error_title or gettext("Unexpected Error"),
                    str(e),
                    traceback.format_exc(),
                )
                if reraise:
                    raise
                return None

        return wrapper

    return decorator


def safe_call(func: Callable[..., T], *args, default: T = None, **kwargs) -> T:
    """Call a function safely, returning default on error."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        log.warning(f"Safe call failed: {e}")
        return default
