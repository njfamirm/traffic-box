"""Subscription management module."""

import base64
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from traffic_box.generator import build_auto_config, build_single_node_config
from traffic_box.parser import parse_uri, sanitize_filename

DEFAULT_SUB_URL = os.environ.get("TRAFFIC_BOX_SUB_URL", "")


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def get_profiles_dir() -> Path:
    env_dir = os.environ.get("TRAFFIC_BOX_PROFILES_DIR")
    if env_dir:
        p = Path(env_dir)
    else:
        p = get_project_root() / "profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_sub_url_file() -> Path:
    return get_project_root() / "sub_url.txt"


def fetch_subscription_content(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "v2rayN/6.23 traffic-box/0.1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8").strip()

    try:
        return base64.b64decode(content).decode("utf-8")
    except Exception:
        return content


def validate_config(cfg: dict) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["sing-box", "check", "-c", "/dev/stdin"],
            input=json.dumps(cfg),
            text=True,
            capture_output=True,
        )
        return p.returncode == 0, p.stderr
    except FileNotFoundError:
        return True, "sing-box binary not found"


def update_subscription(url: str = None, log_fn=print) -> list[Path]:
    sub_file = get_sub_url_file()
    if not url:
        if sub_file.exists():
            url = sub_file.read_text().strip()
        else:
            url = DEFAULT_SUB_URL

    if not url:
        log_fn("Error: No subscription URL configured. Please specify a URL.")
        return []

    sub_file.write_text(url)
    log_fn(f"Fetching subscription: {url}")

    raw = fetch_subscription_content(url)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]

    parsed_nodes = []
    for line in lines:
        parsed = parse_uri(line)
        if parsed:
            parsed_nodes.append(parsed)

    if not parsed_nodes:
        log_fn("No supported nodes found in subscription!")
        return []

    log_fn(f"Found {len(parsed_nodes)} nodes:")
    for name, ob in parsed_nodes:
        log_fn(f"  • {name} ({ob['server']}:{ob['server_port']})")

    profiles_dir = get_profiles_dir()

    # Clean up old generated numbered profiles to prevent stale configs
    for old_file in profiles_dir.glob("*.json"):
        if re.match(r"^\d\d-", old_file.name):
            try:
                old_file.unlink()
            except OSError:
                pass

    saved_paths = []

    # 1. Combined Auto / Failover profile
    auto_cfg = build_auto_config(parsed_nodes)
    valid, err = validate_config(auto_cfg)
    if not valid:
        log_fn(f"Warning: Auto config validation error: {err}")
    auto_file = profiles_dir / "00-auto.json"
    auto_file.write_text(json.dumps(auto_cfg, indent=2, ensure_ascii=False))
    saved_paths.append(auto_file)
    log_fn(f"Saved: {auto_file.name}")

    # 2. Individual node profiles
    for i, (name, ob) in enumerate(parsed_nodes, 1):
        clean_name = f"{i:02d}-{sanitize_filename(name)}.json"
        node_file = profiles_dir / clean_name
        node_cfg = build_single_node_config(ob)
        valid, err = validate_config(node_cfg)
        if not valid:
            log_fn(f"Warning: {clean_name} validation error: {err}")
        node_file.write_text(json.dumps(node_cfg, indent=2, ensure_ascii=False))
        saved_paths.append(node_file)
        log_fn(f"Saved: {clean_name}")

    log_fn(f"Subscription update completed: {len(saved_paths)} profiles generated.")
    return saved_paths
