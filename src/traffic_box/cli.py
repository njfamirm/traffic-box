"""Command-line interface for traffic-box."""

import argparse
import sys
from traffic_box.gui import main as gui_main
from traffic_box.sub import update_subscription


def main():
    parser = argparse.ArgumentParser(
        prog="traffic-box",
        description="Traffic-Box: Policy-based routing manager and sing-box GUI launcher",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # GUI
    subparsers.add_parser("gui", help="Launch the GTK4 GUI")

    # Sub update
    sub_parser = subparsers.add_parser("sub", help="Fetch subscription and generate profiles")
    sub_parser.add_argument("url", nargs="?", default=None, help="Subscription URL (optional)")

    args = parser.parse_args()

    if args.command == "gui" or args.command is None:
        gui_main()
    elif args.command == "sub":
        update_subscription(args.url)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
