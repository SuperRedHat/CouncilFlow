"""Tests for the restricted when-expression evaluator (TASK-075)."""

from __future__ import annotations

import pytest

from councilflow.config.when_eval import WhenExpressionError, evaluate

# ---------------------------------------------------------------------------
# Legitimate expressions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "context", "expected"),
    [
        ("task.complexity == 'L'", {"task": {"complexity": "L"}}, True),
        ("task.complexity == 'L'", {"task": {"complexity": "M"}}, False),
        ("task.complexity in ['S', 'M']", {"task": {"complexity": "S"}}, True),
        ("task.complexity in ['S', 'M']", {"task": {"complexity": "L"}}, False),
        ("task.complexity not in ['S', 'M']", {"task": {"complexity": "L"}}, True),
        ("'frontend' in task.module", {"task": {"module": "frontend/auth"}}, True),
        ("'frontend' in task.module", {"task": {"module": "backend/db"}}, False),
        (
            "task.complexity in ['S', 'M'] and 'test' in task.module",
            {"task": {"complexity": "S", "module": "test/api"}},
            True,
        ),
        (
            "task.complexity in ['S', 'M'] and 'test' in task.module",
            {"task": {"complexity": "L", "module": "test/api"}},
            False,
        ),
        ("not task.complexity == 'L'", {"task": {"complexity": "M"}}, True),
        ("not task.complexity == 'L'", {"task": {"complexity": "L"}}, False),
        (
            "task.complexity == 'L' or 'security' in task.module",
            {"task": {"complexity": "M", "module": "feature/security-core"}},
            True,
        ),
        ("True", {}, True),
        ("False", {}, False),
        ("1 == 1", {}, True),
        ("1 < 2", {}, True),
        ("2 >= 2", {}, True),
        ("'S' != 'M'", {}, True),
    ],
)
def test_legitimate_expressions(expr: str, context: dict, expected: bool) -> None:
    assert evaluate(expr, context) is expected


# ---------------------------------------------------------------------------
# Missing / partial context — must return False cleanly, never raise
# ---------------------------------------------------------------------------


def test_missing_top_level_name_returns_none_then_false() -> None:
    assert evaluate("task.complexity == 'L'", {}) is False


def test_missing_nested_field_returns_none_then_false() -> None:
    assert evaluate("task.complexity == 'L'", {"task": {}}) is False


def test_missing_field_in_ordering_is_false() -> None:
    assert evaluate("task.priority > 5", {"task": {}}) is False


def test_missing_container_for_in_is_false() -> None:
    assert evaluate("'x' in task.tags", {"task": {}}) is False


# ---------------------------------------------------------------------------
# Dangerous expressions — must all raise WhenExpressionError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('ls')",
        "task.__class__",
        "task.__class__.__bases__[0]",
        "[x for x in range(10)]",
        "open('/etc/passwd')",
        "lambda: None",
        "(lambda x: x)(5)",
        "eval('1+1')",
        "exec('print(1)')",
        "subprocess.run(['ls'])",
        "task['complexity']",
        "f'{task.complexity}'",
        "task.complexity if True else 'L'",
        "(x := 5)",
        "{1, 2, 3}",
        "{'a': 1}",
        "1 + 1",
        "not (lambda: True)()",
        "getattr(task, 'complexity')",
        "task._private",
        "task.__dict__",
    ],
)
def test_dangerous_expressions_rejected(expr: str) -> None:
    with pytest.raises(WhenExpressionError):
        evaluate(expr, {"task": {"complexity": "L"}})


# ---------------------------------------------------------------------------
# Attribute depth limitation
# ---------------------------------------------------------------------------


def test_single_level_attribute_allowed() -> None:
    assert evaluate("task.complexity == 'L'", {"task": {"complexity": "L"}}) is True


def test_chained_attribute_rejected() -> None:
    with pytest.raises(WhenExpressionError) as excinfo:
        evaluate("task.meta.owner == 'me'", {"task": {"meta": {"owner": "me"}}})
    assert "one level deep" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Parse errors and input validation
# ---------------------------------------------------------------------------


def test_empty_expression_rejected() -> None:
    with pytest.raises(WhenExpressionError):
        evaluate("", {})


def test_whitespace_only_rejected() -> None:
    with pytest.raises(WhenExpressionError):
        evaluate("   ", {})


def test_non_string_input_rejected() -> None:
    with pytest.raises(WhenExpressionError):
        evaluate(123, {})  # type: ignore[arg-type]


def test_syntax_error_gives_clear_message() -> None:
    with pytest.raises(WhenExpressionError) as excinfo:
        evaluate("task.complexity ==", {"task": {}})
    assert "parse" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Error messages carry node kind + position
# ---------------------------------------------------------------------------


def test_error_contains_node_kind_and_position() -> None:
    with pytest.raises(WhenExpressionError) as excinfo:
        evaluate("__import__('os')", {})
    msg = str(excinfo.value)
    assert "Call" in msg
    assert "line" in msg


# ---------------------------------------------------------------------------
# Attribute access on plain objects also works
# ---------------------------------------------------------------------------


class _FakeTask:
    complexity = "L"
    module = "frontend/auth"


def test_attribute_access_on_plain_object() -> None:
    assert evaluate("task.complexity == 'L'", {"task": _FakeTask()}) is True
    assert evaluate("'frontend' in task.module", {"task": _FakeTask()}) is True
