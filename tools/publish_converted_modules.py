#!/usr/bin/env python3
"""Publish validated conversion artifacts without touching other module files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import unicodedata


MODULE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
SOURCE_EXTENSION_RE = re.compile(r"\.(?:sgmodule|module|conf)$", re.IGNORECASE)
INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
RESERVED_FILENAME_RE = re.compile(r"CON|PRN|AUX|NUL|(?:COM|LPT)[1-9\u00b9\u00b2\u00b3]", re.IGNORECASE)


def module_filenames(manifest: object) -> dict[str, str]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        raise ValueError("Manifest must contain a sources array")

    filenames = {}
    owners = {}
    for entry in manifest["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("Source entry must be an object")
        module_id = entry.get("id")
        if not isinstance(module_id, str) or not MODULE_ID_RE.fullmatch(module_id) or module_id in filenames:
            raise ValueError("Source IDs must be unique lowercase slugs")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Source {module_id} needs a name")

        filename = entry.get("filename", SOURCE_EXTENSION_RE.sub("", name) + ".yaml")
        if not isinstance(filename, str) or not filename.endswith(".yaml"):
            raise ValueError(f"Source {module_id} needs a .yaml output filename")
        stem = filename.removesuffix(".yaml")
        if (
            not stem
            or stem.strip(" .") != stem
            or INVALID_FILENAME_RE.search(filename)
            or RESERVED_FILENAME_RE.fullmatch(stem.partition(".")[0].rstrip(" "))
            or len(filename.encode("utf-8")) > 255
        ):
            raise ValueError(f"Source {module_id} needs a portable output filename")

        key = unicodedata.normalize("NFC", filename.casefold())
        if key in owners:
            raise ValueError(f"Sources {owners[key]} and {module_id} share an output filename; set a unique filename")
        owners[key] = module_id
        filenames[module_id] = filename
    return filenames


def publish(artifact_dir: Path, manifest_path: Path, destination: Path, summary_path: Path | None = None) -> None:
    if not artifact_dir.is_dir():
        raise ValueError("Conversion artifact directory does not exist")
    artifact_digest = artifact_dir / "manifest.sha256"
    if artifact_digest.exists():
        actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if artifact_digest.read_text(encoding="utf-8").strip() != actual:
            raise ValueError("The source manifest changed after conversion; retry using its current revision")
    filenames = module_filenames(json.loads(manifest_path.read_text(encoding="utf-8")))
    active_filenames = set(filenames.values())

    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.iterdir():
        if (
            existing.suffix == ".yaml"
            and existing.name not in active_filenames
            and not existing.is_symlink()
            and existing.is_file()
        ):
            existing.unlink()

    for module_id, filename in filenames.items():
        artifact = artifact_dir / f"{module_id}.yaml"
        if not artifact.is_symlink() and artifact.is_file():
            target = destination / filename
            if target.is_symlink():
                raise ValueError(f"Source {module_id} output cannot be a symlink")
            shutil.copyfile(artifact, target)

    if summary_path is not None and (artifact_dir / "summary.md").is_file():
        summary_path.write_text((artifact_dir / "summary.md").read_text(encoding="utf-8"), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path("tools/module_sources.json"))
    parser.add_argument("--destination", type=Path, default=Path("modules/converted"))
    args = parser.parse_args()
    summary = Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None
    try:
        publish(args.artifact_dir, args.manifest, args.destination, summary)
    except (OSError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
