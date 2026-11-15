"""Validate private library uploads through HA's actual file-upload ownership API."""

import io
from types import SimpleNamespace

import pytest
from homeassistant.components.file_upload import FileUploadData
from homeassistant.core import HomeAssistant
from PIL import Image

from custom_components.yeelight_curtain_ble.custom_gif import (
    MAX_GIF_BYTES,
    cleanup_library,
    gif_path,
    import_uploaded_gif,
    read_custom_gif,
    validate_gif,
)


def make_gif(size=(19, 25), frames=2):
    buffer = io.BytesIO()
    images = [Image.new("RGB", size, (index % 256, 0, 0)) for index in range(frames)]
    images[0].save(buffer, format="GIF", save_all=True, append_images=images[1:], duration=100, loop=0)
    return buffer.getvalue()


@pytest.mark.parametrize("data", [b"not a gif", make_gif((20, 25)), make_gif(frames=49), b"x" * (MAX_GIF_BYTES + 1), make_gif()[:-1]])
def test_invalid_gifs_rejected(data):
    with pytest.raises(ValueError):
        validate_gif(data)


async def test_native_upload_validation_storage_and_cleanup(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    upload_id = "upload-one"
    directory = uploads / upload_id
    directory.mkdir()
    (directory / "original.gif").write_bytes(make_gif())
    hass.data["file_upload"] = FileUploadData(uploads, {upload_id: "original.gif"})
    metadata = await hass.async_add_executor_job(import_uploaded_gif, hass, "entry", upload_id, "My animation")
    assert metadata["frames"] == 2 and metadata["name"] == "My animation"
    assert not directory.exists() and not hass.data["file_upload"].has_file(upload_id)
    assert await hass.async_add_executor_job(read_custom_gif, hass, "entry", metadata) == make_gif()
    path = gif_path(hass, "entry", metadata["sha256"])
    assert "custom_components" not in str(path) and "/www/" not in str(path)
    await hass.async_add_executor_job(cleanup_library, hass, "entry", {"My animation": metadata})
    assert path.exists()
    path.write_bytes(make_gif(frames=3))
    with pytest.raises(ValueError, match="checksum"):
        read_custom_gif(hass, "entry", metadata)
    unmanaged = path.parent / "keep.gif"
    unmanaged.write_bytes(b"unmanaged")
    await hass.async_add_executor_job(cleanup_library, hass, "entry", {})
    assert not path.exists() and unmanaged.exists()


def test_names_never_become_paths(tmp_path):
    hass = SimpleNamespace(config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts))))
    for digest in ("../secret", "x" * 64, "A" * 64):
        with pytest.raises(ValueError):
            gif_path(hass, "entry", digest)
