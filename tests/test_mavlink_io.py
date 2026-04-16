"""Tests for arducharts.mavlink_io — MAVLink guards and connection logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from arducharts.mavlink_io import HAS_MAVLINK, MAVLinkConnection, require_mavlink


class TestRequireMavlink:
    def test_has_mavlink_is_bool(self):
        assert isinstance(HAS_MAVLINK, bool)

    def test_does_not_raise_when_available(self):
        if HAS_MAVLINK:
            require_mavlink()  # should not raise

    def test_raises_when_unavailable(self, monkeypatch):
        import arducharts.mavlink_io as mod
        monkeypatch.setattr(mod, "HAS_MAVLINK", False)
        with pytest.raises(ImportError, match="pymavlink required"):
            require_mavlink()


class TestMAVLinkConnectionInit:
    @pytest.mark.skipif(not HAS_MAVLINK, reason="pymavlink not installed")
    def test_init_calls_mavutil(self, monkeypatch):  # pylint: disable=unused-argument
        mock_conn = MagicMock()
        mock_conn.target_system = 1
        mock_conn.target_component = 1
        mock_conn.wait_heartbeat = MagicMock()

        with patch("arducharts.mavlink_io.mavutil") as mock_mavutil:
            mock_mavutil.mavlink_connection.return_value = mock_conn
            _mav = MAVLinkConnection.__new__(MAVLinkConnection)
            # Manually call __init__ with mocked mavutil
            with patch.object(MAVLinkConnection, "__init__", lambda self, *a, **kw: None):
                pass
            # Directly test the constructor logic via a real call
            mock_mavutil.mavlink_connection.return_value = mock_conn
            _mav = MAVLinkConnection("tcp:127.0.0.1:5760", baud=115200)
            mock_mavutil.mavlink_connection.assert_called_once()
            mock_conn.wait_heartbeat.assert_called_once()

    @pytest.mark.skipif(not HAS_MAVLINK, reason="pymavlink not installed")
    def test_context_manager(self, monkeypatch):  # pylint: disable=unused-argument
        mock_conn = MagicMock()
        mock_conn.target_system = 1
        mock_conn.target_component = 1

        with patch("arducharts.mavlink_io.mavutil") as mock_mavutil:
            mock_mavutil.mavlink_connection.return_value = mock_conn
            with MAVLinkConnection("tcp:127.0.0.1:5760") as _mav:
                pass
            mock_conn.close.assert_called_once()


class TestFlashParamsDryRun:
    @pytest.mark.skipif(not HAS_MAVLINK, reason="pymavlink not installed")
    def test_dry_run_no_failures(self):
        mock_conn = MagicMock()
        mock_conn.target_system = 1
        mock_conn.target_component = 1

        with patch("arducharts.mavlink_io.mavutil") as mock_mavutil:
            mock_mavutil.mavlink_connection.return_value = mock_conn
            with MAVLinkConnection("tcp:127.0.0.1:5760") as mav:
                failed = mav.flash_params({"A": 1, "B": 2}, dry_run=True)
                assert not failed
