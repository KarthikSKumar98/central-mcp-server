"""Extract a single version's entry from CHANGELOG.md for use as GitHub Release notes.

Usage:
    python3 extract_changelog_entry.py --version 0.2.0 --file CHANGELOG.md
    # Prints the entry content to stdout
"""

import argparse
import sys


def extract_entry(content: str, version: str) -> str:
    """Extract the changelog section for the given version."""
    header = f"## [{version}]"
    start = content.find(header)
    if start == -1:
        return ""

    # Find the next version header (or end of file)
    next_header = content.find("\n## [", start + 1)
    if next_header == -1:
        entry = content[start:]
    else:
        entry = content[start:next_header]

    # Strip the version header line itself — GitHub Release title already shows the version
    lines = entry.splitlines()
    body_lines = lines[1:]  # drop "## [version] - date"

    # Strip leading/trailing blank lines from body
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    return "\n".join(body_lines)


def main() -> None:
    """Parse arguments, extract changelog entry, and print to stdout."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="Version to extract (e.g. 0.2.0)")
    parser.add_argument("--file", required=True, help="Path to CHANGELOG.md")
    args = parser.parse_args()

    with open(args.file) as f:
        content = f.read()

    entry = extract_entry(content, args.version)
    if not entry:
        print(f"No changelog entry found for version {args.version}", file=sys.stderr)
        sys.exit(1)

    print(entry)


if __name__ == "__main__":
    main()
