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


MODULE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")


def publish(artifact_dir: Path, manifest_path: Path, destination: Path, summary_path: Path | None = None) -> None:
    artifact_digest = artifact_dir / "manifest.sha256"
    if artifact_digest.exists():
        actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if artifact_digest.read_text(encoding="utf-8").strip() != actual:
            raise ValueError("The source manifest changed after conversion; retry using its current revision")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in manifest.get("sources", [])}
    if not isinstance(manifest.get("sources"), list) or any(not MODULE_ID_RE.fullmatch(module_id) for module_id in ids):
        raise ValueError("Manifest must contain a sources array with valid IDs")

    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.iterdir():
        if existing.is_file() and not existing.is_symlink() and existing.suffix == ".yaml":
            module_id = existing.stem
            if MODULE_ID_RE.fullmatch(module_id) and module_id not in ids:
                existing.unlink()

    for artifact in artifact_dir.iterdir():
        if artifact.is_file() and MODULE_ID_RE.fullmatch(artifact.stem) and artifact.suffix == ".yaml":
            if artifact.stem in ids:
                shutil.copyfile(artifact, destination / artifact.name)

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
