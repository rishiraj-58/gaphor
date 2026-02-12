"""Test configuration for template browser tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock GTK-related modules for testing
sys.modules['gi'] = MagicMock()
sys.modules['gi.repository'] = MagicMock()
sys.modules['gi.repository.Gtk'] = MagicMock()
sys.modules['gi.repository.Gdk'] = MagicMock()
sys.modules['gi.repository.GLib'] = MagicMock()
sys.modules['gi.repository.Gio'] = MagicMock()
sys.modules['gi.repository.GObject'] = MagicMock()
sys.modules['gi.repository.GdkPixbuf'] = MagicMock()
sys.modules['gi.repository.Adw'] = MagicMock()

import pytest


@pytest.fixture
def tmp_storage_path(tmp_path):
    """Temporary storage path for template tests."""
    return tmp_path / "templates"
