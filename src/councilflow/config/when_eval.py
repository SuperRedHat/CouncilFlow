"""Restricted AST-based evaluator for RoleRoute ``when`` expressions.

Safety model: only a fixed whitelist of AST node types is permitted.
Any other node (Call, Lambda, Subscript outside list/tuple literals,
Import, Assign, Comprehension, dunder attribute access, etc.) causes a
:class:`WhenExpressionError` with an explicit message pointing at the
offending node.

Allowed:
    - Literals: str, int, float, bool, None, tuple/list of literals
    - Variable access: bare names bound in the evaluation context
    - Attribute access one level deep (e.g. ``task.complexity``); dunder
      names rejected
    - Boolean ops: ``and`` / ``or`` / ``not``
    - Comparisons: ``==`` / ``!=`` / ``<`` / ``<=`` / ``>`` / ``>=`` /
      ``in`` / ``not in``

Not allowed (hard rejected):
    - Call of any kind (``f()``, ``__import__(...)``, ``eval(...)``)
    - Lambda / FunctionDef / ClassDef / Import / Assign / ...
    - Subscript outside list/tuple literal construction (``task['x']``)
    - Attribute access deeper than one level (``task.x.y``)
    - Any attribute starting with ``_`` (rejects ``__class__``,
      ``__subclasses__``, etc.)
    - Comprehensions / generator expressions
    - Walrus / ternary / starred / f-string

Semantics:
    Missing ``task.<field>`` values return ``None`` (not raise). This
    allows routing rules like ``task.complexity == 'L'`` to safely
    evaluate False for tasks that never had a complexity set, instead
    of crashing the pipeline.
"""

from __future__ import annotations

import ast
from typing import Any


class WhenExpressionError(ValueError):
    """Raised when a ``when`` expression is syntactically invalid or unsafe."""


# AST node classes that are always allowed. This intentionally excludes
# ast.Call, ast.Lambda, ast.Subscript, ast.Import, ast.FunctionDef,
# ast.ClassDef, ast.Starred, ast.JoinedStr (f-strings), and all
# comprehension nodes.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BoolOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Attribute,
    ast.List,
    ast.Tuple,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)


def _reject(node: ast.AST, reason: str) -> None:
    """Raise a :class:`WhenExpressionError` with source location.

    ``lineno`` and ``col_offset`` are present on most nodes once Python
    parses them; the error message always includes the AST node type
    and a human-readable reason.
    """

    node_kind = type(node).__name__
    line = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    location = ""
    if line is not None and col is not None:
        location = f" at line {line}, col {col}"
    raise WhenExpressionError(
        f"Disallowed AST node `{node_kind}`{location}: {reason}"
    )


def _check_node(node: ast.AST) -> None:
    """Recursively validate that every descendant is in the whitelist.

    Also enforces one-level-deep ``Attribute`` access and rejects any
    attribute whose name starts with an underscore.
    """

    if not isinstance(node, _ALLOWED_NODES):
        _reject(node, "not in the allowed-AST whitelist")

    if isinstance(node, ast.Attribute):
        # Reject dunder / private attribute access.
        if node.attr.startswith("_"):
            _reject(node, f"private/dunder attribute `.{node.attr}` is forbidden")
        # Only one-level-deep: the value must be a bare Name.
        if not isinstance(node.value, ast.Name):
            _reject(
                node,
                "attribute access must be one level deep (e.g. `task.field`); "
                "chained `task.x.y` or expressions like `(a or b).c` are forbidden",
            )

    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            _reject(node, f"constant of unsupported type `{type(node.value).__name__}`")

    for child in ast.iter_child_nodes(node):
        _check_node(child)


_MISSING = object()


def _resolve_attribute(context: dict[str, Any], base: str, attr: str) -> Any:
    """Look up ``context[base][attr]`` with safe fallbacks.

    - ``context[base]`` missing → ``None``
    - ``context[base]`` is a dict without ``attr`` → ``None``
    - ``context[base]`` has ``attr`` as a normal attribute → return it
    - ``context[base]`` has no such attribute → ``None``

    Never raises for missing lookups; invalid lookups (e.g. trying to
    touch a dunder) are blocked earlier by :func:`_check_node`.
    """

    holder = context.get(base, _MISSING)
    if holder is _MISSING:
        return None
    if isinstance(holder, dict):
        return holder.get(attr)
    # Fall back to attribute access on arbitrary objects.
    return getattr(holder, attr, None)


def _evaluate(node: ast.AST, context: dict[str, Any]) -> Any:
    """Evaluate a validated AST node against the context."""

    if isinstance(node, ast.Expression):
        return _evaluate(node.body, context)

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value_node in node.values:
                result = _evaluate(value_node, context)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            last: Any = False
            for value_node in node.values:
                last = _evaluate(value_node, context)
                if last:
                    return last
            return last

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _evaluate(node.operand, context)

    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, context)
        current = left
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(comparator, context)
            if not _apply_comparison(op, current, right):
                return False
            current = right
        return True

    if isinstance(node, ast.Name):
        return context.get(node.id)

    if isinstance(node, ast.Attribute):
        # _check_node guarantees node.value is a Name.
        assert isinstance(node.value, ast.Name)
        return _resolve_attribute(context, node.value.id, node.attr)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.List):
        return [_evaluate(elt, context) for elt in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_evaluate(elt, context) for elt in node.elts)

    # Should be unreachable if _check_node already ran.
    _reject(node, "unexpected node at evaluation time")
    return None  # pragma: no cover


def _apply_comparison(op: ast.cmpop, left: Any, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Lt):
        return _safe_ordering(left, right, "<")
    if isinstance(op, ast.LtE):
        return _safe_ordering(left, right, "<=")
    if isinstance(op, ast.Gt):
        return _safe_ordering(left, right, ">")
    if isinstance(op, ast.GtE):
        return _safe_ordering(left, right, ">=")
    if isinstance(op, ast.In):
        return _safe_contains(right, left)
    if isinstance(op, ast.NotIn):
        return not _safe_contains(right, left)
    raise WhenExpressionError(
        f"Unsupported comparison operator `{type(op).__name__}`"
    )


def _safe_ordering(left: Any, right: Any, symbol: str) -> bool:
    """Ordering comparisons when operands are uncomparable return ``False``.

    Avoids raising ``TypeError`` when the user writes ``task.missing < 'x'``
    — routing should treat that rule as "not matching" rather than crash.
    """

    if left is None or right is None:
        return False
    try:
        if symbol == "<":
            return left < right
        if symbol == "<=":
            return left <= right
        if symbol == ">":
            return left > right
        if symbol == ">=":
            return left >= right
    except TypeError:
        return False
    raise WhenExpressionError(f"Unsupported ordering symbol `{symbol}`")


def _safe_contains(container: Any, needle: Any) -> bool:
    """``in`` returns False if the container is None or not iterable."""

    if container is None:
        return False
    try:
        return needle in container
    except TypeError:
        return False


def evaluate(expression: str, context: dict[str, Any]) -> bool:
    """Evaluate ``expression`` to a boolean against ``context``.

    Parameters
    ----------
    expression:
        The ``when`` source string from a :class:`RoleRoute`.
    context:
        Mapping from top-level names to their values. Nested access is
        one level deep via attribute syntax: ``task.complexity`` looks
        up ``context['task']['complexity']`` (or ``getattr`` on a plain
        object).

    Returns
    -------
    bool
        ``True`` if the expression matches; ``False`` otherwise. Falsy
        values from the expression ("", 0, [], None) coerce to False.

    Raises
    ------
    WhenExpressionError
        If the expression fails to parse or contains any disallowed
        construct. Never raised for missing context fields (those
        resolve to ``None``).
    """

    if not isinstance(expression, str):
        raise WhenExpressionError("when expression must be a string.")
    if not expression.strip():
        raise WhenExpressionError("when expression cannot be empty.")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as err:
        raise WhenExpressionError(
            f"Failed to parse when expression: {err.msg}"
        ) from err

    _check_node(tree)
    result = _evaluate(tree, context)
    return bool(result)


__all__ = ["WhenExpressionError", "evaluate"]
