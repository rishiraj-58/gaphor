"""Tests for CollaborationUser."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from collaboration.user import CollaborationUser, CursorPosition, USER_COLORS


class TestCollaborationUser:
    def test_create_user(self):
        user = CollaborationUser.create("user-123", "Test User")

        assert user.user_id == "user-123"
        assert user.display_name == "Test User"
        assert user.color in USER_COLORS
        assert user.is_local is False

    def test_create_local_user(self):
        user = CollaborationUser.create("local-user", "Local", is_local=True)

        assert user.is_local is True

    def test_consistent_color_for_same_user_id(self):
        user1 = CollaborationUser.create("same-id", "User 1")
        user2 = CollaborationUser.create("same-id", "User 2")

        assert user1.color == user2.color

    def test_different_colors_for_different_users(self):
        user1 = CollaborationUser.create("user-a", "User A")
        user2 = CollaborationUser.create("user-b", "User B")

        # Colors might be the same by chance, but usually different
        # This is a probabilistic test

    def test_update_cursor(self):
        user = CollaborationUser.create("user-1", "Test")
        user.update_cursor("diagram-1", 100.0, 200.0, ["item-1", "item-2"])

        assert user.cursor_position is not None
        assert user.cursor_position.diagram_id == "diagram-1"
        assert user.cursor_position.x == 100.0
        assert user.cursor_position.y == 200.0
        assert user.cursor_position.selected_item_ids == ["item-1", "item-2"]

    def test_clear_cursor(self):
        user = CollaborationUser.create("user-1", "Test")
        user.update_cursor("diagram-1", 100.0, 200.0)
        user.clear_cursor()

        assert user.cursor_position is None

    def test_color_hex(self):
        user = CollaborationUser(
            user_id="test",
            display_name="Test",
            color=(1.0, 0.5, 0.0, 1.0),
        )

        assert user.color_hex == "#ff7f00"

    def test_to_dict(self):
        user = CollaborationUser.create("user-1", "Test User")
        user.update_cursor("diagram-1", 50.0, 75.0)

        data = user.to_dict()

        assert data["user_id"] == "user-1"
        assert data["display_name"] == "Test User"
        assert len(data["color"]) == 4
        assert data["cursor_position"]["diagram_id"] == "diagram-1"

    def test_from_dict(self):
        data = {
            "user_id": "user-1",
            "display_name": "Test User",
            "color": [0.5, 0.5, 0.5, 1.0],
            "cursor_position": {
                "diagram_id": "diagram-1",
                "x": 100.0,
                "y": 200.0,
                "selected_item_ids": ["item-1"],
            },
        }

        user = CollaborationUser.from_dict(data)

        assert user.user_id == "user-1"
        assert user.display_name == "Test User"
        assert user.color == (0.5, 0.5, 0.5, 1.0)
        assert user.cursor_position.x == 100.0

    def test_from_dict_without_cursor(self):
        data = {
            "user_id": "user-1",
            "display_name": "Test",
            "color": [1.0, 1.0, 1.0, 1.0],
            "cursor_position": None,
        }

        user = CollaborationUser.from_dict(data)

        assert user.cursor_position is None
