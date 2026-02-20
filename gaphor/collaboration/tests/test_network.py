"""Tests for network transports."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from collaboration.network import LocalTransport


class TestLocalTransport:
    def setup_method(self):
        LocalTransport.clear_all()

    def teardown_method(self):
        LocalTransport.clear_all()

    def test_connect_disconnect(self):
        transport = LocalTransport("channel-1", "user-1")

        connected = False
        disconnected = False

        def on_connect():
            nonlocal connected
            connected = True

        def on_disconnect(reason):
            nonlocal disconnected
            disconnected = True

        transport.on_connect = on_connect
        transport.on_disconnect = on_disconnect

        transport.connect()
        assert connected
        assert transport.is_connected

        transport.disconnect()
        assert disconnected
        assert not transport.is_connected

    def test_send_receive_between_transports(self):
        transport1 = LocalTransport("channel-1", "user-1")
        transport2 = LocalTransport("channel-1", "user-2")

        received_messages = []

        def on_message(msg):
            received_messages.append(msg)

        transport2.on_message = on_message

        transport1.connect()
        transport2.connect()

        transport1.send({"type": "test", "data": "hello"})

        assert len(received_messages) == 1
        assert received_messages[0]["data"] == "hello"

    def test_message_not_sent_to_self(self):
        transport = LocalTransport("channel-1", "user-1")

        received_messages = []
        transport.on_message = lambda msg: received_messages.append(msg)

        transport.connect()
        transport.send({"type": "test"})

        assert len(received_messages) == 0

    def test_different_channels_isolated(self):
        transport1 = LocalTransport("channel-1", "user-1")
        transport2 = LocalTransport("channel-2", "user-2")

        received = []
        transport2.on_message = lambda msg: received.append(msg)

        transport1.connect()
        transport2.connect()
        transport1.send({"data": "test"})

        assert len(received) == 0

    def test_send_when_disconnected(self):
        transport1 = LocalTransport("channel-1", "user-1")
        transport2 = LocalTransport("channel-1", "user-2")

        received = []
        transport2.on_message = lambda msg: received.append(msg)

        transport2.connect()
        # transport1 not connected
        transport1.send({"data": "test"})

        assert len(received) == 0
