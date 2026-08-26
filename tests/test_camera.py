"""Snapshot camera for video door entry (WHO=8).

Home Assistant and its aiohttp client are stubbed (see `ha_stubs`); the client
session `camera.py` reaches for is replaced with a fake that records the GET and
hands back a canned response, so the throttle, the session activation, the
request shape and — above all — the fact that the camera password never reaches
the log can be exercised without a panel or a network.

The password below is a distinctive placeholder, chosen so a leak into a log
line would be unmistakable to `assert` against.
"""

import asyncio
import logging
import os
import sys
import types

import pytest
from aiohttp import ClientResponseError, ClientTimeout, RequestInfo
from yarl import URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ha_stubs  # noqa: E402

const = ha_stubs.load("const")
camera = ha_stubs.load("camera")

MAC = "00:03:50:11:22:33"
HOST = "192.168.0.10"
#: Distinctive on purpose: a leak of this string into a log is trivial to catch.
PASSWORD = "s3cr3t-cam-pw"
JPEG = b"\xff\xd8\xff\xe0-a-jpeg-frame"


class FakeGateway:
    """Just enough of the handler for the camera: an async `send` that records."""

    mac = MAC
    unique_id = MAC
    log_id = "[test]"

    def __init__(self):
        self.gateway = types.SimpleNamespace(host=HOST)
        self.sent = []

    async def send(self, message):
        await asyncio.sleep(0)
        self.sent.append(str(message))


class FakeResponse:
    """An async context manager standing in for an aiohttp response."""

    def __init__(self, body=b"", error=None):
        self._body = body
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    async def read(self):
        return self._body


class FakeSession:
    """Records every GET and hands back one preset response."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._response


def _client_response_error() -> ClientResponseError:
    """A 401 whose string carries the request URL — password and all.

    This is what aiohttp raises on a non-2xx, and its `__str__` embeds
    `real_url`; logging the exception itself would spill the password. The test
    that asserts the password is absent from the log is only meaningful against
    an error that actually carries it, so it is built here rather than faked.
    """
    _url = URL(f"https://{HOST}/telecamera.php?CAM_PASSWD={PASSWORD}")
    _info = RequestInfo(url=_url, method="GET", headers={}, real_url=_url)
    return ClientResponseError(request_info=_info, history=(), status=401, message="Unauthorized")


@pytest.fixture(autouse=True)
def _no_real_warmup(monkeypatch):
    """Drop the empirical warm-up sleep so the tests do not wait on wall clock."""
    monkeypatch.setattr(camera, "CAMERA_WARMUP", 0.0)


def _make_camera() -> "camera.MyHOMEDoorCamera":
    return camera.MyHOMEDoorCamera(
        hass=types.SimpleNamespace(data={}),
        name="Front gate",
        entity_name=None,
        device_id="8-20",
        who="8",
        where="20",
        camera_where=4000,
        camera_password=PASSWORD,
        camera_host=HOST,
        verify_ssl=False,
        manufacturer="BTicino S.p.A.",
        model=None,
        gateway=FakeGateway(),
    )


def _install_session(monkeypatch, response) -> FakeSession:
    _session = FakeSession(response)
    monkeypatch.setattr(camera, "async_get_clientsession", lambda hass, verify_ssl=True: _session)
    return _session


# --------------------------------------------------------------------------- #
# A snapshot opens a session, then pulls one frame
# --------------------------------------------------------------------------- #


def test_a_snapshot_opens_a_session_and_returns_the_frame(monkeypatch):
    _install_session(monkeypatch, FakeResponse(body=JPEG))
    _cam = _make_camera()

    _image = asyncio.run(_cam.async_camera_image())

    assert _image == JPEG
    # The stream is dark outside a session: the WHO=7 activation goes first.
    assert _cam._gateway_handler.sent == ["*7*0*4000##"]


def test_the_request_carries_the_password_as_a_param_and_a_timeout(monkeypatch):
    _session = _install_session(monkeypatch, FakeResponse(body=JPEG))
    _cam = _make_camera()

    asyncio.run(_cam.async_camera_image())

    (_url, _kwargs), = _session.calls
    # The password rides in the query string, never in the URL path itself.
    assert _url == f"https://{HOST}/telecamera.php"
    assert _kwargs["params"] == {"CAM_PASSWD": PASSWORD}
    assert isinstance(_kwargs["timeout"], ClientTimeout)
    assert _kwargs["timeout"].total == 8


# --------------------------------------------------------------------------- #
# The throttle: at most one session + fetch per window, success or failure
# --------------------------------------------------------------------------- #


def test_a_second_snapshot_within_the_window_is_served_from_cache(monkeypatch):
    _install_session(monkeypatch, FakeResponse(body=JPEG))
    _cam = _make_camera()

    async def _twice():
        _first = await _cam.async_camera_image()
        _second = await _cam.async_camera_image()
        return _first, _second

    _first, _second = asyncio.run(_twice())

    assert _first == JPEG
    assert _second == JPEG
    # One session opened, not two: the second call was cache, not a fresh fetch.
    assert _cam._gateway_handler.sent == ["*7*0*4000##"]


def test_the_throttle_holds_even_when_the_fetch_fails(monkeypatch):
    """A persistent 401 must not re-open a session on every single call.

    With the throttle keyed on "do we have an image yet", a panel that never
    yields a frame would re-arm the session and hit the bus on every poll. The
    stamp is taken before the fetch, so a failure counts against the window too.
    """
    _install_session(monkeypatch, FakeResponse(error=_client_response_error()))
    _cam = _make_camera()

    async def _twice():
        _first = await _cam.async_camera_image()
        _second = await _cam.async_camera_image()
        return _first, _second

    _first, _second = asyncio.run(_twice())

    assert _first is None
    assert _second is None
    # Exactly one activation despite two calls and no successful frame.
    assert _cam._gateway_handler.sent == ["*7*0*4000##"]


# --------------------------------------------------------------------------- #
# The password never reaches the log
# --------------------------------------------------------------------------- #


def test_the_password_is_never_logged(monkeypatch, caplog):
    """A failed fetch is logged by type and status only, never the exception.

    The aiohttp error string embeds the request URL, which embeds the password;
    interpolating the exception (or the URL) would spill it into
    `home-assistant.log`. The warning must name the failure without it.
    """
    _install_session(monkeypatch, FakeResponse(error=_client_response_error()))
    _cam = _make_camera()

    with caplog.at_level(logging.WARNING):
        _image = asyncio.run(_cam.async_camera_image())

    assert _image is None
    assert PASSWORD not in caplog.text
    assert "CAM_PASSWD" not in caplog.text
    assert HOST not in caplog.text
    # The failure is still reported: type and HTTP status make the log useful.
    assert "ClientResponseError" in caplog.text
    assert "401" in caplog.text
