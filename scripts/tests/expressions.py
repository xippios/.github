"""The conditions of the workflows and the trigger files as GitHub evaluates them, in the subset
the tests know: string literals in single quotes, the properties of the context a test gives, an
object filter `.*.`, the functions `contains`, `startsWith`, `endsWith` and `fromJSON`, `==` and
`!=`, `&&`, `||` and parentheses. Strings compare without case, `&&` and `||` give one of their
operands as GitHub's do, and a variable that neither the repository nor the organization sets
reads as ''. A property that the context does not hold, a comparison of two values of different
kinds and any form outside the subset raise `OutsideError` instead of being guessed."""

import json
import re

TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^']|'')*')|(?P<op>==|!=|&&|\|\||[(),])"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_-]*(?:\.(?:[A-Za-z_][A-Za-z0-9_-]*|\*))*))"
)
FUNCTIONS = ("contains", "startsWith", "endsWith", "fromJSON")


class OutsideError(ValueError):
    """A condition, or a part of one, outside the subset that the evaluator knows."""


def tokens(condition: str) -> list[tuple[str, str]]:
    """The tokens of ``condition``, each its kind and its text."""
    found = []
    position = 0
    while condition[position:].strip():
        match = TOKEN.match(condition, position)
        if match is None:
            raise OutsideError(condition[position:])
        kind = match.lastgroup
        found.append((kind, match.group(kind)))
        position = match.end()
    return found


def truthy(value: object) -> bool:
    """GitHub's truth: false, null, 0 and '' are false, and any other value, [] too, is true."""
    if value is None or value is False or value == "":
        return False
    return not (isinstance(value, int | float) and not isinstance(value, bool) and value == 0)


def equal(left: object, right: object) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left.lower() == right.lower()
    if type(left) is not type(right):
        raise OutsideError(f"{left!r} and {right!r} are of different kinds")
    return left == right


def text(value: object) -> str:
    if not isinstance(value, str):
        raise OutsideError(f"{value!r} is no string")
    return value


def call(name: str, arguments: list[object]) -> object:
    if name == "fromJSON" and len(arguments) == 1:
        return json.loads(text(arguments[0]))
    if name in ("startsWith", "endsWith") and len(arguments) == 2:
        string, part = text(arguments[0]).lower(), text(arguments[1]).lower()
        return string.startswith(part) if name == "startsWith" else string.endswith(part)
    if name == "contains" and len(arguments) == 2:
        search, item = arguments
        if isinstance(search, list):
            return any(isinstance(each, type(item)) and equal(each, item) for each in search)
        return text(item).lower() in text(search).lower()
    raise OutsideError(f"{name} with {len(arguments)} arguments")


def resolve(path: str, context: dict) -> object:
    """The value of the property ``path`` in ``context``; an unset variable reads as ''."""
    parts = path.split(".")
    if parts[0] == "vars" and len(parts) == 2:
        return context.get("vars", {}).get(parts[1], "")
    values: list[object] = [context]
    filtered = False
    for part in parts:
        if part == "*":
            if filtered or len(values) != 1 or not isinstance(values[0], list):
                raise OutsideError(path)
            values, filtered = list(values[0]), True
            continue
        for value in values:
            if not isinstance(value, dict) or part not in value:
                raise OutsideError(path)
        values = [value[part] for value in values]
    return values if filtered else values[0]


class Parser:
    """A descent over the tokens of one condition, evaluating as it reads."""

    def __init__(self, condition: str, context: dict) -> None:
        self.tokens = tokens(condition)
        self.context = context
        self.position = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self, expected: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (expected is not None and token[1] != expected):
            raise OutsideError(f"expected {expected or 'a token'} at token {self.position}")
        self.position += 1
        return token

    def condition(self) -> object:
        value = self.either()
        if self.peek() is not None:
            raise OutsideError(f"unread token {self.peek()[1]!r}")
        return value

    def either(self) -> object:
        value = self.both()
        while self.peek() == ("op", "||"):
            self.take()
            right = self.both()
            value = value if truthy(value) else right
        return value

    def both(self) -> object:
        value = self.comparison()
        while self.peek() == ("op", "&&"):
            self.take()
            right = self.comparison()
            value = right if truthy(value) else value
        return value

    def comparison(self) -> object:
        left = self.primary()
        token = self.peek()
        if token in (("op", "=="), ("op", "!=")):
            self.take()
            right = self.primary()
            return equal(left, right) == (token[1] == "==")
        return left

    def primary(self) -> object:
        kind, word = self.take()
        if (kind, word) == ("op", "("):
            value = self.either()
            self.take(")")
            return value
        if kind == "string":
            return word[1:-1].replace("''", "'")
        if kind != "name":
            raise OutsideError(f"unexpected {word!r}")
        if self.peek() == ("op", "("):
            if word not in FUNCTIONS:
                raise OutsideError(f"unknown function {word}")
            self.take()
            arguments = []
            if self.peek() != ("op", ")"):
                arguments.append(self.either())
                while self.peek() == ("op", ","):
                    self.take()
                    arguments.append(self.either())
            self.take(")")
            return call(word, arguments)
        return resolve(word, self.context)


def holds(condition: str, context: dict) -> bool:
    """Whether ``condition`` holds in ``context``, the contexts of GitHub a test gives, such as
    ``{"github": {"event_name": "push"}, "vars": {}}``."""
    return truthy(Parser(condition, context).condition())


def runs(condition: str, event: str, variables: dict[str, str]) -> bool:
    """Whether `condition` holds on the caller's event `event` with the caller's `variables`."""
    return holds(condition, {"github": {"event_name": event}, "vars": variables})
