"""Offline encoders for formats confirmed in YLYDD-0053 packet captures.

This module does not connect, pair, or send anything to a device.
"""

from __future__ import annotations

import binascii
import json

GIF_BLOCK_SIZE = 504
FILE_ACK = b"\x06"
FILE_END = b"\x04"


def encode_request(request_id: int, method: str, params: list) -> bytes:
    """Encode a JSON request for AE3B, including the observed CR LF delimiter."""
    if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 1:
        raise ValueError("request_id must be a positive integer")
    if not isinstance(method, str) or not method or not isinstance(params, list):
        raise ValueError("method must be a nonempty string and params must be a list")
    message = {"id": request_id, "method": method, "params": params}
    return (
        json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\r\n"
    ).encode("utf-8")


def gif_upload_packets(gif: bytes) -> list[bytes]:
    """Build the observed AE3D blocks and final EOT byte.

    A sender must wait for AE3E ACK (0x06) after every block and after EOT.
    Each data block is 509 bytes: 3-byte header, 504-byte payload, 2-byte CRC.
    This size and CRC were verified against all 229 captured data blocks.
    BLE/proxy MTU compatibility and retry behavior still need hardware tests.
    """
    if not gif.startswith((b"GIF87a", b"GIF89a")):
        raise ValueError("Expected a GIF87a or GIF89a file")
    count = (len(gif) + GIF_BLOCK_SIZE - 1) // GIF_BLOCK_SIZE
    if count > 255:
        raise ValueError("Sequence-number rollover has not been verified")
    packets = []
    for index in range(count):
        sequence = index + 1
        payload = gif[index * GIF_BLOCK_SIZE : (index + 1) * GIF_BLOCK_SIZE]
        payload = payload.ljust(GIF_BLOCK_SIZE, b"\x1a")
        crc = binascii.crc_hqx(payload, 0xFFFF).to_bytes(2, "big")
        packets.append(bytes((1, sequence, sequence ^ 0xFF)) + payload + crc)
    return packets + [FILE_END]


def decode_gif_blocks(blocks: list[bytes]) -> bytes:
    """Validate captured data blocks; return bytes including terminal padding.

    Padding cannot safely be removed with rstrip: a real GIF might end in a
    padding-like byte. The original GIF size or a structural GIF parser is needed.
    """
    if not blocks:
        raise ValueError("No data blocks")
    payloads = []
    for sequence, block in enumerate(blocks, 1):
        if len(block) != GIF_BLOCK_SIZE + 5:
            raise ValueError(f"Invalid block length at sequence {sequence}")
        if block[:3] != bytes((1, sequence, sequence ^ 0xFF)):
            raise ValueError(f"Invalid sequence/header at block {sequence}")
        payload = block[3:-2]
        if binascii.crc_hqx(payload, 0xFFFF) != int.from_bytes(block[-2:], "big"):
            raise ValueError(f"CRC mismatch at block {sequence}")
        payloads.append(payload)
    result = b"".join(payloads)
    if not result.startswith((b"GIF87a", b"GIF89a")):
        raise ValueError("Transfer is not a GIF")
    return result
