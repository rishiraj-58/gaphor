"""Pytest configuration for template tests."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture(scope="function")
def temp_dir():
    """Create a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
