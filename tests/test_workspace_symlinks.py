"""TASK-057 — materialize_workspace exposes dependency dirs as junctions / symlinks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from councilflow.models.delegation import (
    DEFAULT_DEPENDENCY_SYMLINKS,
    DEFAULT_ISOLATION_EXCLUDE_PATTERNS,
    IsolatedWorkspace,
)
from councilflow.utils.io import cleanup_workspace, materialize_workspace


def _seed_dependency_dir(root: Path, name: str, file_name: str, content: str) -> Path:
    """Create a small dependency-style tree under root/<name>/<...>/<file>."""

    target = root / name / ".bin" / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _materialize_with_copy(
    source: Path,
    council_root: Path,
    delegation_id: str,
    dependency_symlinks: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
):
    isolated = IsolatedWorkspace(
        strategy="copy",
        include_patterns=[],
        exclude_patterns=(
            exclude_patterns
            if exclude_patterns is not None
            else list(DEFAULT_ISOLATION_EXCLUDE_PATTERNS)
        ),
        workspace_path=None,
        dependency_symlinks=(
            dependency_symlinks
            if dependency_symlinks is not None
            else list(DEFAULT_DEPENDENCY_SYMLINKS)
        ),
    )
    return materialize_workspace(
        project_root=source,
        council_root=council_root,
        delegation_id=delegation_id,
        isolated=isolated,
    )


def test_default_dependency_symlinks_cover_common_ecosystems() -> None:
    names = set(DEFAULT_DEPENDENCY_SYMLINKS)
    assert "node_modules" in names
    assert ".venv" in names
    assert "venv" in names
    assert "vendor" in names


def test_materialize_copy_symlinks_node_modules_so_sidecar_can_read_deps(
    tmp_path: Path,
) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    seeded = _seed_dependency_dir(source, "node_modules", "fake-binary", "#!/bin/sh\n")
    council_root = source / ".council"

    materialization = _materialize_with_copy(
        source=source,
        council_root=council_root,
        delegation_id="smoke_symlinks",
    )
    workspace_dep = materialization.workspace_path / "node_modules" / ".bin" / "fake-binary"

    assert materialization.effective_strategy == "copy"
    assert workspace_dep.exists(), "symlinked binary should be readable from workspace"
    assert workspace_dep.read_text(encoding="utf-8") == "#!/bin/sh\n"

    cleanup_workspace(source, materialization.workspace_path, materialization.effective_strategy)

    # Source dependency must remain intact after workspace cleanup.
    assert seeded.exists(), "cleanup must never touch the real source dependency directory"
    assert seeded.read_text(encoding="utf-8") == "#!/bin/sh\n"


def test_materialize_copy_skips_missing_dependency_silently(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "app.ts").write_text("export {}\n", encoding="utf-8")
    council_root = source / ".council"

    # No node_modules / .venv / venv / vendor in source — materialize should
    # succeed and simply not create any symlink entries.
    materialization = _materialize_with_copy(
        source=source,
        council_root=council_root,
        delegation_id="no_deps",
    )
    assert materialization.effective_strategy == "copy"
    assert (materialization.workspace_path / "src" / "app.ts").exists()
    assert not (materialization.workspace_path / "node_modules").exists()

    cleanup_workspace(source, materialization.workspace_path, materialization.effective_strategy)


def test_materialize_copy_honors_empty_dependency_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    _seed_dependency_dir(source, "node_modules", "fake-binary", "noop")
    council_root = source / ".council"

    # When the caller explicitly opts out of dependency sharing, node_modules
    # must not appear in the workspace.
    materialization = _materialize_with_copy(
        source=source,
        council_root=council_root,
        delegation_id="opt_out",
        dependency_symlinks=[],
    )
    assert not (materialization.workspace_path / "node_modules").exists()

    cleanup_workspace(source, materialization.workspace_path, materialization.effective_strategy)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows junction cleanup verification",
)
def test_cleanup_removes_junction_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    seeded = _seed_dependency_dir(source, "node_modules", "fake-binary", "hello\n")
    council_root = source / ".council"

    materialization = _materialize_with_copy(
        source=source,
        council_root=council_root,
        delegation_id="cleanup_test",
    )
    junction = materialization.workspace_path / "node_modules"
    assert junction.exists()

    cleanup_workspace(source, materialization.workspace_path, materialization.effective_strategy)

    # Workspace gone:
    assert not materialization.workspace_path.exists()
    # Real source dependency intact:
    assert seeded.exists()
    assert seeded.read_text(encoding="utf-8") == "hello\n"


def test_git_worktree_strategy_also_links_dependencies(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    # Initialize a tiny git repo so git_worktree strategy is viable.
    (source / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "init"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "councilflow@example.com"],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "CouncilFlow Test"],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "add", "README.md"],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "commit", "-m", "seed"],
        check=True, capture_output=True, text=True,
    )

    # node_modules is .gitignored so it stays outside HEAD, matching the
    # chess-project reproduction that exposed this bug.
    (source / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _seed_dependency_dir(source, "node_modules", "eslint", "#!/node\n")

    council_root = source / ".council"
    isolated = IsolatedWorkspace(
        strategy="git_worktree",
        dependency_symlinks=list(DEFAULT_DEPENDENCY_SYMLINKS),
    )
    materialization = materialize_workspace(
        project_root=source,
        council_root=council_root,
        delegation_id="git_worktree_smoke",
        isolated=isolated,
    )

    try:
        assert materialization.effective_strategy == "git_worktree"
        workspace_eslint = materialization.workspace_path / "node_modules" / ".bin" / "eslint"
        assert workspace_eslint.exists(), (
            "node_modules should be linked into the git_worktree workspace"
        )
        assert workspace_eslint.read_text(encoding="utf-8") == "#!/node\n"
    finally:
        cleanup_workspace(
            source, materialization.workspace_path, materialization.effective_strategy
        )
        assert (source / "node_modules" / ".bin" / "eslint").exists()
