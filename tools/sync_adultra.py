#!/usr/bin/env python3
"""Sync AdUltra while changing exactly one script URL; fail closed on drift."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.request

SOURCE_URL = "https://yfamilys.com/module/adultra.sgmodule"
ORIGINAL_JS_URL = "https://raw.githubusercontent.com/app2smile/rules/master/js/qidian.js"
REPLACEMENT_JS_URL = "https://raw.githubusercontent.com/ninggee/Egern/main/scripts/qidian.js?v=20261128-activityicon"
TARGET = Path(__file__).resolve().parents[1] / "modules/adultra-qidian-fix.sgmodule"
MAX_BYTES = 5 * 1024 * 1024
REQUIRED_SECTIONS = ("Rule", "URL Rewrite", "Body Rewrite", "Map Local", "Script", "MITM")


class SyncError(ValueError):
    """Upstream download or structure is unsafe to publish."""


def render_module(source: bytes) -> bytes:
    if not source or len(source) > MAX_BYTES:
        raise SyncError("Upstream is empty or exceeds the 5 MiB safety limit")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SyncError("Upstream is not valid UTF-8") from exc
    if "\x00" in text or re.search(r"(?is)^\s*(?:<!doctype\s+html|<html\b)", text):
        raise SyncError("Upstream looks like HTML or binary data, not a module")
    sections = re.findall(r"(?m)^\[([^\]\r\n]+)\]\s*$", text)
    for section in REQUIRED_SECTIONS:
        if sections.count(section) != 1:
            raise SyncError(f"Expected exactly one [{section}] section")
    if source.count(ORIGINAL_JS_URL.encode()) != 1:
        raise SyncError("Expected exactly one original Qidian URL; manual review required")
    if REPLACEMENT_JS_URL in text:
        raise SyncError("Upstream already contains the replacement URL; manual review required")
    script_section = re.split(r"(?m)^\[Script\]\s*$", text, maxsplit=1)[1]
    script_section = re.split(r"(?m)^\[[^\]\r\n]+\]\s*$", script_section, maxsplit=1)[0]
    rules = [line for line in script_section.splitlines()
             if not line.lstrip().startswith(("#", ";"))
             and re.search(r"\bscript-path=" + re.escape(ORIGINAL_JS_URL) + r"(?=,|\s*$)", line)]
    if len(rules) != 1 or not re.search(r"\btype=http-response(?=,|\s*$)", rules[0]):
        raise SyncError("Target URL is not in exactly one active HTTP response script rule")
    result = source.replace(ORIGINAL_JS_URL.encode(), REPLACEMENT_JS_URL.encode(), 1)
    if result.replace(REPLACEMENT_JS_URL.encode(), ORIGINAL_JS_URL.encode(), 1) != source:
        raise SyncError("Unexpected change outside the target URL")
    return result


def fetch_source() -> bytes:
    request = urllib.request.Request(SOURCE_URL, headers={
        "User-Agent": "Surge/5.0 AdUltraSync/1.0",
        "Accept": "text/plain, application/octet-stream;q=0.9, */*;q=0.5",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.geturl().split(":", 1)[0].lower() != "https":
                raise SyncError("Refusing a non-HTTPS final download URL")
            data = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SyncError(f"Cannot download upstream; existing module is unchanged: {exc}") from exc
    return data


def sync_bytes(source: bytes, target: Path = TARGET) -> bool:
    result = render_module(source)
    if target.exists() and target.read_bytes() == result:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".adultra-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(result)
        os.chmod(temporary, 0o644)
        temporary.replace(target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, help="Use a local source for offline validation")
    args = parser.parse_args()
    try:
        source = args.source_file.read_bytes() if args.source_file else fetch_source()
        changed = sync_bytes(source)
    except (SyncError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Upstream SHA-256: {hashlib.sha256(source).hexdigest()}")
    print("Updated module (one URL replacement)." if changed else "No upstream change; no file written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
