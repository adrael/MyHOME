"""The "Open" button of a video door entry panel (WHO=8).

Home Assistant is stubbed (see `ha_stubs`); `OWNd` is real. The panel's Open
button pulses the gate strike — energise, then release — and the two frames must
leave in that order, or the strike is left under tension. The test captures what
`async_press` sends and asserts the pair and its order.
"""

import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ha_stubs  # noqa: E402

const = ha_stubs.load("const")
button = ha_stubs.load("button")

MAC = "00:03:50:11:22:33"


class FakeGateway:
    """Just enough of the handler: an async `send` recording each frame."""

    mac = MAC
    unique_id = MAC
    device_id = "gateway-registry-id"
    log_id = "[test]"

    def __init__(self):
        self.sent = []

    async def send(self, message):
        await asyncio.sleep(0)
        self.sent.append(str(message))


def _open_button(lock_address=20) -> "button.MyHOMEVideoDoorEntryButton":
    return button.MyHOMEVideoDoorEntryButton(
        hass=types.SimpleNamespace(data={}),
        name="Front gate",
        device_id="8-20",
        who="8",
        where="20",
        lock_address=lock_address,
        manufacturer="BTicino S.p.A.",
        model=None,
        gateway=FakeGateway(),
    )


def test_pressing_open_pulses_the_strike_in_order():
    """Energise `*8*19*<addr>##`, then release `*8*20*<addr>##`, in that order."""
    _button = _open_button(20)
    asyncio.run(_button.async_press())
    assert _button._gateway_handler.sent == ["*8*19*20##", "*8*20*20##"]


def test_the_open_button_uses_the_configured_lock_address():
    _button = _open_button(11)
    asyncio.run(_button.async_press())
    assert _button._gateway_handler.sent == ["*8*19*11##", "*8*20*11##"]
