# 🚦 Traffic-Box

> **Transparent policy-based routing engine, subscription manager, and GTK4 GUI launcher for sing-box.**

---

## 🌟 Key Features

- **Policy-Based Traffic Routing**:
  - Automatic bypass for Iranian websites (`.ir` and `geosite-ir`).
  - Direct DNS resolution & DNS hijacking for zero leaks.
  - Automatic TUN interface routing (`sing-tun`).
- **Subscription Management (`traffic-box sub`)**:
  - Parses VLESS Reality (TCP), WebSocket, XHTTP / HTTPUpgrade, gRPC.
  - Automatically builds single-node profiles and a combined `00-auto.json` with auto latency testing (`urltest`) and failover.
  - Keeps credentials and subscription cache strictly out of Git (`.gitignore`).
- **Modern GTK4 GUI Launcher (`traffic-box gui`)**:
  - Profile switcher dropdown.
  - One-click **Update Sub** button.
  - Real-time sing-box logs streaming.
  - Passwordless execution via Polkit rules.

---

## 📁 Architecture & Directory Layout

```
traffic-box/
├── config/
│   └── rules.json         # Routing rules, direct domains, DNS servers
├── polkit/
│   └── 49-traffic-box.rules # Polkit policy for rootless prompt
├── profiles/              # Generated sing-box configs (Ignored in Git)
│   ├── 00-auto.json       # Auto-failover & latency testing
│   ├── 01-us-reality.json
│   └── ...
├── scripts/
│   ├── setup.sh           # Installation script
│   └── singbox-stop       # Process terminator helper
├── src/
│   └── traffic_box/
│       ├── cli.py         # CLI entry point
│       ├── generator.py   # Config generator
│       ├── gui.py         # GTK4 user interface
│       ├── parser.py      # Protocol link parser
│       ├── routing.py     # Base routing and DNS rules
│       └── sub.py         # Subscription updater
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 🚀 Quick Start

### 1. Installation
```bash
./scripts/setup.sh
```

### 2. Update Subscription
```bash
traffic-box sub "https://your-subscription-link..."
# or just run:
traffic-box sub
```

### 3. Launch UI
```bash
traffic-box gui
```
