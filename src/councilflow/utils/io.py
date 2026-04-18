"""Sidecar workspace materialization and controlled import-back helpers."""

from __future__ import annotations

import fnmatch
import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from councilflow.models.delegation import (
    ExecutionGuardrails,
    IsolatedWorkspace,
    WorkspaceFileChange,
)

# Performance-only skip for the change detector. Workflow state paths such as
# .claude/skills, .workflow-core, .council deliberately stay visible here so
# sidecar attempts to modify them can be classified and rejected by the
# protected_paths guardrail during classify_import_changes().
_SCAN_SKIP_PATTERNS: tuple[str, ...] = (
    ".git/**",
    "__pycache__/**",
    ".venv/**",
    "node_modules/**",
    "*.pyc",
)


@dataclass(frozen=True)
class WorkspaceMaterialization:
    """Concrete result of a workspace materialization attempt."""

    workspace_path: Path
    effective_strategy: str


def _path_matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _protected_path_covers(relative_path: str, protected_paths: list[str]) -> bool:
    normalized = relative_path.replace("\\", "/")
    for protected in protected_paths:
        protected_norm = protected.replace("\\", "/").rstrip("/")
        if normalized == protected_norm or normalized.startswith(protected_norm + "/"):
            return True
    return False


def _should_exclude(relative_path: str, exclude_patterns: list[str]) -> bool:
    normalized = relative_path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in exclude_patterns)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_workspace(
    project_root: Path,
    council_root: Path,
    delegation_id: str,
    isolated: IsolatedWorkspace,
) -> WorkspaceMaterialization:
    """Materialize a sidecar workspace according to the requested isolation strategy.

    The effective strategy may differ from the requested one when the requested
    strategy is not viable for the host environment (for example, git_worktree
    on a non-git directory falls back to copy).
    """

    requested = isolated.strategy
    if requested == "none":
        return WorkspaceMaterialization(
            workspace_path=project_root,
            effective_strategy="none",
        )

    workspace_path = council_root / "workspaces" / delegation_id
    if workspace_path.exists():
        shutil.rmtree(workspace_path)

    if requested == "git_worktree":
        git_dir = project_root / ".git"
        if git_dir.exists():
            try:
                subprocess.run(
                    ["git", "-C", str(project_root), "worktree", "add",
                     "--detach", str(workspace_path), "HEAD"],
                    capture_output=True,
                    check=True,
                    text=True,
                )
                return WorkspaceMaterialization(
                    workspace_path=workspace_path,
                    effective_strategy="git_worktree",
                )
            except (subprocess.CalledProcessError, OSError):
                pass  # fall through to copy

    # Copy strategy (explicit or fallback from git_worktree).
    _copy_project_tree(
        source=project_root,
        destination=workspace_path,
        include_patterns=isolated.include_patterns,
        exclude_patterns=isolated.exclude_patterns,
    )
    return WorkspaceMaterialization(
        workspace_path=workspace_path,
        effective_strategy="copy",
    )


def _copy_project_tree(
    *,
    source: Path,
    destination: Path,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for src_path in source.rglob("*"):
        if not src_path.is_file():
            continue
        relative = src_path.relative_to(source)
        relative_str = str(relative).replace("\\", "/")
        if _should_exclude(relative_str, exclude_patterns):
            continue
        if include_patterns and not _path_matches_any(relative_str, include_patterns):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, target)


def detect_workspace_changes(
    source_root: Path,
    workspace_path: Path,
    exclude_patterns: list[str] | None = None,
) -> list[WorkspaceFileChange]:
    """Return every file that differs between the source root and the workspace.

    The workspace scan uses only _SCAN_SKIP_PATTERNS (performance-only skips)
    so sidecar attempts to write into workflow state paths remain visible for
    the classifier to reject.

    The source scan uses the full `exclude_patterns` (plus _SCAN_SKIP_PATTERNS)
    because any path the materialization explicitly excluded was never present
    in the workspace to begin with, and must not be treated as a sidecar-driven
    deletion.

    Returns an empty list when workspace_path equals source_root (strategy=none).
    """

    if workspace_path == source_root:
        return []

    scan_skip = list(_SCAN_SKIP_PATTERNS)
    source_excludes = list(_SCAN_SKIP_PATTERNS)
    if exclude_patterns:
        source_excludes.extend(exclude_patterns)

    changes: list[WorkspaceFileChange] = []

    # Modified / added
    for workspace_file in workspace_path.rglob("*"):
        if not workspace_file.is_file():
            continue
        relative = workspace_file.relative_to(workspace_path)
        relative_str = str(relative).replace("\\", "/")
        if _should_exclude(relative_str, scan_skip):
            continue
        source_file = source_root / relative
        try:
            byte_size = workspace_file.stat().st_size
        except OSError:
            continue
        if not source_file.exists() or not source_file.is_file():
            changes.append(
                WorkspaceFileChange(
                    path=relative_str,
                    change_type="added",
                    byte_size=byte_size,
                )
            )
            continue
        try:
            if _file_hash(workspace_file) != _file_hash(source_file):
                changes.append(
                    WorkspaceFileChange(
                        path=relative_str,
                        change_type="modified",
                        byte_size=byte_size,
                    )
                )
        except (OSError, PermissionError):
            continue

    # Deleted
    for source_file in source_root.rglob("*"):
        if not source_file.is_file():
            continue
        relative = source_file.relative_to(source_root)
        relative_str = str(relative).replace("\\", "/")
        if _should_exclude(relative_str, source_excludes):
            continue
        workspace_file = workspace_path / relative
        if not workspace_file.exists():
            try:
                size = source_file.stat().st_size
            except OSError:
                continue
            changes.append(
                WorkspaceFileChange(
                    path=relative_str,
                    change_type="deleted",
                    byte_size=size,
                )
            )

    changes.sort(key=lambda change: (change.path, change.change_type))
    return changes


def classify_import_changes(
    changes: list[WorkspaceFileChange],
    guardrails: ExecutionGuardrails,
) -> list[WorkspaceFileChange]:
    """Mark each change as imported or rejected based on the guardrails manifest."""

    classified: list[WorkspaceFileChange] = []
    manifest = guardrails.import_manifest
    writable = manifest.writable_globs
    total_bytes = 0
    imported_count = 0

    for change in changes:
        reason: str | None = None
        if _protected_path_covers(change.path, guardrails.protected_paths):
            reason = "path is covered by execution_guardrails.protected_paths"
        elif writable and not _path_matches_any(change.path, writable):
            reason = "path is not matched by import_manifest.writable_globs"
        elif imported_count >= manifest.max_file_count:
            reason = "import_manifest.max_file_count budget exhausted"
        elif total_bytes + change.byte_size > manifest.max_total_bytes:
            reason = "import_manifest.max_total_bytes budget exhausted"

        if reason is None:
            imported_count += 1
            total_bytes += change.byte_size
            classified.append(change.model_copy(update={"imported": True}))
        else:
            classified.append(
                change.model_copy(update={"imported": False, "rejection_reason": reason})
            )
    return classified


def apply_import_changes(
    changes: list[WorkspaceFileChange],
    source_root: Path,
    workspace_path: Path,
) -> None:
    """Copy imported files from the workspace back to the source root."""

    if workspace_path == source_root:
        return

    for change in changes:
        if not change.imported:
            continue
        target = source_root / change.path
        if change.change_type == "deleted":
            if target.exists():
                target.unlink()
            continue
        workspace_file = workspace_path / change.path
        if not workspace_file.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(workspace_file, target)


def cleanup_workspace(
    project_root: Path,
    workspace_path: Path,
    effective_strategy: str,
) -> None:
    """Remove the sidecar workspace (best-effort)."""

    if workspace_path == project_root or not workspace_path.exists():
        return

    if effective_strategy == "git_worktree":
        try:
            subprocess.run(
                ["git", "-C", str(project_root), "worktree", "remove", "--force",
                 str(workspace_path)],
                capture_output=True,
                check=True,
                text=True,
            )
            return
        except (subprocess.CalledProcessError, OSError):
            pass  # fall through to rmtree

    try:
        shutil.rmtree(workspace_path, ignore_errors=True)
    except OSError:
        pass


def summarize_import_outcome(
    changes: list[WorkspaceFileChange],
) -> tuple[str, str | None]:
    """Return (outcome, rejected_reason) derived from the classified manifest."""

    if not changes:
        return ("none", None)

    imported = [change for change in changes if change.imported]
    rejected = [change for change in changes if not change.imported]

    if not rejected:
        return ("applied", None)
    if not imported:
        first_reason = rejected[0].rejection_reason or "all changes rejected"
        return ("rejected", first_reason)
    summary = f"{len(rejected)} change(s) rejected: " + ", ".join(
        f"{change.path} ({change.rejection_reason})" for change in rejected[:3]
    )
    return ("partial", summary)
