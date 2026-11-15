"""Package just the installable component and its installation instructions."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/yeelight_curtain_ble"


def main():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    output = ROOT / "dist" / f"yeelight_curtain_ble-{manifest['version']}.zip"
    output.parent.mkdir(exist_ok=True)
    files = [ROOT / "INSTALL.md"] + sorted(
        p
        for p in COMPONENT.rglob("*")
        if p.is_file() and p.suffix in (".py", ".json", ".gif", ".png")
    )
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            info = ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 11, 15, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert all(not name.startswith((".captures/", ".venv/")) for name in archive.namelist())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n")
    print(f"{output}: {len(files)} files, {output.stat().st_size} bytes, SHA-256 {digest}")


if __name__ == "__main__":
    main()
