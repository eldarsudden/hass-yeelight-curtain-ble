"""A simulated peripheral at the Bleak boundary; no hardware writes in tests."""

import json
from types import SimpleNamespace

import pytest

from custom_components.yeelight_curtain_ble.const import FILE_NOTIFY, FILE_WRITE, JSON_NOTIFY


class Peripheral:
    def __init__(self):
        self.is_connected = True
        self.mtu_size = 512
        self.services = SimpleNamespace(
            get_characteristic=lambda _uuid: SimpleNamespace(max_write_without_response_size=509)
        )
        self.callbacks = {}
        self.requests = []
        self.file_packets = []
        self.drop_reply = False
        self.ack = b"\x06"
        self.power = "off"
        self.bright = 9
        self.music = {"on": 0, "effect_id": 0}
        self.effect = [71, 1012, {}]
        self.color_mode = 14
        self.hue = 0
        self.sat = 0
        self.adapter_set = 1
        self.adapter_side = 1
        self.disconnected_callback = None
        self.disconnects = 0

    async def start_notify(self, uuid, callback):
        self.callbacks[uuid] = callback

    async def stop_notify(self, uuid):
        self.callbacks.pop(uuid, None)

    async def disconnect(self):
        self.is_connected = False
        self.disconnects += 1
        if self.disconnected_callback:
            self.disconnected_callback(self)

    async def write_gatt_char(self, uuid, payload, response):
        if uuid == FILE_WRITE:
            assert response is False
            self.file_packets.append(bytes(payload))
            if not self.drop_reply:
                self.callbacks[FILE_NOTIFY](None, self.ack)
            return
        assert response is True
        assert payload.endswith(b"\r\n")
        request = json.loads(payload)
        self.requests.append(request)
        method, params = request["method"], request["params"]
        if method == "get_prop":
            result = [
                {
                    "power": self.power,
                    "bright": str(self.bright),
                    "mic_music_mode": json.dumps(self.music),
                    "color_mode": str(self.color_mode),
                    "hue": str(self.hue),
                    "sat": str(self.sat),
                    "adapter_set": str(self.adapter_set),
                    "adapter_side": str(self.adapter_side),
                }[params[0]]
            ]
        elif method == "get_fx_effect":
            result = self.effect
        elif method == "set_power":
            self.power = params[0]
            result = ["ok"]
        elif method == "set_scene":
            assert params[0] == "bright" and params[2] == 0
            self.bright = params[1]
            result = ["ok"]
        elif method == "set_ps":
            if params[0] == "adapter_side":
                assert params[1] in (0, 1)
                self.adapter_set = 1
                self.adapter_side = params[1]
            else:
                assert params[0] == "mic_music_mode" and isinstance(params[1], str)
                self.music = json.loads(params[1])
            result = ["ok"]
        elif method == "set_hsv":
            self.hue, self.sat, transition, duration = params
            assert transition == "smooth" and duration == 0
            self.color_mode = 3
            self.effect = [0, 0, {}]
            self.music = {"on": 0, "effect_id": 0}
            result = ["ok"]
        elif method == "set_fx_effect":
            options = dict(params[3])
            if "color" in options:
                # Hardware normalizes ARGB to signed ints and four padded slots.
                colors = [value if value < 2**31 else value - 2**32 for value in options["color"]]
                options["color"] = colors + [0] * (4 - len(colors))
            self.effect = params[:2] + [options]
            self.color_mode = 14
            result = ["ok"]
        else:
            result = [57]
        if not self.drop_reply:
            encoded = (json.dumps({"id": request["id"], "result": result}) + "\r\n").encode()
            # Split inside a JSON token, as can happen with notification fragmentation.
            self.callbacks[JSON_NOTIFY](None, encoded[:9])
            self.callbacks[JSON_NOTIFY](None, encoded[9:])


@pytest.fixture
def peripheral():
    return Peripheral()
