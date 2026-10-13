#!/usr/bin/env python3
"""Search apibay.org, inspect torrent entries, and create magnet links."""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://apibay.org"
TIMEOUT_SECONDS = 15


class ApiError(Exception):
    """An API request or response could not be handled."""


def fetch_json(endpoint, **params):
    query = urlencode(params)
    url = f"{API_BASE}/{endpoint}?{query}"
    request = Request(url, headers={"User-Agent": "apibay-cli/1.0"})

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except HTTPError as exc:
        raise ApiError(f"API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ApiError(f"could not reach apibay.org: {reason}") from exc

    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiError("API returned invalid JSON") from exc


def format_size(value):
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "unknown"

    if size < 0:
        return "unknown"

    for unit, divisor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= divisor or unit == "KB":
            return f"{size / divisor:.2f} {unit}"
    return "unknown"


def format_added(value):
    try:
        timestamp = int(value)
        return datetime.fromtimestamp(timestamp).strftime("%d/%m/%y")
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown"


def sanitize_terminal_text(value, multiline=False):
    text = str(value)
    cleaned = []

    def skip_csi(index):
        while index < len(text):
            code = ord(text[index])
            index += 1
            if 0x40 <= code <= 0x7E:
                break
        return index

    def skip_string_control(index, allow_bel=False):
        while index < len(text):
            if allow_bel and text[index] == "\x07":
                return index + 1
            if text[index] == "\x1b" and index + 1 < len(text) and text[index + 1] == "\\":
                return index + 2
            if ord(text[index]) == 0x9C:
                return index + 1
            index += 1
        return index

    index = 0
    while index < len(text):
        char = text[index]
        code = ord(char)

        if char == "\x1b":
            if index + 1 >= len(text):
                break
            introducer = text[index + 1]
            if introducer == "[":
                index = skip_csi(index + 2)
            elif introducer == "]":
                index = skip_string_control(index + 2, allow_bel=True)
            elif introducer in "PX^_":
                index = skip_string_control(index + 2)
            else:
                index += 1
                while index < len(text) and 0x20 <= ord(text[index]) <= 0x2F:
                    index += 1
                if index < len(text) and 0x30 <= ord(text[index]) <= 0x7E:
                    index += 1
            continue

        if code == 0x9B:
            index = skip_csi(index + 1)
            continue
        if code == 0x9D:
            index = skip_string_control(index + 1, allow_bel=True)
            continue
        if code in (0x90, 0x98, 0x9E, 0x9F):
            index = skip_string_control(index + 1)
            continue

        if char == "\n":
            cleaned.append(char if multiline else " ")
        elif char == "\r":
            if index + 1 >= len(text) or text[index + 1] != "\n":
                cleaned.append(" ")
        elif char == "\t":
            cleaned.append(" ")
        elif code < 0x20 or 0x7F <= code <= 0x9F:
            pass
        else:
            cleaned.append(char)
        index += 1

    return "".join(cleaned)


def colourize(value, code):
    text = sanitize_terminal_text(value)
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
        return text
    return f"\033[{code}m{text}\033[0m"


def format_uploader(entry):
    username = sanitize_terminal_text(entry.get("username") or "").strip()
    return username or "-"


def column_widths(entries, include_uploader=False):
    ids = [sanitize_terminal_text(entry.get("id", "unknown")) for entry in entries]
    sizes = [format_size(entry.get("size")) for entry in entries]
    swarms = [
        "{}/{}".format(
            sanitize_terminal_text(entry.get("seeders", "0")),
            sanitize_terminal_text(entry.get("leechers", "0")),
        )
        for entry in entries
    ]
    widths = {
        "id": max((len(value) for value in ids), default=0),
        "size": max((len(value) for value in sizes), default=0),
        "swarm": max((len(value) for value in swarms), default=0),
    }
    if include_uploader:
        uploaders = [format_uploader(entry) for entry in entries]
        widths["uploader"] = max((len(value) for value in uploaders), default=0)
    return widths


def entry_line(entry, widths=None, include_uploader=False):
    if widths is None:
        widths = column_widths([entry], include_uploader=include_uploader)

    raw_id = sanitize_terminal_text(entry.get("id", "unknown"))
    raw_size = format_size(entry.get("size"))
    raw_seeders = sanitize_terminal_text(entry.get("seeders", "0"))
    raw_leechers = sanitize_terminal_text(entry.get("leechers", "0"))
    swarm_text = f"{raw_seeders}/{raw_leechers}"

    entry_id = colourize(f"{raw_id:>{widths['id']}}", "36;1")
    size = colourize(f"{raw_size:>{widths['size']}}", "33")
    swarm_padding = " " * max(0, widths["swarm"] - len(swarm_text))
    swarm = swarm_padding + colourize(raw_seeders, "32")
    swarm += colourize("/", "2") + colourize(raw_leechers, "31")
    added = colourize(format_added(entry.get("added")), "2")
    name = colourize(entry.get("name", "(unnamed)"), "1")
    line = f"{entry_id} {size} {swarm} {added} {name}"
    if include_uploader:
        uploader = format_uploader(entry)
        uploader = colourize(f"{uploader:>{widths['uploader']}}", "35")
        line += f" {uploader}"
    return line


def is_missing_entry(entry):
    entry_id = str(entry.get("id", ""))
    name = str(entry.get("name", "")).strip().lower()
    return entry_id == "0" or name == "no results found"


def normalize_entry(payload):
    if isinstance(payload, list):
        if not payload:
            return None
        payload = payload[0]
    if not isinstance(payload, dict) or is_missing_entry(payload):
        return None
    return payload


def search(query, columns=None):
    payload = fetch_json("q.php", q=query)
    if isinstance(payload, dict):
        entries = [payload]
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ApiError("search response had an unexpected format")

    entries = [entry for entry in entries if isinstance(entry, dict) and not is_missing_entry(entry)]
    if not entries:
        print("No results found.")
        return

    include_uploader = columns == "uploader"
    widths = column_widths(entries, include_uploader=include_uploader)
    for entry in entries:
        print(entry_line(entry, widths=widths, include_uploader=include_uploader))


def normalize_files(payload):
    if isinstance(payload, dict):
        files = payload.get("files")
        if isinstance(files, list):
            payload = files
        else:
            names = payload.get("name")
            sizes = payload.get("size")
            if isinstance(names, list) and isinstance(sizes, list):
                count = max(len(names), len(sizes))
                payload = [
                    {
                        "name": names[index] if index < len(names) else "(unnamed)",
                        "size": sizes[index] if index < len(sizes) else None,
                    }
                    for index in range(count)
                ]

    if not isinstance(payload, list):
        raise ApiError("file response had an unexpected format")

    def unwrap(value):
        while isinstance(value, list) and len(value) == 1:
            value = value[0]
        return value

    files = []
    for item in payload:
        if isinstance(item, dict):
            files.append({
                "name": unwrap(item.get("name", "(unnamed)")),
                "size": unwrap(item.get("size")),
            })
    return files


def details(entry_id):
    entry = normalize_entry(fetch_json("t.php", id=entry_id))
    if entry is None:
        raise ApiError(f"no entry found for ID {entry_id}")

    print(entry_line(entry))

    print(colourize("Uploaded by:", "36;1"), colourize(format_uploader(entry), "1"))

    print(colourize("Description:", "36;1"))
    description = entry.get("description") or entry.get("descr")
    print(sanitize_terminal_text(description, multiline=True) if description else "No description available.")
    print(colourize("Files:", "36;1"))

    files = normalize_files(fetch_json("f.php", id=entry_id))
    if not files:
        print("  No files listed.")
        return

    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        name = colourize(file_info.get("name", "(unnamed)"), "1")
        size = colourize(format_size(file_info.get("size")), "33")
        print(f"\t{name}\t{size}")


def magnet(entry_id):
    entry = normalize_entry(fetch_json("t.php", id=entry_id))
    if entry is None:
        raise ApiError(f"no entry found for ID {entry_id}")

    info_hash = str(entry.get("info_hash", "")).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", info_hash):
        raise ApiError(f"entry {entry_id} did not include a valid 40-character info hash")

    print(f"magnet:?xt=urn:btih:{info_hash.upper()}")


def parse_id(value):
    try:
        entry_id = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ID must be an integer") from exc
    if entry_id <= 0:
        raise argparse.ArgumentTypeError("ID must be a positive integer")
    return entry_id


def build_parser():
    parser = argparse.ArgumentParser(description="Search apibay.org and create magnet links.")
    commands = parser.add_subparsers(dest="command", required=True)

    search_parser = commands.add_parser("search", help="search for entries")
    search_parser.add_argument(
        "--columns",
        choices=("uploader",),
        help="add an optional search column",
    )
    search_parser.add_argument("query", nargs="+", help="search terms")

    details_parser = commands.add_parser("details", help="show entry details and files")
    details_parser.add_argument("id", type=parse_id, help="entry ID")

    magnet_parser = commands.add_parser("magnet", help="print an entry's magnet link")
    magnet_parser.add_argument("id", type=parse_id, help="entry ID")

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "search":
            search(" ".join(args.query), columns=args.columns)
        elif args.command == "details":
            details(args.id)
        else:
            magnet(args.id)
    except ApiError as exc:
        print(f"apibay: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
