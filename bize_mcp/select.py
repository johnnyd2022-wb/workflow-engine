"""A JMESPath subset for ``select`` and ``$from`` paths. No functions, no filters, no code.

Supported::

    name                      a field                       items[0]          one element
    a.b.c                     nested fields                 items[*].name     that field of every element
    items[*].{id: id, n: name}   a projection into new objects (keys are plain names)
    "quoted field"            a field whose name needs quoting

A path that finds nothing gives ``null`` (a missing field is never turned into 0 or ""). Unlike JMESPath,
a projection keeps those nulls, so ``items[*].cost`` lines up with ``items[*].name`` by position and a
missing cost can never be paired with the wrong lot. The parser is bounded (length and
depth) so a model can't hand it something expensive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_LENGTH = 300
MAX_DEPTH = 8
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")
_INT = re.compile(r"-?\d+")


class SelectError(ValueError):
    """The expression isn't in the supported subset."""


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Index:
    n: int


@dataclass(frozen=True)
class Star:
    pass


@dataclass(frozen=True)
class Hash:
    pairs: tuple[tuple[str, tuple], ...]


class _Parser:
    def __init__(self, text: str, allow_hash: bool):
        if len(text) > MAX_LENGTH:
            raise SelectError("The expression is too long.")
        self.text, self.pos, self.allow_hash = text, 0, allow_hash

    def fail(self, what: str) -> SelectError:
        return SelectError(f"Unsupported or invalid expression near position {self.pos}: {what}.")

    def peek(self) -> str:
        return self.text[self.pos : self.pos + 1]

    def space(self) -> None:
        while self.peek() == " ":
            self.pos += 1

    def parse(self) -> tuple:
        path = self.path(0)
        self.space()
        if self.pos != len(self.text):
            raise self.fail("unexpected text")
        return path

    def name(self) -> str:
        self.space()
        if self.peek() == '"':
            end = self.text.find('"', self.pos + 1)
            if end < 0:
                raise self.fail("unterminated quote")
            value, self.pos = self.text[self.pos + 1 : end], end + 1
            return value
        match = _IDENT.match(self.text, self.pos)
        if not match:
            raise self.fail("expected a field name")
        self.pos = match.end()
        return match.group(0)

    def path(self, depth: int) -> tuple:
        if depth > MAX_DEPTH:
            raise self.fail("nested too deeply")
        steps: list = []
        self.space()
        if self.peek() == "{":
            steps.append(self.hash(depth))
        elif self.peek() == "[":
            steps.append(self.bracket())
        else:
            steps.append(Field(self.name()))
        while True:
            self.space()
            char = self.peek()
            if char == ".":
                self.pos += 1
                self.space()
                steps.append(self.hash(depth) if self.peek() == "{" else Field(self.name()))
            elif char == "[":
                steps.append(self.bracket())
            else:
                return tuple(steps)

    def bracket(self):
        self.pos += 1
        self.space()
        if self.peek() == "*":
            self.pos += 1
            node: Any = Star()
        else:
            match = _INT.match(self.text, self.pos)
            if not match:
                raise self.fail("expected * or a number")
            self.pos, node = match.end(), Index(int(match.group(0)))
        self.space()
        if self.peek() != "]":
            raise self.fail("expected ]")
        self.pos += 1
        return node

    def hash(self, depth: int):
        if not self.allow_hash:
            raise self.fail("{ } is not allowed here")
        self.pos += 1
        pairs = []
        while True:
            key = self.name()
            self.space()
            if self.peek() != ":":
                raise self.fail("expected :")
            self.pos += 1
            pairs.append((key, self.path(depth + 1)))
            self.space()
            char = self.peek()
            self.pos += 1
            if char == "}":
                return Hash(tuple(pairs))
            if char != ",":
                raise self.fail("expected , or }")


def compile_expression(text: str, *, allow_hash: bool = True) -> tuple:
    if not isinstance(text, str) or not text.strip():
        raise SelectError("The expression is empty.")
    return _Parser(text.strip(), allow_hash).parse()


_MISSING = object()


def _apply(steps: tuple, value: Any) -> Any:
    for index, step in enumerate(steps):
        if value is _MISSING or value is None:
            return None
        if isinstance(step, Field):
            value = value.get(step.name) if isinstance(value, dict) else None
        elif isinstance(step, Index):
            if not isinstance(value, list):
                return None
            try:
                value = value[step.n]
            except IndexError:
                return None
        elif isinstance(step, Hash):
            value = {key: _apply(sub, value) for key, sub in step.pairs}
        elif isinstance(step, Star):
            if not isinstance(value, list):
                return None
            rest = steps[index + 1 :]
            return [_apply(rest, item) if rest else item for item in value]
    return value


def evaluate(expression: tuple, value: Any) -> Any:
    return _apply(expression, value)


def select(text: str, value: Any) -> Any:
    return evaluate(compile_expression(text), value)
