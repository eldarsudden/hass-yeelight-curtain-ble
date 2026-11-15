"""Export an allowlisted repository for review before publishing to GitHub."""

import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist/hacs-repository"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    files = [
        ROOT / name
        for name in (
            "README.md",
            "AGENTS.md",
            "INSTALL.md",
            "CHANGELOG.md",
            "hacs.json",
            "pyproject.toml",
            "requirements-dev.txt",
        )
    ]
    files += [
        ROOT / "tools/build_release.py",
        ROOT / "tools/prepare_hacs_repo.py",
        ROOT / ".github/workflows/release.yml",
        ROOT / ".github/workflows/release-notes.yml",
    ]
    for folder in (ROOT / "custom_components/yeelight_curtain_ble", ROOT / "tests"):
        files += [
            p
            for p in folder.rglob("*")
            if p.is_file() and p.suffix in (".py", ".json", ".gif", ".png", ".js")
        ]
    for path in sorted(files):
        target = OUTPUT / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (OUTPUT / ".gitignore").write_text(
        ".venv/\n__pycache__/\n.pytest_cache/\n.ruff_cache/\ndist/\n.captures/\n*.log\n"
    )
    exported = sorted(
        [OUTPUT / p.relative_to(ROOT) for p in files]
        + [OUTPUT / ".gitignore"]
    )
    assert not any(p.suffix in (".cfa", ".mp4", ".apk", ".jpg", ".log") for p in exported)
    archive_path = ROOT / "dist/hacs-repository.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in exported:
            archive.write(path, path.relative_to(OUTPUT).as_posix())
    review = {
        "intended_repository": "eldarsudden/hass-yeelight-curtain-ble",
        "published": False,
        "files": [
            {
                "path": p.relative_to(OUTPUT).as_posix(),
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in exported
        ],
    }
    (ROOT / "dist/publication-review.json").write_text(json.dumps(review, indent=2) + "\n")
    print(f"Prepared {len(exported)} files at {OUTPUT}; archive {archive_path}")


if __name__ == "__main__":
    main()
