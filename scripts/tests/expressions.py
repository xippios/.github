"""The conditions of the workflows and the trigger files as GitHub evaluates them, in the subset
the tests know: comparisons of `github.event_name` or a variable with a literal, joined by `&&`.
Strings compare without case, and a variable that neither the repository nor the organization
sets reads as ''. A term outside the subset raises `ValueError` instead of being guessed."""

import re

TERM = re.compile(r"(github\.event_name|vars\.[A-Z_]+) (==|!=) '([^']*)'")


def runs(condition: str, event: str, variables: dict[str, str]) -> bool:
    """Whether `condition` holds on the caller's event `event` with the caller's `variables`."""
    result = True
    for term in condition.split(" && "):
        match = TERM.fullmatch(term)
        if match is None:
            raise ValueError(term)
        name, operator, literal = match.groups()
        value = event if name == "github.event_name" else variables.get(name[5:], "")
        result = result and ((value.lower() == literal.lower()) == (operator == "=="))
    return result
