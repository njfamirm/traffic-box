"""Routing rules and DNS templates for sing-box."""

import json
from pathlib import Path

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "rules.json"


def load_rules_config(path: Path = None) -> dict:
    target = path or DEFAULT_RULES_PATH
    if target.exists():
        try:
            return json.loads(target.read_text())
        except Exception:
            pass
    return {
        "log_level": "warn",
        "dns": {
            "direct_servers": [
                {"tag": "dns-direct", "server": "1.1.1.1"},
                {"tag": "dns-direct-google", "server": "8.8.8.8"},
                {"tag": "dns-cloudflare-ip", "server": "104.16.249.249"},
            ],
            "final_dns": "dns-direct-google",
            "strategy": "prefer_ipv4",
        },
        "tun": {
            "interface_name": "sing-tun",
            "inet4_address": "172.19.0.1/30",
            "auto_route": True,
            "strict_route": True,
        },
        "routing": {
            "direct_domain_suffixes": [
                ".ir",
                "soffit.co",
                "mynexim.ir",
                "stone-scoop.ir",
                "mahakacc.mahaksoft.com",
                "swissplus.co",
                "kavenegar.com",
                "github.com",
                "githubusercontent.com",
            ],
            "direct_ip_cidrs": [
                "195.88.208.203/32"
            ],
            "rule_sets": [
                {
                    "tag": "geosite-ir",
                    "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ir.srs",
                }
            ],
        },
    }


def build_base_config(rules: dict = None) -> dict:
    r = rules or load_rules_config()
    
    dns_servers = []
    for s in r.get("dns", {}).get("direct_servers", []):
        dns_servers.append({
            "type": "udp",
            "tag": s["tag"],
            "server": s["server"],
        })

    direct_suffixes = r.get("routing", {}).get("direct_domain_suffixes", [])
    rule_sets = r.get("routing", {}).get("rule_sets", [])
    direct_cidrs = r.get("routing", {}).get("direct_ip_cidrs", [])

    return {
        "log": {
            "level": r.get("log_level", "warn"),
        },
        "dns": {
            "servers": dns_servers,
            "rules": [
                {
                    "domain_suffix": direct_suffixes,
                    "server": "dns-direct",
                },
                {
                    "rule_set": [rs["tag"] for rs in rule_sets],
                    "server": "dns-direct",
                },
            ],
            "final": r.get("dns", {}).get("final_dns", "dns-direct-google"),
            "strategy": r.get("dns", {}).get("strategy", "prefer_ipv4"),
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": r.get("tun", {}).get("interface_name", "sing-tun"),
                "address": [r.get("tun", {}).get("inet4_address", "172.19.0.1/30")],
                "auto_route": r.get("tun", {}).get("auto_route", True),
                "strict_route": r.get("tun", {}).get("strict_route", True),
            }
        ],
        "route": {
            "rule_set": [
                {
                    "tag": rs["tag"],
                    "type": "remote",
                    "format": "binary",
                    "url": rs["url"],
                    "download_detour": "direct",
                }
                for rs in rule_sets
            ],
            "rules": [
                {"inbound": "tun-in", "action": "sniff"},
                {"protocol": "dns", "action": "hijack-dns"},
                {"domain_suffix": direct_suffixes, "outbound": "direct"},
                {"ip_cidr": direct_cidrs, "outbound": "direct"} if direct_cidrs else None,
                {"rule_set": [rs["tag"] for rs in rule_sets], "outbound": "direct"},
            ],
            "final": "proxy",
            "auto_detect_interface": True,
            "default_domain_resolver": "dns-direct",
        },
    }
