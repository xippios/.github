"""A strict reader of the YAML that the trigger files of the README and the lean workflows of this
repository are written in: block mappings indented by two spaces, block sequences of mappings,
plain scalars and flow sequences of plain words. PyYAML is not among the suite's pins, so a test
reads a workflow with this reader, which refuses what it does not know instead of guessing: a
tab, a comment, a key given twice, a quoted or block scalar, an indicator at the start of a plain
scalar and an indentation that YAML would read otherwise. A file it reads, YAML reads alike, with
every scalar a string."""

import re

KEY = re.compile(r"([A-Za-z0-9_-]+):(?: (.+))?")
# A word of a flow sequence, such as a type of an event or a branch.
WORD = re.compile(r"[A-Za-z0-9_./*-]+")
# What YAML reads as an indicator at the start of a plain scalar; `[` opens a flow sequence,
# which the reader takes apart itself.
INDICATORS = "-?:,]{}#&*!|>'\"%@`"


class UnreadError(ValueError):
    """A line outside the subset that the reader knows."""


def scalar(value: str, line: str) -> str | list[str]:
    """The plain scalar or the flow sequence of plain words that `value` writes."""
    if value.startswith("["):
        items = [item.strip() for item in value.removesuffix("]")[1:].split(",")]
        if not value.endswith("]") or not all(WORD.fullmatch(item) for item in items):
            raise UnreadError(line)
        return items
    if value[0] in INDICATORS or ": " in value or " #" in value or value != value.rstrip():
        raise UnreadError(line)
    return value


def parse(text: str) -> dict:
    """The mapping that `text` writes, or `UnreadError` naming the first line it cannot read."""
    root: dict = {}
    # The open collections, innermost last, each with the indentation of its entries.
    stack: list[tuple[int, dict | list]] = [(0, root)]
    # The last key whose value is not on its line: its indentation, its mapping and its name.
    pending: tuple[int, dict, str] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if "\t" in line or "#" in line:
            raise UnreadError(line)
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        item = body.startswith("- ")
        if pending is not None and indent == pending[0] + 2:
            child: dict | list = [] if item else {}
            pending[1][pending[2]] = child
            stack.append((indent, child))
        else:
            while stack[-1][0] > indent:
                stack.pop()
            if stack[-1][0] != indent:
                raise UnreadError(line)
        pending = None
        collection = stack[-1][1]
        if item:
            if not isinstance(collection, list):
                raise UnreadError(line)
            mapping: dict = {}
            collection.append(mapping)
            indent += 2
            stack.append((indent, mapping))
            body = body[2:]
        elif isinstance(collection, dict):
            mapping = collection
        else:
            raise UnreadError(line)
        match = KEY.fullmatch(body)
        if match is None or match.group(1) in mapping:
            raise UnreadError(line)
        key, value = match.groups()
        if value is None:
            mapping[key] = None
            pending = (indent, mapping, key)
        else:
            mapping[key] = scalar(value, line)
    return root
