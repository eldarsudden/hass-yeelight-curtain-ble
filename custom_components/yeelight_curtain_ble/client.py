"""Async transport; the caller supplies the connection, including HA proxies."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError

from .const import FILE_NOTIFY, FILE_WRITE, JSON_NOTIFY, JSON_WRITE
from .protocol import FILE_ACK, encode_request, gif_upload_packets


class CurtainError(Exception):
    """A transport, framing or device error."""


class CurtainClient:
    """Keep one connection; correlate replies and fail pending requests on loss."""

    def __init__(
        self,
        connect: Callable[..., Awaitable[BleakClient]],
        on_props: Callable[[dict[str, Any]], None] | None = None,
        timeout: float = 10,
    ) -> None:
        self._connect = connect
        self._on_props = on_props
        self._timeout = timeout
        self._client: BleakClient | None = None
        self._buffer = bytearray()
        self._pending: dict[int, asyncio.Future] = {}
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._file_ack: asyncio.Queue[bytes] = asyncio.Queue()
        self._file_subscribed = False

    def _disconnected(self, client: BleakClient) -> None:
        if self._client is not client:
            return
        self._client = None
        if self._file_subscribed:
            self._file_ack.put_nowait(b"")
        self._file_subscribed = False
        self._fail_pending()

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(CurtainError("Bluetooth disconnected"))

    def _notify(self, _characteristic, payload: bytearray) -> None:
        self._buffer.extend(payload)
        if len(self._buffer) > 65536:
            self._buffer.clear()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CurtainError("JSON notification exceeded 64 KiB"))
            return
        while b"\n" in self._buffer:
            line, _, remaining = self._buffer.partition(b"\n")
            self._buffer[:] = remaining
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Expected a JSON object")
                request_id = message.get("id")
                if isinstance(request_id, int):
                    future = self._pending.get(request_id)
                    if future is not None and not future.done():
                        future.set_result(message)
                if message.get("method") == "props" and self._on_props is not None:
                    params = message.get("params")
                    if isinstance(params, dict):
                        self._on_props(params)
            except (ValueError, UnicodeDecodeError):
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(CurtainError("Malformed JSON notification"))

    async def _ensure_connected(self) -> BleakClient:
        if self._client is not None and self._client.is_connected:
            return self._client
        self._buffer.clear()
        self._file_subscribed = False
        client = await self._connect(self._disconnected)
        self._client = client
        try:
            for uuid in (JSON_WRITE, JSON_NOTIFY):
                if client.services.get_characteristic(uuid) is None:
                    raise CurtainError("Device lacks the curtain JSON characteristics")
            await asyncio.wait_for(client.start_notify(JSON_NOTIFY, self._notify), self._timeout)
        except BaseException:
            await self.disconnect()
            raise
        return client

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        self._file_subscribed = False
        self._fail_pending()
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), self._timeout)
            except (BleakError, TimeoutError):
                pass

    async def request(self, method: str, params: list) -> list:
        async with self._lock:
            client = await self._ensure_connected()
            self._sequence += 1
            request_id = self._sequence
            future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            try:
                async with asyncio.timeout(self._timeout):
                    await client.write_gatt_char(
                        JSON_WRITE, encode_request(request_id, method, params), response=True
                    )
                    reply = await future
                if "error" in reply:
                    raise CurtainError(f"{method} rejected: {reply['error']}")
                if not isinstance(reply.get("result"), list):
                    raise CurtainError(f"{method} returned no result list")
                return reply["result"]
            finally:
                self._pending.pop(request_id, None)
                if future.done() and not future.cancelled():
                    future.exception()
                else:
                    future.cancel()

    async def set(self, method: str, params: list) -> None:
        if await self.request(method, params) != ["ok"]:
            raise CurtainError(f"{method} was not acknowledged")

    async def read_state(self) -> dict[str, Any]:
        power = await self.request("get_prop", ["power"])
        bright = await self.request("get_prop", ["bright"])
        music = await self.request("get_prop", ["mic_music_mode"])
        effect = await self.request("get_fx_effect", [])
        try:
            state = {
                "power": power[0],
                "bright": int(bright[0]),
                "music": json.loads(music[0]),
                "effect": effect,
            }
            if state["power"] not in ("on", "off") or not 0 <= state["bright"] <= 100:
                raise ValueError("Invalid power or brightness")
            if not isinstance(state["music"], dict) or state["music"].get("on") not in (0, 1):
                raise ValueError("Invalid music state")
            if len(effect) < 2 or not all(isinstance(x, int) for x in effect[:2]):
                raise ValueError("Invalid effect state")
        except (ValueError, IndexError, TypeError) as error:
            raise CurtainError(f"Invalid state response: {error}") from error
        return state

    async def upload(self, gif: bytes) -> None:
        packets = gif_upload_packets(gif)
        async with self._lock:
            client = await self._ensure_connected()
            characteristic = client.services.get_characteristic(FILE_WRITE)
            if characteristic is None or client.services.get_characteristic(FILE_NOTIFY) is None:
                raise CurtainError("Device lacks the GIF transfer characteristics")
            if min(client.mtu_size - 3, characteristic.max_write_without_response_size) < 509:
                raise CurtainError(
                    "GIF transfer needs MTU 512 and writes of 509 bytes; "
                    "this Bluetooth adapter/proxy cannot currently provide them"
                )
            if not self._file_subscribed:
                await asyncio.wait_for(
                    client.start_notify(
                        FILE_NOTIFY, lambda _char, data: self._file_ack.put_nowait(bytes(data))
                    ),
                    self._timeout,
                )
                self._file_subscribed = True
            while not self._file_ack.empty():
                self._file_ack.get_nowait()
            # Never blindly retry a block: ACK loss/retransmission was not captured.
            for packet in packets:
                async with asyncio.timeout(self._timeout):
                    await client.write_gatt_char(FILE_WRITE, packet, response=False)
                    if await self._file_ack.get() != FILE_ACK:
                        raise CurtainError("Unexpected GIF transfer acknowledgement")
