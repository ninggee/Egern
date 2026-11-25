#!/usr/bin/env python3
"""Parse generated Egern modules and verify their minimum shape."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import yaml

REJECT_TARGETS = {
    (404, "", ()): "http://reject/",
    (200, "", ()): "http://reject-200/",
    (200, "{}", (("Content-Type", "application/json"),)): "http://reject-dict/",
    (200, "[]", (("Content-Type", "application/json"),)): "http://reject-array/",
}


def normalize(text: str) -> str:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Module is not a mapping")
    replacements = {}
    if "rewrites" in data:
        rules = []
        for rewrite in data["rewrites"] or []:
            actions = rewrite.get("actions", [])
            if len(actions) != 1 or set(actions[0]) != {"respond"}:
                raise ValueError("Unsupported response action")
            response = actions[0]["respond"]
            status = response.get("status")
            body = response.get("body", "")
            headers = response.get("headers") or {}
            rule = {"match": rewrite["match"]}
            if status in (301, 302, 307, 308) and set(headers) == {"Location"} and not body:
                rule.update(location=headers["Location"], status_code=status)
            else:
                key = (status, body, tuple(sorted(headers.items())))
                if key not in REJECT_TARGETS:
                    raise ValueError("Response requires Map Local support; keeping original source")
                rule["location"] = REJECT_TARGETS[key]
            rules.append(rule)
        if data.get("url_rewrites"):
            raise ValueError("Mixed response and URL rewrites require an order review")
        replacements["rewrites"] = yaml.safe_dump({"url_rewrites": rules}, allow_unicode=True, sort_keys=False)
    if "compat_arguments_schema" in data:
        descriptions = []
        for name, schema in data["compat_arguments_schema"].items():
            descriptions.append(f"{name}: {schema.get('description') or name}")
        replacements["compat_arguments_schema"] = yaml.safe_dump(
            {"compat_arguments_desc": "\n".join(descriptions)}, allow_unicode=True, sort_keys=False
        )
    if not replacements:
        return text
    sections = re.split(r"(?m)(?=^[A-Za-z_][\w-]*:)", text)
    output = []
    for section in sections:
        match = re.match(r"([A-Za-z_][\w-]*):", section)
        output.append(replacements.get(match.group(1), section) if match else section)
    return "".join(output)


def validate(directory: Path, normalize_files: bool = False) -> int:
    files = sorted(directory.glob("*.yaml"))
    valid_count = 0
    effective_fields = {"rules", "url_rewrites", "header_rewrites", "body_rewrites", "map_locals", "scriptings", "mitm", "real_ip_domains"}
    for path in files:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}\.yaml", path.name):
            raise ValueError(f"Unexpected generated filename: {path.name}")
        try:
            text = path.read_text(encoding="utf-8")
            if normalize_files:
                text = normalize(text)
            data = yaml.safe_load(text)
            if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
                raise ValueError("Generated module has no valid name")
            if "rewrites" in data or "compat_arguments_schema" in data:
                raise ValueError("Generated module contains undocumented converter fields")
            for rule in data.get("rules") or []:
                for body in rule.values():
                    if isinstance(body, dict) and body.get("policy") not in (None, "DIRECT", "REJECT"):
                        raise ValueError("Module requires a source-specific policy review")
            if not any(data.get(field) for field in effective_fields):
                raise ValueError("Generated module has no effective content")
            if normalize_files:
                path.write_text(text, encoding="utf-8", newline="\n")
            valid_count += 1
        except (yaml.YAMLError, ValueError, TypeError, KeyError, AttributeError):
            if not normalize_files:
                raise ValueError(f"Generated module failed validation: {path.name}")
            path.unlink()
            print(f"Skipped incompatible generated module: {path.stem}")
    print(f"Validated {valid_count} generated Egern modules.")
    if normalize_files and (directory / "summary.md").is_file():
        with (directory / "summary.md").open("a", encoding="utf-8") as handle:
            handle.write(f"\nPassed Egern field checks: {valid_count}/{len(files)}. Failed active sources keep their previous outputs.\n")
    return valid_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--normalize", action="store_true")
    args = parser.parse_args()
    try:
        validate(args.directory, args.normalize)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
