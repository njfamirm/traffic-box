"""Protocol parsers for VLESS, VMess, Shadowsocks, Trojan."""

import base64
import json
import re
import urllib.parse


def sanitize_filename(name: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", name).strip().lower()
    clean = re.sub(r"[-\s]+", "-", clean)
    return clean or "node"


def parse_vless(uri: str) -> tuple[str, dict]:
    p = urllib.parse.urlparse(uri)
    raw_name = urllib.parse.unquote(p.fragment) if p.fragment else p.hostname
    user_info = p.netloc.split("@")[0]
    host_port = p.netloc.split("@")[1]
    host, port = host_port.split(":")
    port = int(port)
    qs = {k: v[0] for k, v in urllib.parse.parse_qs(p.query).items()}

    tag = raw_name.strip()
    outbound = {
        "type": "vless",
        "tag": tag,
        "server": host,
        "server_port": port,
        "uuid": user_info,
    }

    net_type = qs.get("type", "tcp")
    if net_type == "ws":
        outbound["transport"] = {
            "type": "ws",
            "path": qs.get("path", "/"),
            "headers": {"Host": qs.get("host", host)},
        }
    elif net_type in ("http", "httpupgrade", "xhttp"):
        t_type = "httpupgrade" if net_type in ("httpupgrade", "xhttp") else "http"
        outbound["transport"] = {
            "type": t_type,
            "path": qs.get("path", "/"),
            "host": qs.get("host", host),
        }
    elif net_type == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": qs.get("serviceName", ""),
        }

    sec = qs.get("security", "")
    if sec == "reality":
        outbound["tls"] = {
            "enabled": True,
            "server_name": qs.get("sni") or qs.get("host", host),
            "utls": {
                "enabled": True,
                "fingerprint": qs.get("fp", "ios"),
            },
            "reality": {
                "enabled": True,
                "public_key": qs.get("pbk", ""),
            },
        }
        if qs.get("sid"):
            outbound["tls"]["reality"]["short_id"] = qs["sid"]
    elif sec == "tls":
        outbound["tls"] = {
            "enabled": True,
            "server_name": qs.get("sni") or qs.get("host", host),
            "utls": {
                "enabled": True,
                "fingerprint": qs.get("fp", "chrome"),
            },
        }
        if qs.get("alpn"):
            outbound["tls"]["alpn"] = [x.strip() for x in qs["alpn"].split(",")]

    return raw_name, outbound


def parse_uri(uri: str) -> tuple[str, dict] | None:
    uri = uri.strip()
    if uri.startswith("vless://"):
        return parse_vless(uri)
    return None
