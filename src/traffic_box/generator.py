"""Sing-box configuration generator."""

import copy
from traffic_box.routing import build_base_config


def build_single_node_config(outbound: dict, rules: dict = None) -> dict:
    cfg = build_base_config(rules)
    proxy_ob = copy.deepcopy(outbound)
    proxy_ob["tag"] = "proxy"
    cfg["outbounds"] = [
        proxy_ob,
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"},
    ]
    # filter None in rules
    cfg["route"]["rules"] = [r for r in cfg["route"]["rules"] if r is not None]
    return cfg


def build_auto_config(parsed_nodes: list[tuple[str, dict]], rules: dict = None) -> dict:
    cfg = build_base_config(rules)
    node_tags = [ob["tag"] for _, ob in parsed_nodes]
    outbounds = [
        {
            "type": "selector",
            "tag": "proxy",
            "outbounds": ["auto"] + node_tags,
            "default": "auto",
        },
        {
            "type": "urltest",
            "tag": "auto",
            "outbounds": node_tags,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "3m",
            "tolerance": 50,
        },
    ]
    for _, ob in parsed_nodes:
        outbounds.append(copy.deepcopy(ob))
    outbounds.append({"type": "direct", "tag": "direct"})
    outbounds.append({"type": "block", "tag": "block"})
    cfg["outbounds"] = outbounds
    cfg["route"]["rules"] = [r for r in cfg["route"]["rules"] if r is not None]
    return cfg
