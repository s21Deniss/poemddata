#!/usr/bin/env python3
"""
json2md.py

LLM/RAG-oriented JSON -> Markdown converter.

Designed initially for RePoE / Path of Exile datasets, but can also
process arbitrary JSON.

Main goals:

    JSON
      ↓
    remove empty/noise values
      ↓
    compress repetitive structures
      ↓
    preserve source values
      ↓
    create independent records
      ↓
    Markdown suitable for NotebookLM / Gemini

The converter does NOT:
    - invent descriptions
    - summarize facts
    - infer missing values
    - modify numeric values
    - translate game data
    - resolve external references unless explicitly requested

Usage:

    python json2md.py data/mods.json

    python json2md.py data/mods.json ai/mods.md

    python json2md.py data/mods.json ai/mods.md --dataset mods

    python json2md.py data/mods.json ai/mods.md --stats
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ============================================================================
# Configuration
# ============================================================================

# Fields that are almost always useful when represented in an LLM document.
#
# This is NOT an allow-list. Unknown fields are still preserved.
# It only controls preferred ordering.
PREFERRED_ORDER = [
    "name",
    "text",
    "type",
    "domain",
    "generation_type",
    "required_level",
    "is_essence_only",
    "stats",
    "groups",
    "spawn_weights",
    "generation_weights",
    "adds_tags",
    "implicit_tags",
    "grants_effects",
    "gold_value",
]


# These fields are commonly empty and provide no information when empty.
DROP_EMPTY = True


# Values above this length are kept, but rendered as block text rather
# than trying to put them into a single Markdown line.
LONG_TEXT_THRESHOLD = 500


# ============================================================================
# Basic helpers
# ============================================================================

def is_empty(value: Any) -> bool:
    """Return True if a value contains no useful data."""

    if value is None:
        return True

    if value == "":
        return True

    if isinstance(value, list) and len(value) == 0:
        return True

    if isinstance(value, dict) and len(value) == 0:
        return True

    return False


def scalar_to_text(value: Any) -> str:
    """
    Convert a scalar without changing its meaning.
    """

    if value is None:
        return "null"

    if value is True:
        return "true"

    if value is False:
        return "false"

    if isinstance(value, str):
        return value

    return str(value)


def clean_text(value: str) -> str:
    """
    Prevent source strings from accidentally becoming Markdown structure.

    The actual value is not modified in the dataset logic.
    """

    return value.replace("\r\n", "\n").replace("\r", "\n")


def safe_heading(value: Any) -> str:
    """
    Make a value safe to use in a Markdown heading.
    """

    text = scalar_to_text(value)
    text = text.replace("\n", " ")

    # Prevent source data beginning with # from creating another heading.
    text = re.sub(r"^#+\s*", "", text)

    if len(text) > 160:
        text = text[:157] + "..."

    return text or "(unnamed)"


def ordered_keys(obj: dict[str, Any]) -> list[str]:
    """
    Put important fields first while preserving all unknown fields.
    """

    preferred = [
        key for key in PREFERRED_ORDER
        if key in obj
    ]

    remaining = [
        key for key in obj
        if key not in preferred
    ]

    return preferred + remaining


def find_identifier(obj: dict[str, Any]) -> tuple[str, Any] | None:
    """
    Find a useful identifier for arbitrary records.
    """

    for field in (
        "name",
        "title",
        "id",
        "slug",
        "key",
        "uuid",
    ):
        if field in obj:
            value = obj[field]

            if not isinstance(value, (dict, list)):
                if not is_empty(value):
                    return field, value

    return None


# ============================================================================
# Compact RePoE structures
# ============================================================================

def render_stats(stats: list[Any]) -> list[str]:
    """
    Compress RePoE stats.

    Input:

        [
            {
                "id": "maximum_life",
                "min": 10,
                "max": 20
            }
        ]

    Output:

        - maximum_life: 10-20
    """

    lines = []

    for stat in stats:

        if not isinstance(stat, dict):
            lines.append(f"- {scalar_to_text(stat)}")
            continue

        stat_id = stat.get("id", "?")
        minimum = stat.get("min")
        maximum = stat.get("max")

        if minimum is not None and maximum is not None:
            if minimum == maximum:
                lines.append(
                    f"- `{stat_id}`: {minimum}"
                )
            else:
                lines.append(
                    f"- `{stat_id}`: {minimum}-{maximum}"
                )

        elif minimum is not None:
            lines.append(
                f"- `{stat_id}`: min={minimum}"
            )

        elif maximum is not None:
            lines.append(
                f"- `{stat_id}`: max={maximum}"
            )

        else:
            lines.append(
                f"- `{stat_id}`"
            )

    return lines


def render_weights(weights: list[Any]) -> str:
    """
    Compress RePoE weight arrays.

    Input:

        [
            {"tag": "ring", "weight": 500},
            {"tag": "amulet", "weight": 250}
        ]

    Output:

        ring=500, amulet=250
    """

    parts = []

    for entry in weights:

        if not isinstance(entry, dict):
            parts.append(scalar_to_text(entry))
            continue

        tag = entry.get("tag", "?")
        weight = entry.get("weight", "?")

        parts.append(
            f"{tag}={weight}"
        )

    return ", ".join(parts)


def render_granted_effects(effects: list[Any]) -> list[str]:
    """
    Compress granted effects.
    """

    lines = []

    for effect in effects:

        if not isinstance(effect, dict):
            lines.append(
                f"- {scalar_to_text(effect)}"
            )
            continue

        effect_id = effect.get(
            "granted_effect_id",
            "?",
        )

        level = effect.get("level")

        if level is not None:
            lines.append(
                f"- `{effect_id}` (level {level})"
            )
        else:
            lines.append(
                f"- `{effect_id}`"
            )

    return lines


# ============================================================================
# Generic arrays
# ============================================================================

def render_scalar_array(
    values: list[Any],
) -> list[str]:

    return [
        f"- {scalar_to_text(value)}"
        for value in values
        if not (DROP_EMPTY and is_empty(value))
    ]


def render_generic_array(
    values: list[Any],
    indent: str = "",
) -> list[str]:

    lines = []

    for value in values:

        if is_empty(value) and DROP_EMPTY:
            continue

        if isinstance(value, dict):

            identifier = find_identifier(value)

            if identifier:
                field, identifier_value = identifier

                lines.append(
                    f"{indent}- **{field}:** "
                    f"{safe_heading(identifier_value)}"
                )
            else:
                lines.append(
                    f"{indent}-"
                )

            nested = render_generic_object(
                value,
                indent=indent + "  ",
            )

            lines.extend(nested)

        elif isinstance(value, list):

            lines.append(
                f"{indent}-"
            )

            lines.extend(
                render_generic_array(
                    value,
                    indent=indent + "  ",
                )
            )

        else:

            lines.append(
                f"{indent}- "
                f"{scalar_to_text(value)}"
            )

    return lines


# ============================================================================
# Generic object renderer
# ============================================================================

def render_generic_object(
    obj: dict[str, Any],
    *,
    indent: str = "",
) -> list[str]:

    lines = []

    for key in ordered_keys(obj):

        value = obj[key]

        if DROP_EMPTY and is_empty(value):
            continue

        if isinstance(value, (str, int, float, bool)) or value is None:

            text = clean_text(
                scalar_to_text(value)
            )

            if "\n" in text or len(text) > LONG_TEXT_THRESHOLD:

                lines.append(
                    f"{indent}**{key}:**"
                )
                lines.append("")

                lines.extend(
                    f"{indent}{line}"
                    for line in text.splitlines()
                )

                lines.append("")

            else:

                lines.append(
                    f"{indent}**{key}:** {text}"
                )

        elif isinstance(value, list):

            if not value:
                continue

            lines.append(
                f"{indent}**{key}:**"
            )

            lines.extend(
                render_generic_array(
                    value,
                    indent=indent + "  ",
                )
            )

        elif isinstance(value, dict):

            lines.append(
                f"{indent}**{key}:**"
            )

            lines.extend(
                render_generic_object(
                    value,
                    indent=indent + "  ",
                )
            )

    return lines


# ============================================================================
# RePoE mod renderer
# ============================================================================

def render_mod(
    mod_id: str,
    mod: dict[str, Any],
) -> list[str]:

    lines = []

    name = mod.get("name")

    if name and not is_empty(name):
        title = name
    else:
        title = mod_id

    lines.append(
        f"## Mod: {safe_heading(title)}"
    )

    lines.append("")

    # The ID is extremely useful for cross-referencing with other RePoE
    # datasets, so it is always retained.
    lines.append(
        f"**ID:** `{mod_id}`"
    )

    lines.append("")

    # ------------------------------------------------------------------------
    # Important scalar properties
    # ------------------------------------------------------------------------

    scalar_fields = [
        "text",
        "type",
        "domain",
        "generation_type",
        "required_level",
        "is_essence_only",
        "gold_value",
    ]

    for field in scalar_fields:

        if field not in mod:
            continue

        value = mod[field]

        if DROP_EMPTY and is_empty(value):
            continue

        if field == "text":

            text = clean_text(
                scalar_to_text(value)
            )

            if len(text) > LONG_TEXT_THRESHOLD or "\n" in text:

                lines.append("**Text:**")
                lines.append("")
                lines.append(text)
                lines.append("")

            else:

                lines.append(
                    f"**Text:** {text}"
                )

        else:

            lines.append(
                f"**{field}:** "
                f"{scalar_to_text(value)}"
            )

    # ------------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------------

    stats = mod.get("stats")

    if stats:
        lines.append("")
        lines.append("### Stats")
        lines.append("")
        lines.extend(render_stats(stats))

    # ------------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------------

    groups = mod.get("groups")

    if groups:
        lines.append("")
        lines.append("### Groups")
        lines.append("")

        lines.append(
            ", ".join(
                f"`{scalar_to_text(x)}`"
                for x in groups
                if not is_empty(x)
            )
        )

    # ------------------------------------------------------------------------
    # Spawn weights
    # ------------------------------------------------------------------------

    spawn_weights = mod.get("spawn_weights")

    if spawn_weights:
        lines.append("")
        lines.append("### Spawn Weights")
        lines.append("")
        lines.append(
            render_weights(spawn_weights)
        )

    # ------------------------------------------------------------------------
    # Generation weights
    # ------------------------------------------------------------------------

    generation_weights = mod.get(
        "generation_weights"
    )

    if generation_weights:
        lines.append("")
        lines.append("### Generation Weights")
        lines.append("")
        lines.append(
            render_weights(
                generation_weights
            )
        )

    # ------------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------------

    adds_tags = mod.get("adds_tags")

    if adds_tags:
        lines.append("")
        lines.append("### Adds Tags")
        lines.append("")
        lines.append(
            ", ".join(
                f"`{scalar_to_text(x)}`"
                for x in adds_tags
                if not is_empty(x)
            )
        )

    implicit_tags = mod.get("implicit_tags")

    if implicit_tags:
        lines.append("")
        lines.append("### Implicit Tags")
        lines.append("")
        lines.append(
            ", ".join(
                f"`{scalar_to_text(x)}`"
                for x in implicit_tags
                if not is_empty(x)
            )
        )

    # ------------------------------------------------------------------------
    # Granted effects
    # ------------------------------------------------------------------------

    grants_effects = mod.get(
        "grants_effects"
    )

    if grants_effects:
        lines.append("")
        lines.append("### Granted Effects")
        lines.append("")
        lines.extend(
            render_granted_effects(
                grants_effects
            )
        )

    # ------------------------------------------------------------------------
    # Unknown fields
    #
    # This protects us if RePoE adds something in a future version.
    # ------------------------------------------------------------------------

    known_fields = {
        "name",
        "text",
        "type",
        "domain",
        "generation_type",
        "required_level",
        "is_essence_only",
        "gold_value",
        "stats",
        "groups",
        "spawn_weights",
        "generation_weights",
        "adds_tags",
        "implicit_tags",
        "grants_effects",
    }

    unknown_fields = [
        key
        for key in mod
        if key not in known_fields
    ]

    for key in unknown_fields:

        value = mod[key]

        if DROP_EMPTY and is_empty(value):
            continue

        lines.append("")
        lines.append(
            f"### {safe_heading(key)}"
        )
        lines.append("")

        lines.extend(
            render_generic_object(
                {key: value}
            )
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    return lines


# ============================================================================
# Dataset detection
# ============================================================================

def detect_dataset(
    data: Any,
    filename: str,
) -> str:

    name = filename.lower()

    if name in {
        "mods.json",
        "mods.min.json",
    }:
        return "mods"

    if name in {
        "stats.json",
        "stats.min.json",
    }:
        return "stats"

    if name in {
        "stat_translations.json",
        "stat_translations.min.json",
    }:
        return "stat_translations"

    # Heuristic detection.
    if isinstance(data, dict):

        sample = next(
            iter(data.values()),
            None,
        )

        if isinstance(sample, dict):

            if (
                "generation_type" in sample
                and "stats" in sample
            ):
                return "mods"

    return "generic"


# ============================================================================
# Generic dataset renderer
# ============================================================================

def render_generic_dataset(
    data: Any,
) -> list[str]:

    lines = []

    if isinstance(data, dict):

        for key, value in data.items():

            if DROP_EMPTY and is_empty(value):
                continue

            if isinstance(value, dict):

                identifier = find_identifier(
                    value
                )

                if identifier:

                    field, identifier_value = (
                        identifier
                    )

                    title = (
                        f"{field}: "
                        f"{safe_heading(identifier_value)}"
                    )

                else:

                    title = safe_heading(key)

                lines.append(
                    f"## {title}"
                )

                lines.append("")

                lines.append(
                    f"**ID:** `{key}`"
                )

                lines.append("")

                lines.extend(
                    render_generic_object(
                        value
                    )
                )

                lines.append("")
                lines.append("---")
                lines.append("")

            else:

                lines.append(
                    f"## {safe_heading(key)}"
                )

                lines.append("")

                if isinstance(value, list):
                    lines.extend(
                        render_generic_array(value)
                    )
                else:
                    lines.append(
                        scalar_to_text(value)
                    )

                lines.append("")

    elif isinstance(data, list):

        for index, value in enumerate(data):

            if DROP_EMPTY and is_empty(value):
                continue

            lines.append(
                f"## Record {index + 1}"
            )

            lines.append("")

            if isinstance(value, dict):
                lines.extend(
                    render_generic_object(value)
                )
            else:
                lines.append(
                    scalar_to_text(value)
                )

            lines.append("")
            lines.append("---")
            lines.append("")

    else:

        lines.append(
            scalar_to_text(data)
        )

    return lines


# ============================================================================
# Statistics
# ============================================================================

def count_nodes(value: Any) -> int:

    if isinstance(value, dict):
        return (
            1
            + sum(
                count_nodes(v)
                for v in value.values()
            )
        )

    if isinstance(value, list):
        return (
            1
            + sum(
                count_nodes(v)
                for v in value
            )
        )

    return 1


def count_records(value: Any) -> int:

    if isinstance(value, dict):

        return sum(
            1 if isinstance(v, dict) else 0
            for v in value.values()
        )

    if isinstance(value, list):

        return sum(
            1 if isinstance(v, dict) else 0
            for v in value
        )

    return 0


def estimate_tokens(text: str) -> int:
    """
    Rough estimate only.

    Actual Gemini tokenization will differ.
    """

    return max(
        1,
        (len(text) + 3) // 4,
    )


# ============================================================================
# Header
# ============================================================================

def build_header(
    *,
    dataset_name: str,
    source: Path,
    data: Any,
    body: str,
) -> str:

    records = count_records(data)
    nodes = count_nodes(data)

    size_bytes = len(
        body.encode("utf-8")
    )

    tokens = estimate_tokens(body)

    return f"""# Path of Exile Data: {dataset_name}

> Source: `{source.name}`
>
> This document is a deterministic conversion of the source JSON.
> No factual information has been inferred or generated.
>
> Values shown here originate from the source dataset.
> Missing fields should not be assumed to exist.
> Empty values are omitted to reduce noise.
>
> Internal IDs are preserved because they may reference other RePoE datasets.

## Dataset Information

- Records: {records:,}
- JSON nodes: {nodes:,}
- Markdown characters: {len(body):,}
- Estimated tokens: {tokens:,}
- Markdown size: {size_bytes / 1024 / 1024:.2f} MiB

---

"""


# ============================================================================
# Conversion
# ============================================================================

def convert(
    input_path: Path,
    output_path: Path,
    *,
    dataset: str | None = None,
) -> dict[str, Any]:

    with input_path.open(
        "r",
        encoding="utf-8",
    ) as f:

        data = json.load(f)

    dataset_name = (
        dataset
        or detect_dataset(
            data,
            input_path.name,
        )
    )

    # ---------------------------------------------------------------
    # Render
    # ---------------------------------------------------------------

    if dataset_name == "mods":

        if not isinstance(data, dict):
            raise ValueError(
                "mods dataset must be a JSON object"
            )

        body_lines = []

        for mod_id, mod in data.items():

            if not isinstance(mod, dict):
                continue

            body_lines.extend(
                render_mod(
                    mod_id,
                    mod,
                )
            )

        body = "\n".join(
            body_lines
        )

    else:

        body = "\n".join(
            render_generic_dataset(
                data
            )
        )

    header = build_header(
        dataset_name=dataset_name,
        source=input_path,
        data=data,
        body=body,
    )

    output = header + body

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        output,
        encoding="utf-8",
    )

    return {
        "dataset": dataset_name,
        "records": count_records(data),
        "nodes": count_nodes(data),
        "characters": len(output),
        "words": len(output.split()),
        "estimated_tokens": estimate_tokens(output),
        "bytes": len(
            output.encode("utf-8")
        ),
    }


# ============================================================================
# CLI
# ============================================================================

def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Convert RePoE/JSON datasets into "
            "compact LLM/RAG-friendly Markdown."
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
            "Defaults to <input>.md"
        ),
    )

    parser.add_argument(
        "--dataset",
        choices=[
            "mods",
            "stats",
            "stat_translations",
            "generic",
        ],
        help=(
            "Force dataset type. "
            "Normally detected automatically."
        ),
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print output statistics.",
    )

    args = parser.parse_args()

    input_path = args.input

    if not input_path.exists():
        print(
            f"ERROR: File does not exist: {input_path}",
            file=sys.stderr,
        )
        return 1

    output_path = (
        args.output
        or input_path.with_suffix(".md")
    )

    try:

        result = convert(
            input_path,
            output_path,
            dataset=args.dataset,
        )

    except json.JSONDecodeError as exc:

        print(
            f"ERROR: Invalid JSON: {exc}",
            file=sys.stderr,
        )
        return 1

    except Exception as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print()
    print("JSON → LLM Markdown")
    print("===================")
    print(f"Dataset       : {result['dataset']}")
    print(f"Input         : {input_path}")
    print(f"Output        : {output_path}")
    print(f"Records       : {result['records']:,}")
    print(f"JSON nodes    : {result['nodes']:,}")
    print(f"Characters    : {result['characters']:,}")
    print(f"Words         : {result['words']:,}")
    print(
        f"Est. tokens   : "
        f"{result['estimated_tokens']:,}"
    )
    print(
        f"Size          : "
        f"{result['bytes'] / 1024 / 1024:.2f} MiB"
    )
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
