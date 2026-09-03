#!/usr/bin/env python3
"""
json2md.py

Convert arbitrary JSON into LLM/RAG-friendly Markdown.

Design goals:
- Preserve source values exactly
- Make JSON hierarchy explicit
- Keep records independently retrievable
- Preserve JSON paths for verification
- Avoid Markdown tables
- Avoid generated/interpretive descriptions
- Handle arbitrary JSON structures
- Produce deterministic output
- Provide size/token estimates
- Optionally include/exclude JSON paths
- Sensibly identify records inside arrays
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_HEADING_DEPTH = 6

# Fields commonly useful as human-readable record identifiers.
IDENTIFIER_FIELDS = (
    "name",
    "title",
    "id",
    "slug",
    "key",
    "uuid",
    "uid",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_scalar(value: Any) -> str:
    """
    Convert a JSON scalar into Markdown-safe text.

    Important:
    We do not interpret or modify the actual value.
    """

    if value is None:
        return "null"

    if value is True:
        return "true"

    if value is False:
        return "false"

    if isinstance(value, (int, float)):
        return str(value)

    if isinstance(value, str):
        return value

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def safe_heading(value: str) -> str:
    """
    Make a value safe to use as a Markdown heading without
    changing the underlying source value.
    """

    value = str(value).strip()

    if not value:
        return "(empty)"

    # Prevent accidental Markdown heading injection.
    value = re.sub(r"^#+\s*", "", value)

    return value


def scalar_preview(value: Any, max_length: int = 80) -> str:
    """
    Create a short preview for record headings.

    This is presentation-only; source values remain unchanged below.
    """

    text = format_scalar(value)

    text = text.replace("\n", " ")

    if len(text) > max_length:
        return text[:max_length - 3] + "..."

    return text


def find_identifier(obj: dict[str, Any]) -> tuple[str, Any] | None:
    """
    Find a useful human-readable identifier for an object.
    """

    for field in IDENTIFIER_FIELDS:
        if field in obj:
            value = obj[field]

            if not isinstance(value, (dict, list)):
                return field, value

    return None


def is_scalar(value: Any) -> bool:
    return not isinstance(value, (dict, list))


def is_array_of_objects(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, dict) for item in value)
    )


def is_object_of_objects(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and len(value) > 0
        and all(isinstance(item, dict) for item in value.values())
    )


def json_path_property(path: str, key: str) -> str:
    """
    Build a readable JSON path.

    Uses dot notation for normal keys and bracket notation
    for unusual keys.
    """

    if not path:
        return key

    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return f"{path}.{key}"

    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'{path}["{escaped}"]'


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class MarkdownRenderer:
    def __init__(
        self,
        *,
        include_paths: bool = True,
        max_heading_depth: int = DEFAULT_MAX_HEADING_DEPTH,
    ):
        self.include_paths = include_paths
        self.max_heading_depth = max_heading_depth

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def render(self, data: Any) -> str:
        lines: list[str] = []

        lines.extend(self.render_root(data))

        return "\n".join(lines).rstrip() + "\n"

    # -----------------------------------------------------------------------
    # Root
    # -----------------------------------------------------------------------

    def render_root(self, data: Any) -> list[str]:
        lines: list[str] = []

        if isinstance(data, dict):
            lines.extend(
                self.render_object(
                    data,
                    path="$",
                    heading_level=2,
                    root=True,
                )
            )

        elif isinstance(data, list):
            lines.extend(
                self.render_array(
                    data,
                    path="$",
                    heading_level=2,
                    root=True,
                )
            )

        else:
            lines.append("## Value")
            lines.append("")
            lines.append(f"**JSON Path:** `$`")
            lines.append("")
            lines.append(format_scalar(data))
            lines.append("")

        return lines

    # -----------------------------------------------------------------------
    # Objects
    # -----------------------------------------------------------------------

    def render_object(
        self,
        obj: dict[str, Any],
        *,
        path: str,
        heading_level: int,
        root: bool = False,
    ) -> list[str]:

        lines: list[str] = []

        # Scalars first.
        #
        # This is intentional:
        # Important identifying fields become immediately visible
        # when an LLM retrieves a chunk.
        scalar_fields = [
            (key, value)
            for key, value in obj.items()
            if is_scalar(value)
        ]

        complex_fields = [
            (key, value)
            for key, value in obj.items()
            if not is_scalar(value)
        ]

        for key, value in scalar_fields:
            lines.append(
                f"- **{key}:** {format_scalar(value)}"
            )

        if scalar_fields and complex_fields:
            lines.append("")

        # Nested values.
        for key, value in complex_fields:
            child_path = json_path_property(path, key)

            lines.extend(
                self.render_field(
                    key,
                    value,
                    path=child_path,
                    heading_level=heading_level,
                )
            )

        return lines

    # -----------------------------------------------------------------------
    # Fields
    # -----------------------------------------------------------------------

    def render_field(
        self,
        key: str,
        value: Any,
        *,
        path: str,
        heading_level: int,
    ) -> list[str]:

        lines: list[str] = []

        level = min(
            heading_level + 1,
            self.max_heading_depth,
        )

        heading = "#" * level

        if isinstance(value, dict):
            lines.append(f"{heading} {safe_heading(key)}")
            lines.append("")

            if self.include_paths:
                lines.append(f"**JSON Path:** `{path}`")
                lines.append("")

            lines.extend(
                self.render_object(
                    value,
                    path=path,
                    heading_level=level,
                )
            )

            lines.append("")

        elif isinstance(value, list):
            lines.append(f"{heading} {safe_heading(key)}")
            lines.append("")

            if self.include_paths:
                lines.append(f"**JSON Path:** `{path}`")
                lines.append("")

            lines.extend(
                self.render_array(
                    value,
                    path=path,
                    heading_level=level,
                )
            )

            lines.append("")

        return lines

    # -----------------------------------------------------------------------
    # Arrays
    # -----------------------------------------------------------------------

    def render_array(
        self,
        array: list[Any],
        *,
        path: str,
        heading_level: int,
        root: bool = False,
    ) -> list[str]:

        lines: list[str] = []

        if not array:
            lines.append("_Empty array._")
            return lines

        # Array of objects:
        #
        # Treat every object as an independent record.
        #
        # This is particularly important for RAG because it creates
        # natural retrieval boundaries.
        if is_array_of_objects(array):

            for index, item in enumerate(array):
                item_path = f"{path}[{index}]"

                identifier = find_identifier(item)

                if identifier:
                    field, value = identifier
                    title = (
                        f"{field}: "
                        f"{scalar_preview(value)}"
                    )
                else:
                    title = f"Record {index + 1}"

                level = min(
                    heading_level + 1,
                    self.max_heading_depth,
                )

                lines.append(
                    f"{'#' * level} {safe_heading(title)}"
                )
                lines.append("")

                if self.include_paths:
                    lines.append(
                        f"**JSON Path:** `{item_path}`"
                    )
                    lines.append("")

                lines.extend(
                    self.render_object(
                        item,
                        path=item_path,
                        heading_level=level,
                    )
                )

                lines.append("")

            return lines

        # Array containing nested arrays/objects/scalars.
        for index, item in enumerate(array):
            item_path = f"{path}[{index}]"

            if isinstance(item, dict):

                level = min(
                    heading_level + 1,
                    self.max_heading_depth,
                )

                identifier = find_identifier(item)

                if identifier:
                    field, value = identifier
                    title = (
                        f"{field}: "
                        f"{scalar_preview(value)}"
                    )
                else:
                    title = f"Item {index + 1}"

                lines.append(
                    f"{'#' * level} {safe_heading(title)}"
                )
                lines.append("")

                if self.include_paths:
                    lines.append(
                        f"**JSON Path:** `{item_path}`"
                    )
                    lines.append("")

                lines.extend(
                    self.render_object(
                        item,
                        path=item_path,
                        heading_level=level,
                    )
                )

                lines.append("")

            elif isinstance(item, list):

                lines.append(
                    f"- **Item {index + 1}**"
                )

                if self.include_paths:
                    lines.append(
                        f"  - JSON Path: `{item_path}`"
                    )

                lines.extend(
                    self.render_array(
                        item,
                        path=item_path,
                        heading_level=heading_level,
                    )
                )

            else:

                if self.include_paths:
                    lines.append(
                        f"- **Item {index + 1}** "
                        f"(`{item_path}`): "
                        f"{format_scalar(item)}"
                    )
                else:
                    lines.append(
                        f"- {format_scalar(item)}"
                    )

        return lines


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def count_nodes(value: Any) -> int:
    """
    Count every JSON value recursively.
    """

    if isinstance(value, dict):
        return (
            1
            + sum(count_nodes(v) for v in value.values())
        )

    if isinstance(value, list):
        return (
            1
            + sum(count_nodes(v) for v in value)
        )

    return 1


def count_records(value: Any) -> int:
    """
    Approximate number of meaningful records.

    Primarily counts objects inside arrays.
    """

    count = 0

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                count += 1

            count += count_records(item)

    elif isinstance(value, dict):
        for child in value.values():
            count += count_records(child)

    return count


def estimate_tokens(text: str) -> int:
    """
    Rough token estimate.

    This is intentionally conservative and is NOT tokenizer-specific.
    """

    # ~4 characters/token is a useful rough estimate for English text.
    return max(1, (len(text) + 3) // 4)


def collect_stats(
    data: Any,
    markdown: str,
) -> dict[str, Any]:

    if isinstance(data, dict):
        root_type = "object"
        root_entries = len(data)

    elif isinstance(data, list):
        root_type = "array"
        root_entries = len(data)

    else:
        root_type = type(data).__name__
        root_entries = 1

    return {
        "root_type": root_type,
        "root_entries": root_entries,
        "json_nodes": count_nodes(data),
        "records": count_records(data),
        "markdown_characters": len(markdown),
        "markdown_words": len(markdown.split()),
        "estimated_tokens": estimate_tokens(markdown),
        "markdown_bytes": len(markdown.encode("utf-8")),
    }


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def build_header(
    *,
    source_file: Path,
    data: Any,
    markdown: str,
    include_paths: bool,
) -> str:

    stats = collect_stats(data, markdown)

    generated = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    lines = [
        f"# Dataset: {source_file.stem}",
        "",
        "> This document is a deterministic conversion of a JSON dataset "
        "into structured Markdown for LLM/RAG consumption.",
        ">",
        "> Source values are preserved. The converter does not infer, "
        "summarize, classify, or generate factual content.",
        "",
        "## Document Metadata",
        "",
        f"- **Source file:** `{source_file.name}`",
        f"- **Generated:** `{generated}`",
        f"- **Root type:** `{stats['root_type']}`",
        f"- **Top-level entries:** `{stats['root_entries']}`",
        f"- **JSON nodes:** `{stats['json_nodes']:,}`",
        f"- **Records:** `{stats['records']:,}`",
        f"- **Markdown characters:** `{stats['markdown_characters']:,}`",
        f"- **Markdown words:** `{stats['markdown_words']:,}`",
        f"- **Estimated tokens:** `{stats['estimated_tokens']:,}`",
        f"- **Markdown size:** "
        f"`{stats['markdown_bytes'] / 1024 / 1024:.2f} MiB`",
        "",
        "## Reading Rules",
        "",
        "- Treat the source data as authoritative for this dataset.",
        "- Do not assume a field exists if it is not present.",
        "- Do not infer missing values.",
        "- `null` means the source JSON explicitly contained a null value.",
        "- Empty arrays and objects are preserved as empty.",
        "- JSON Paths identify the original location of a value.",
        "- Headings and labels are structural metadata added by this converter.",
        "",
    ]

    if include_paths:
        lines.extend([
            "## JSON Path Convention",
            "",
            "- `$` = JSON document root",
            "- `.field` = object property",
            "- `[N]` = array index",
            '- `["field"]` = object property containing special characters',
            "",
        ])

    lines.extend([
        "---",
        "",
        "## Dataset",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(
    input_path: Path,
    output_path: Path,
    *,
    include_paths: bool,
    max_heading_depth: int,
) -> dict[str, Any]:

    try:
        with input_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {input_path}: "
            f"{exc.msg} at line {exc.lineno}, column {exc.colno}"
        ) from exc

    renderer = MarkdownRenderer(
        include_paths=include_paths,
        max_heading_depth=max_heading_depth,
    )

    body = renderer.render(data)

    header = build_header(
        source_file=input_path,
        data=data,
        markdown=body,
        include_paths=include_paths,
    )

    markdown = header + body

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        markdown,
        encoding="utf-8",
    )

    stats = collect_stats(data, markdown)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Convert JSON into structured Markdown optimized "
            "for LLM/RAG consumption."
        )
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Input JSON file",
    )

    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help=(
            "Output Markdown file. "
            "Defaults to input filename with .md extension."
        ),
    )

    parser.add_argument(
        "--no-paths",
        action="store_true",
        help="Do not include JSON Paths in the Markdown.",
    )

    parser.add_argument(
        "--max-heading-depth",
        type=int,
        default=DEFAULT_MAX_HEADING_DEPTH,
        help=(
            "Maximum Markdown heading depth "
            f"(default: {DEFAULT_MAX_HEADING_DEPTH})."
        ),
    )

    args = parser.parse_args()

    input_path = args.input

    if not input_path.exists():
        print(
            f"ERROR: File does not exist: {input_path}",
            file=sys.stderr,
        )
        return 1

    if not input_path.is_file():
        print(
            f"ERROR: Not a file: {input_path}",
            file=sys.stderr,
        )
        return 1

    if args.max_heading_depth < 2:
        print(
            "ERROR: --max-heading-depth must be >= 2",
            file=sys.stderr,
        )
        return 1

    output_path = (
        args.output
        if args.output
        else input_path.with_suffix(".md")
    )

    try:
        stats = convert(
            input_path,
            output_path,
            include_paths=not args.no_paths,
            max_heading_depth=args.max_heading_depth,
        )

    except (OSError, ValueError) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print("JSON → Markdown complete")
    print("------------------------")
    print(f"Input       : {input_path}")
    print(f"Output      : {output_path}")
    print(f"Root type   : {stats['root_type']}")
    print(f"Root entries: {stats['root_entries']:,}")
    print(f"JSON nodes  : {stats['json_nodes']:,}")
    print(f"Records     : {stats['records']:,}")
    print(f"Characters  : {stats['markdown_characters']:,}")
    print(f"Words       : {stats['markdown_words']:,}")
    print(f"Est. tokens : {stats['estimated_tokens']:,}")
    print(
        f"Size        : "
        f"{stats['markdown_bytes'] / 1024 / 1024:.2f} MiB"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

