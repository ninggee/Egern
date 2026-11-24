#!/usr/bin/env python3
"""Rebuild the consolidated bank direct list from upstream sources.

Sources:
  - LM-Firefly/Rules, one .list per bank in Domestic-Services.
  - v2fly/domain-list-community data/category-bank-cn (direct domains only;
    include: lines are category references, not domains).
  - A small static extras block for banks the upstreams do not cover.

The script fails closed: any upstream download problem, empty file, HTML
response, missing required domain, or implausible total aborts the run and
leaves the checked-in list untouched. Bare words without a dot (for example
the `icbc` and `citic` entries carried by the upstream lists) are dropped,
because no real hostname ends in a bare word. Non-ASCII domains are converted
to punycode.
"""
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

LM_FIREFLY_BASE = "https://raw.githubusercontent.com/LM-Firefly/Rules/master/Domestic-Services/"
V2FLY_BANK_CN = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/category-bank-cn"
TARGET = Path(__file__).resolve().parents[1] / "rules/bank_direct_all.list"
MAX_BYTES = 5 * 1024 * 1024
MIN_TOTAL = 200
MAX_TOTAL = 2000

# (upstream file, group name) in the order groups appear in the output.
BANKS = [
    ("ICBC", "工商银行"),
    ("CCB", "建设银行"),
    ("ABC", "农业银行"),
    ("BOC", "中国银行"),
    ("BOCOM", "交通银行"),
    ("PSBC", "邮储银行"),
    ("CMB", "招商银行"),
    ("CITIC", "中信银行"),
    ("CEB", "光大银行"),
    ("CGB", "广发银行"),
    ("PingAn", "平安"),
]

# Static domains the upstreams do not cover, grouped for the output.
EXTRAS = [
    ("浙商银行", ["czbank.com"]),
    ("城商行 / 民营银行", [
        "bankofshanghai.com",
        "jsbchina.cn",
        "nbcb.com.cn",
        "hzbank.com.cn",
        "cbhb.com.cn",
        "hfbank.com.cn",
        "webank.com",
        "mybank.cn",
    ]),
    ("银联 / 支付", [
        "unionpay.com",
        "unionpayintl.com",
        "95516.com",
        "alipay.com",
        "alipay.cn",
        "tenpay.com",
    ]),
    ("银行备用域名", [
        "ccb.com.cn",
        "abchina.com.cn",
        "bankofchina.com",
        "bankcomm.com.cn",
        "gdb.com.cn",
        "ecitic.com",
    ]),
]

# Domains that must survive every rebuild; their absence means the upstream
# data is broken and the run must not publish a partial list.
REQUIRED_DOMAINS = [
    "icbc.com.cn",
    "boc.cn",
    "pingan.com.cn",
    "spdb.com.cn",
    "cib.com.cn",
    "cmbc.com.cn",
    "hxb.com.cn",
    "czbank.com",
    "unionpay.com",
    "tenpay.com",
    "ccb.com",
    "abchina.com",
]

HEADER = [
    "# 银行直连规则 - 整合版（所有主流银行，一个文件）",
    "# 来源：LM-Firefly/Rules 各银行 .list + v2fly category-bank-cn + 已验证的补充域名",
    "# 用法：在 Egern 配置 rules 里加一条 rule_set 指向它，policy 填 DIRECT，放在 Reject 之后、Proxy_Rule 之前",
    "# 银行域名极少变动，这个文件基本不用维护",
]


class UpdateError(ValueError):
    """Upstream download or content is unsafe to publish."""


def to_ascii(domain: str) -> str:
    """Lowercase a domain and convert non-ASCII labels to punycode."""
    domain = domain.strip().lower()
    if not domain:
        return ""
    try:
        return ".".join(label.encode("idna").decode("ascii") for label in domain.split("."))
    except UnicodeError:
        return domain


def is_domain(value: str) -> bool:
    """A usable suffix entry: ASCII, has at least one dot, sane characters."""
    return bool(re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", value))


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "BankListSync/1.0",
        "Accept": "text/plain, application/octet-stream;q=0.9, */*;q=0.5",
        "Accept-Encoding": "identity",
    })
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.geturl().split(":", 1)[0].lower() != "https":
                raise UpdateError("Refusing a non-HTTPS final download URL")
            return response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Cannot download {url}; existing list is unchanged: {exc}") from exc


def decode(data: bytes, url: str) -> str:
    if not data or len(data) > MAX_BYTES:
        raise UpdateError(f"Upstream is empty or exceeds the 5 MiB safety limit: {url}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpdateError(f"Upstream is not valid UTF-8: {url}") from exc
    if "\x00" in text or re.search(r"(?is)^\s*(?:<!doctype\s+html|<html\b)", text):
        raise UpdateError(f"Upstream looks like HTML or binary data, not a rule list: {url}")
    return text


def parse_lm_firefly(text: str, name: str) -> list[str]:
    domains = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("DOMAIN-SUFFIX,"):
            domains.append(to_ascii(line.split(",", 1)[1]))
    if not domains:
        raise UpdateError(f"Upstream list yielded no domains: {name}")
    return domains


def parse_v2fly(text: str) -> list[str]:
    domains = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("include:"):
            continue
        if line.startswith(("full:", "domain:")):
            line = line.split(":", 1)[1]
        if line.startswith(("keyword:", "regexp:", "geosite:", "ext:")):
            continue
        domains.append(to_ascii(line))
    if not domains:
        raise UpdateError("Upstream v2fly bank list yielded no domains")
    return domains


def collect(source_dir: Path | None) -> tuple[list[tuple[str, list[str]]], dict[str, str]]:
    """Return grouped domains and the SHA-256 of every upstream source."""
    groups: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    hashes: dict[str, str] = {}
    dropped = 0

    def add(group: str, domain: str) -> None:
        nonlocal dropped
        domain = to_ascii(domain)
        if not is_domain(domain):
            dropped += 1
            return
        if domain in seen:
            return
        seen.add(domain)
        for name, items in groups:
            if name == group:
                items.append(domain)
                return
        groups.append((group, [domain]))

    def load(url: str, name: str) -> str:
        if source_dir is not None:
            data = (source_dir / name).read_bytes()
        else:
            data = fetch(url)
        hashes[name] = hashlib.sha256(data).hexdigest()
        return decode(data, url)

    for code, group in BANKS:
        name = f"{code}.list"
        text = load(LM_FIREFLY_BASE + name, name)
        for domain in parse_lm_firefly(text, name):
            add(group, domain)

    v2fly_text = load(V2FLY_BANK_CN, "category-bank-cn")
    for domain in parse_v2fly(v2fly_text):
        add("其他银行（v2fly）", domain)

    for group, domains in EXTRAS:
        for domain in domains:
            add(group, domain)

    total = sum(len(items) for _, items in groups)
    if total < MIN_TOTAL or total > MAX_TOTAL:
        raise UpdateError(f"Implausible total {total}; expected {MIN_TOTAL}-{MAX_TOTAL}")
    missing = [d for d in REQUIRED_DOMAINS if d not in seen]
    if missing:
        raise UpdateError(f"Required domains missing, upstream data is broken: {missing}")
    print(f"Dropped {dropped} bare entries without a dot.")
    return groups, hashes


def render(groups: list[tuple[str, list[str]]]) -> bytes:
    lines = list(HEADER) + [""]
    for group, domains in groups:
        lines.append(f"# {group}")
        lines.extend(f"DOMAIN-SUFFIX,{d}" for d in sorted(domains))
        lines.append("")
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")


def update(source_dir: Path | None = None, target: Path = TARGET) -> bool:
    groups, hashes = collect(source_dir)
    result = render(groups)
    for name, digest in hashes.items():
        print(f"Upstream SHA-256 {name}: {digest}")
    total = sum(len(items) for _, items in groups)
    print(f"Total unique domains: {total}")
    if target.exists() and target.read_bytes() == result:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".bank-", delete=False) as handle:
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
    parser.add_argument("--source-dir", type=Path, help="Use local source files for offline validation")
    parser.add_argument("--target", type=Path, default=TARGET, help="Output path (default: rules/bank_direct_all.list)")
    args = parser.parse_args()
    try:
        changed = update(args.source_dir, args.target)
    except (UpdateError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Updated bank list." if changed else "No upstream change; no file written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
