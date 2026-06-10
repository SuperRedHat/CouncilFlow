"""0.1.2 — materialize_workspace overlays host uncommitted state onto the worktree.

Regression coverage for the TASK-007A incident: a delegated tester stage
ran against a freshly-created git worktree whose ``git worktree add HEAD``
checkout lacked the implementer's just-produced untracked files. The fix
copies untracked + modified files over and removes deleted ones, so every
delegation phase sees the code the controller is actually iterating on.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from councilflow.models.delegation import (
    DEFAULT_ISOLATION_EXCLUDE_PATTERNS,
    IsolatedWorkspace,
)
from councilflow.utils.io import cleanup_workspace, materialize_workspace


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@councilflow.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "CouncilFlow Test"],
        check=True,
        capture_output=True,
    )


def _commit_all(root: Path, message: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "add", "-A"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message],
        check=True,
        capture_output=True,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _materialize_git_worktree(
    source: Path,
    council_root: Path,
    delegation_id: str,
) -> Path:
    isolated = IsolatedWorkspace(
        strategy="git_worktree",
        include_patterns=[],
        exclude_patterns=list(DEFAULT_ISOLATION_EXCLUDE_PATTERNS),
        dependency_symlinks=[],
    )
    result = materialize_workspace(
        project_root=source,
        council_root=council_root,
        delegation_id=delegation_id,
        isolated=isolated,
    )
    assert result.effective_strategy == "git_worktree", (
        "these tests only exercise the git_worktree overlay path; "
        f"got {result.effective_strategy!r}"
    )
    return result.workspace_path


def test_untracked_new_file_is_visible_in_worktree(tmp_path: Path) -> None:
    """The TASK-007A repro: implementer added a new file but it's still
    untracked in the host; tester must see it."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    untracked_rel = "src/feature/board-view.ts"
    _write(source / untracked_rel, "export const view = () => 42;\n")

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_untracked")
    try:
        overlaid = workspace_path / untracked_rel
        assert overlaid.is_file()
        assert overlaid.read_text(encoding="utf-8") == "export const view = () => 42;\n"
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_modified_tracked_file_uses_working_tree_content(tmp_path: Path) -> None:
    """Working-tree edits to a tracked file must overlay HEAD in the worktree."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    target_rel = "src/greet.ts"
    _write(source / target_rel, "export const greet = () => 'committed';\n")
    _commit_all(source, "chore: baseline")

    _write(source / target_rel, "export const greet = () => 'uncommitted edit';\n")

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_modified")
    try:
        overlaid = workspace_path / target_rel
        assert overlaid.read_text(encoding="utf-8") == (
            "export const greet = () => 'uncommitted edit';\n"
        )
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_locally_deleted_tracked_file_is_absent_from_worktree(tmp_path: Path) -> None:
    """If the user deleted a file locally (not yet committed), the sidecar
    must not surface the stale HEAD version."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    deleted_rel = "src/legacy.ts"
    _write(source / deleted_rel, "export const legacy = () => 0;\n")
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    (source / deleted_rel).unlink()

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_deleted")
    try:
        assert not (workspace_path / deleted_rel).exists()
        # untouched files still come through
        assert (workspace_path / "README.md").is_file()
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_gitignored_untracked_files_are_not_overlaid(tmp_path: Path) -> None:
    """Files matched by .gitignore must not be copied even though they are
    physically present in the host working tree."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    _write(source / ".gitignore", "secrets.env\n")
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    _write(source / "secrets.env", "API_KEY=do-not-leak\n")

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_ignored")
    try:
        assert not (workspace_path / "secrets.env").exists()
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_exclude_patterns_filter_stays_enforced(tmp_path: Path) -> None:
    """IsolatedWorkspace.exclude_patterns (e.g. .council/**) filters on top
    of .gitignore so workflow-only directories never leak into the sidecar."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    # Untracked entry that IS NOT in .gitignore but IS in exclude_patterns.
    forbidden_rel = ".claude/secrets.json"
    _write(source / forbidden_rel, "{\"token\": \"x\"}\n")

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_excluded")
    try:
        assert not (workspace_path / forbidden_rel).exists()
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_nested_untracked_directories_are_created(tmp_path: Path) -> None:
    """When the host has new files several levels deep, the worktree copy
    must create the intermediate directories."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    new_rel = "tests/unit/features/board-view/rules.spec.ts"
    _write(source / new_rel, "it('sanity', () => 1);\n")

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_nested")
    try:
        assert (workspace_path / new_rel).is_file()
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_overlay_handles_crlf_text_without_corruption(tmp_path: Path) -> None:
    """Windows line endings in the host working tree should survive the
    overlay bit-for-bit; shutil.copy2 uses binary mode so this should just
    work — pin it as a regression guard."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    rel = "src/note.txt"
    crlf_content = "first line\r\nsecond line\r\n"
    (source / rel).parent.mkdir(parents=True, exist_ok=True)
    (source / rel).write_bytes(crlf_content.encode("utf-8"))

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_crlf")
    try:
        assert (workspace_path / rel).read_bytes() == crlf_content.encode("utf-8")
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_overlay_is_noop_when_tree_is_clean(tmp_path: Path) -> None:
    """No uncommitted state means the overlay step adds nothing and removes
    nothing — existing behavior must remain bit-identical."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    rel = "src/greet.ts"
    _write(source / rel, "export const greet = () => 1;\n")
    _commit_all(source, "chore: baseline")

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_clean")
    try:
        # sanity: HEAD content still there, nothing extra was overlaid
        assert (workspace_path / rel).read_text(encoding="utf-8") == (
            "export const greet = () => 1;\n"
        )
        # No stray junk from the overlay path
        overlay_marker = workspace_path / ".councilflow_overlay"
        assert not overlay_marker.exists()
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


@pytest.mark.parametrize("sub", ["src/a.ts", "docs/readme.md"])
def test_overlay_copies_many_untracked_paths(tmp_path: Path, sub: str) -> None:
    """Parametric smoke that multiple untracked files land correctly."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    _write(source / sub, f"// content for {sub}\n")

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, f"del_{sub.replace('/', '_')}")
    try:
        assert (workspace_path / sub).is_file()
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")


def test_uncommitted_rename_removes_old_path_from_worktree(tmp_path: Path) -> None:
    """TASK-121: `git mv old new` (uncommitted) — HEAD still contains the old
    path, so the worktree checkout must have it REMOVED and the new path
    overlaid; otherwise the sidecar sees both modules side by side."""

    source = tmp_path / "repo"
    source.mkdir()
    _init_git_repo(source)
    _write(source / "src" / "old_name.ts", "export const v = 1;\n")
    _write(source / "README.md", "# base\n")
    _commit_all(source, "chore: baseline")

    subprocess.run(
        ["git", "-C", str(source), "mv", "src/old_name.ts", "src/new_name.ts"],
        check=True,
        capture_output=True,
    )

    council_root = source / ".council"
    workspace_path = _materialize_git_worktree(source, council_root, "del_rename")
    try:
        assert not (workspace_path / "src" / "old_name.ts").exists()
        assert (workspace_path / "src" / "new_name.ts").is_file()
    finally:
        cleanup_workspace(source, workspace_path, "git_worktree")
