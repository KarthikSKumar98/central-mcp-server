"""Generate a CHANGELOG.md entry from a list of merged PRs.

Usage:
    python3 generate_changelog.py --prs merged_prs.json --version 0.2.0 --output CHANGELOG.md
"""

import argparse
import json
import sys
from datetime import date, timezone

PREFIX_TO_SECTION = {
    "tool:": "New Tools",
    "feat:": "Features",
    "fix:": "Bug Fixes",
    "refactor:": "Refactoring",
    "docs:": "Documentation",
    "ci:": "Maintenance",
    "chore:": "Maintenance",
    "test:": "Maintenance",
}

SECTION_ORDER = [
    "New Tools",
    "Features",
    "Bug Fixes",
    "Refactoring",
    "Documentation",
    "Maintenance",
    "Other",
]

CHANGELOG_HEADER = """# Changelog

All notable changes to this project will be documented in this file.

"""


def categorize_pr(title: str) -> tuple[str, str]:
    """Return (section, stripped_title) for a PR title."""
    for prefix, section in PREFIX_TO_SECTION.items():
        if title.lower().startswith(prefix):
            stripped = title[len(prefix):].strip()
            # Capitalize first letter
            stripped = stripped[0].upper() + stripped[1:] if stripped else stripped
            return section, stripped
    return "Other", title.strip()


def generate_entry(prs: list[dict], version: str) -> str:
    """Generate a single changelog section for the given version."""
    today = date.today().isoformat()
    sections: dict[str, list[str]] = {s: [] for s in SECTION_ORDER}

    for pr in prs:
        number = pr["number"]
        title = pr["title"]
        section, stripped = categorize_pr(title)
        sections[section].append(f"- {stripped} (#{number})")

    lines = [f"## [{version}] - {today}\n"]
    for section in SECTION_ORDER:
        entries = sections[section]
        if entries:
            lines.append(f"\n### {section}\n")
            lines.extend(entries)

    return "\n".join(lines) + "\n"


def load_existing_changelog(path: str) -> str:
    """Load existing changelog content, stripping the header if present."""
    try:
        with open(path) as f:
            content = f.read()
        # Strip the standard header so we can prepend the new entry
        if content.startswith("# Changelog"):
            # Find the first version entry
            idx = content.find("\n## [")
            if idx != -1:
                return content[idx + 1:]  # keep from "## [" onwards
            return ""
        return content
    except FileNotFoundError:
        return ""


def main() -> None:
    """Parse arguments, generate changelog entry, and write to file."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--prs", required=True, help="Path to merged_prs.json")
    parser.add_argument("--version", required=True, help="Release version (e.g. 0.2.0)")
    parser.add_argument("--output", required=True, help="Path to CHANGELOG.md")
    args = parser.parse_args()

    with open(args.prs) as f:
        prs = json.load(f)

    if not prs:
        print("No PRs found since last release — skipping changelog generation.", file=sys.stderr)
        sys.exit(1)

    new_entry = generate_entry(prs, args.version)
    existing = load_existing_changelog(args.output)

    with open(args.output, "w") as f:
        f.write(CHANGELOG_HEADER)
        f.write(new_entry)
        if existing:
            f.write("\n")
            f.write(existing)

    print(f"CHANGELOG.md updated with entry for v{args.version}")


if __name__ == "__main__":
    main()
