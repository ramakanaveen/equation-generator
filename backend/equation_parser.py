import re


def parse_equations(markdown_text: str) -> list[dict]:
    """
    Parse Ph1 markdown output into a list of equation dicts.

    Each equation follows the template:
        ### Alpha {N}: {Name}
        **Expression:** ...
        **Pattern Family:** ...
        **Economic Rationale:** ...
        **Frequency:** ... minutes
        **Parameter Specifications:** (table)
        **Grid Search Configuration:** ...

    Returns list of dicts with keys:
        number, name, expression, family, rationale,
        frequency, parameters, grid, raw_markdown
    """
    # Split on ### Alpha headings, keeping the heading in each block
    blocks = re.split(r"(?=### Alpha \d+)", markdown_text)
    equations = []
    for block in blocks:
        block = block.strip()
        if not block.startswith("### Alpha"):
            continue

        eq = _parse_block(block)
        if eq:
            equations.append(eq)

    return equations


def _parse_block(block: str) -> dict | None:
    # Extract heading: ### Alpha N: Name
    heading_match = re.match(r"### Alpha (\d+):\s*(.+)", block)
    if not heading_match:
        return None

    number = int(heading_match.group(1))
    name = heading_match.group(2).strip()

    def _extract(label: str) -> str:
        """Extract single-line field."""
        pattern = rf"\*\*{re.escape(label)}:\*\*\s*(.+)"
        m = re.search(pattern, block)
        return m.group(1).strip() if m else ""

    def _extract_multiline(label: str, next_label: str | None = None) -> str:
        """Extract multi-line field between label and next label."""
        if next_label:
            pattern = (
                rf"\*\*{re.escape(label)}:\*\*\s*(.*?)"
                rf"(?=\*\*{re.escape(next_label)}:\*\*|### Alpha \d+|$)"
            )
        else:
            pattern = rf"\*\*{re.escape(label)}:\*\*\s*(.*?)(?=### Alpha \d+|$)"
        m = re.search(pattern, block, re.DOTALL)
        return m.group(1).strip() if m else ""

    return {
        "number": number,
        "name": name,
        "expression": _extract("Expression"),
        "family": _extract("Pattern Family"),
        "rationale": _extract("Economic Rationale"),
        "frequency": _extract("Frequency"),
        "parameters": _extract_multiline("Parameter Specifications", "Grid Search Configuration"),
        "grid": _extract_multiline("Grid Search Configuration"),
        "raw_markdown": block,
    }
