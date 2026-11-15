"""Protocol regression and failure handling without a real lamp."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from custom_components.yeelight_curtain_ble.client import CurtainClient, CurtainError
from custom_components.yeelight_curtain_ble.const import FILE_NOTIFY, JSON_NOTIFY
from custom_components.yeelight_curtain_ble.coordinator import load_catalog
from custom_components.yeelight_curtain_ble.protocol import gif_upload_packets

ROOT = Path(__file__).parents[1]


def make_client(peripheral, **kwargs):
    async def connect(disconnected_callback):
        peripheral.is_connected = True
        peripheral.disconnected_callback = disconnected_callback
        return peripheral

    return CurtainClient(connect, **kwargs)


async def test_fragmented_reads_and_separate_request_ids(peripheral):
    client = make_client(peripheral)
    state = await client.read_state()
    assert state == {
        "power": "off",
        "bright": 9,
        "music": {"on": 0, "effect_id": 0},
        "effect": [71, 1012, {}],
        "color_mode": 14,
    }
    assert [r["id"] for r in peripheral.requests] == [1, 2, 3, 4, 5]
    assert len(peripheral.callbacks) == 1
    assert not client._pending
    await client.disconnect()
    assert not peripheral.is_connected


async def test_timeout_cleans_pending_request(peripheral):
    client = make_client(peripheral, timeout=0.01)
    peripheral.drop_reply = True
    with pytest.raises(TimeoutError):
        await client.read_state()
    assert not client._pending
    await client.disconnect()


async def test_disconnect_fails_request_without_waiting_for_timeout(peripheral):
    client = make_client(peripheral, timeout=10)
    peripheral.drop_reply = True
    task = asyncio.create_task(client.request("get_prop", ["power"]))
    while not peripheral.requests:
        await asyncio.sleep(0)
    await peripheral.disconnect()
    with pytest.raises(CurtainError, match="disconnected"):
        await asyncio.wait_for(task, 0.5)
    assert not client._pending


async def test_props_coalesced_with_reply_and_stale_id(peripheral):
    observed = []
    client = make_client(peripheral, on_props=observed.append)
    await client.read_state()
    peripheral.callbacks[JSON_NOTIFY](
        None, b'{"id":1,"result":["stale"]}\r\n{"method":"props","params":{"power":"on"}}\r\n'
    )
    assert observed == [{"power": "on"}]
    await client.disconnect()


async def test_upload_obeys_block_ack_and_eot(peripheral):
    client = make_client(peripheral)
    gif = (ROOT / "custom_components/yeelight_curtain_ble/presets/ufo.gif").read_bytes()
    await client.upload(gif)
    assert peripheral.file_packets == gif_upload_packets(gif)
    assert len(peripheral.file_packets[-1]) == 1
    assert FILE_NOTIFY in peripheral.callbacks
    await client.disconnect()


@pytest.mark.parametrize("mtu,max_write", [(247, 509), (512, 244)])
async def test_upload_rejects_small_proxy_before_first_block(peripheral, mtu, max_write):
    client = make_client(peripheral)
    peripheral.mtu_size = mtu
    peripheral.services.get_characteristic = lambda _uuid: type(
        "Char", (), {"max_write_without_response_size": max_write}
    )()
    with pytest.raises(CurtainError, match="509 bytes"):
        await client.upload(b"GIF89a" + b"x" * 20)
    assert peripheral.file_packets == []
    await client.disconnect()


async def test_upload_aborts_on_bad_ack_without_retransmission(peripheral):
    client = make_client(peripheral)
    peripheral.ack = b"\x15"
    with pytest.raises(CurtainError, match="acknowledgement"):
        await client.upload(b"GIF89a" + b"x" * 1000)
    assert len(peripheral.file_packets) == 1
    await client.disconnect()


def test_catalog_and_gif_integrity():
    catalog = load_catalog()
    assert len(catalog["presets"]) == 19
    assert len(catalog["music_effects"]) == 6
    assert len(catalog["palettes"]) == 40
    for preset in catalog["presets"]:
        if "file" in preset:
            file = ROOT / "custom_components/yeelight_curtain_ble/presets" / preset["file"]
            assert hashlib.sha256(file.read_bytes()).hexdigest() == preset["sha256"]
    assert all(len(palette) == 16 for palette in catalog["palettes"].values())


def test_encoder_against_original_captures():
    from custom_components.yeelight_curtain_ble.protocol import encode_request

    files = [
        ROOT / ".captures/2026-11-15/decoded-capture.json",
        *sorted((ROOT / ".captures/2026-11-15/music").glob("*.json")),
    ]
    count = 0
    for path in files:
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for row in data.get("att_records", []):
            request = row.get("json", {})
            if row["direction"] == "phone_to_device" and "method" in request:
                assert encode_request(
                    request["id"], request["method"], request["params"]
                ) == bytes.fromhex(row["value_hex"])
                count += 1
    if not count:
        pytest.skip("Private captures are not distributed")
    assert count >= 142


async def test_uniform_hsv_readback_and_exit_to_effect(peripheral):
    client = make_client(peripheral)
    peripheral.color_mode = 3
    peripheral.hue, peripheral.sat = 233, 100
    peripheral.effect = [0, 0, {}]
    state = await client.read_state()
    assert state["color_mode"] == 3 and state["hs_color"] == (233, 100)
    assert [r["params"] for r in peripheral.requests[-3:]] == [["color_mode"], ["hue"], ["sat"]]
    peripheral.color_mode = 14
    state = await client.read_state()
    assert "hs_color" not in state
    await client.disconnect()


@pytest.mark.parametrize("hue,sat", [(360, 10), (-1, 10), (20, 101), (20, -1), ("not a number", 50)])
async def test_invalid_hsv_readback_is_rejected(peripheral, hue, sat):
    client = make_client(peripheral)
    peripheral.color_mode = 3
    peripheral.hue, peripheral.sat = hue, sat
    with pytest.raises(CurtainError, match="Invalid state response"):
        await client.read_state()
    await client.disconnect()
