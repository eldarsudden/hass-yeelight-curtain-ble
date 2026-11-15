"""Validate and privately store user GIFs outside the installed component."""

import hashlib
import io
from pathlib import Path

from homeassistant.components.file_upload import process_uploaded_file
from PIL import Image, UnidentifiedImageError

from .const import DOMAIN

OPT_CUSTOM_GIFS = "custom_gifs"
OPT_LAST_CUSTOM_GIF = "last_custom_gif"
OPT_CUSTOM_SLOT = "custom_gif_slot"
MAX_GIF_BYTES = 504 * 255
MAX_GIF_FRAMES = 48
GIF_SIZE = (19, 25)
# Reuse the observed GIF activation parameters, not an invented firmware slot.
GIF_EFFECT = [71, 1007]


def validate_gif(data: bytes) -> dict:
    """Decode every frame within conservative bounds supported by our captures."""
    if not 0 < len(data) <= MAX_GIF_BYTES:
        raise ValueError(f"GIF must be at most {MAX_GIF_BYTES} bytes")
    if not data.endswith(b";"):
        raise ValueError("GIF trailer is missing")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "GIF" or image.size != GIF_SIZE:
                raise ValueError("Expected a 19 x 25 pixel GIF")
            count = 0
            while True:
                if image.size != GIF_SIZE:
                    raise ValueError("All GIF frames must be 19 x 25 pixels")
                image.load()
                count += 1
                if count > MAX_GIF_FRAMES:
                    raise ValueError("GIF must contain at most 48 frames")
                try:
                    image.seek(count)
                except EOFError:
                    break
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError("Invalid or truncated GIF") from error
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "frames": count}


def gif_path(hass, entry_id: str, digest: str) -> Path:
    """Only content-addressed files inside this entry's private library are allowed."""
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid GIF identifier")
    return Path(hass.config.path(DOMAIN, entry_id, f"{digest}.gif"))


def import_uploaded_gif(hass, entry_id: str, file_id: str, name: str) -> dict:
    """Consume a native HA upload, validate it and atomically save a private copy."""
    name = name.strip()
    if not name or len(name) > 64:
        raise ValueError("Use a GIF name between 1 and 64 characters")
    with process_uploaded_file(hass, file_id) as source:
        with source.open("rb") as handle:
            data = handle.read(MAX_GIF_BYTES + 1)
        metadata = {"name": name, **validate_gif(data)}
        target = gif_path(hass, entry_id, metadata["sha256"])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return metadata


def read_custom_gif(hass, entry_id: str, metadata: dict) -> bytes:
    """Revalidate the stored bytes before any device writes."""
    with gif_path(hass, entry_id, metadata["sha256"]).open("rb") as handle:
        data = handle.read(MAX_GIF_BYTES + 1)
    if validate_gif(data)["sha256"] != metadata["sha256"]:
        raise ValueError("Stored GIF checksum does not match")
    return data


def cleanup_library(hass, entry_id: str, library: dict) -> None:
    """Remove only unused managed GIFs after a successful options reload."""
    root = Path(hass.config.path(DOMAIN, entry_id))
    retained = {item["sha256"] for item in library.values()}
    for path in root.glob("*.gif"):
        digest = path.stem
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) and digest not in retained:
            path.unlink(missing_ok=True)
