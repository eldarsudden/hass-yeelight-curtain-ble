"""Package just the installable component and its installation instructions."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/yeelight_curtain_ble"


def build_release(tag: str | None = None) -> Path:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    version = manifest["version"]
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Release version must use stable MAJOR.MINOR.PATCH format")
    if tag is not None and tag != version:
        raise ValueError(f"Tag {tag!r} does not match manifest version {version!r}")
    notes = None
    if tag is not None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        match = re.search(
            rf"^## {re.escape(version)}(?: — [^\n]+)?\n(.*?)(?=^## |\Z)",
            changelog,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match or not match[1].strip():
            raise ValueError(f"Missing CHANGELOG entry for {version}")
        notes = match[1].strip() + "\n"
    output = ROOT / "dist" / f"yeelight_curtain_ble-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    files = [ROOT / "INSTALL.md"] + sorted(
        p
        for p in COMPONENT.rglob("*")
        if p.is_file() and p.suffix in (".py", ".json", ".gif", ".png", ".js")
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
    if notes is not None:
        (output.parent / "release-notes.md").write_text(notes, encoding="utf-8")
    print(f"{output}: {len(files)} files, {output.stat().st_size} bytes, SHA-256 {digest}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Require this release tag to match manifest and CHANGELOG")
    args = parser.parse_args()
    try:
        build_release(args.tag)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
