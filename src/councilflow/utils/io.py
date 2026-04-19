"""Sidecar workspace materialization and controlled import-back helpers."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from councilflow.models.delegation import (
    ExecutionGuardrails,
    IsolatedWorkspace,
    WorkspaceFileChange,
)
from councilflow.utils.logging import get_logger

_logger = get_logger(__name__)

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


@dataclass(frozen=True)
class WorkspaceBaseline:
    """File-level snapshot of a workspace taken right after materialization.

    ``detect_workspace_changes`` compares this baseline against the workspace
    state AFTER the provider has run, so the manifest reflects only what the
    sidecar itself did. Comparing against the host source tree instead (the
    previous implementation) incorrectly flagged the user's uncommitted source
    files as ``deleted`` and caused real data loss — see TASK-058.

    ``hashes`` maps posix-style relative paths to SHA-256 hex digests.
    """

    hashes: dict[str, str]


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
                # `git worktree add HEAD` only checks out the committed tree,
                # so untracked new files and working-tree modifications stay
                # invisible to the sidecar. That's fine for a pure CI-style
                # checkout but wrong for CouncilFlow delegations: the
                # implementer stage imports new files into the host working
                # tree (still untracked) and the following tester stage needs
                # to verify THAT code, not the last committed snapshot. Mirror
                # the host's uncommitted state onto the fresh worktree so
                # tester / reviewer see what the controller just produced.
                # See TASK-007A post-mortem / 0.1.2 release notes.
                _overlay_uncommitted_files(
                    project_root=project_root,
                    workspace_path=workspace_path,
                    exclude_patterns=isolated.exclude_patterns,
                )
                _link_dependency_dirs(
                    source=project_root,
                    destination=workspace_path,
                    dependency_symlinks=isolated.dependency_symlinks,
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
    _link_dependency_dirs(
        source=project_root,
        destination=workspace_path,
        dependency_symlinks=isolated.dependency_symlinks,
    )
    return WorkspaceMaterialization(
        workspace_path=workspace_path,
        effective_strategy="copy",
    )


def _link_dependency_dirs(
    *,
    source: Path,
    destination: Path,
    dependency_symlinks: list[str],
) -> None:
    """Expose source's dependency directories inside the workspace via
    junctions (Windows) or symlinks (Unix) so tester stages can resolve
    package-manager binaries without paying the materialize copy cost.

    The sidecar is expected to treat these as read-only shared references:
    any write via the junction lands in the host project. Errors are logged
    and then swallowed — a missing or unlinkable dependency should not abort
    the whole materialization.
    """

    for name in dependency_symlinks:
        if not name or name in {".", ".."}:
            continue
        src_path = source / name
        if not src_path.exists() or not src_path.is_dir():
            continue
        dst_path = destination / name
        if dst_path.exists() or dst_path.is_symlink():
            # Prefer whatever materialize produced (copy may have included a
            # selected subset); do not overwrite it with a symlink.
            continue
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _logger.debug("materialize.symlink_parent_mkdir_failed name=%s reason=%s", name, exc)
            continue

        linked = False
        if sys.platform == "win32":
            # Directory junctions work without admin on NTFS; fall back to
            # os.symlink if junction creation fails.
            try:
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(dst_path), str(src_path)],
                    capture_output=True,
                    check=True,
                    text=True,
                )
                linked = True
            except (subprocess.CalledProcessError, OSError) as exc:
                _logger.debug(
                    "materialize.junction_failed name=%s reason=%s",
                    name,
                    exc,
                )

        if not linked:
            try:
                os.symlink(src_path, dst_path, target_is_directory=True)
                linked = True
            except OSError as exc:
                _logger.debug(
                    "materialize.symlink_failed name=%s reason=%s",
                    name,
                    exc,
                )

        if linked:
            _logger.info(
                "materialize.dependency_linked name=%s workspace=%s",
                name,
                str(dst_path),
            )


def _overlay_uncommitted_files(
    *,
    project_root: Path,
    workspace_path: Path,
    exclude_patterns: list[str],
) -> None:
    """Mirror host uncommitted state onto a freshly-created git worktree.

    `git worktree add --detach HEAD` gives us the committed tree. That omits:

    * Untracked new files — things the implementer or fixer stage imported
      back into the host source but the user hasn't staged / committed yet.
    * Modified tracked files — edits to existing files that live only in the
      working tree.
    * Deletions pending commit — files removed from the host working tree
      but still present at HEAD.

    Without this overlay, a tester / reviewer stage that fires after an
    uncommitted implementer output ends up testing the last commit, not the
    code under review. The 0.1.2 fix copies untracked + modified files into
    the worktree and removes deleted ones, so every delegation phase sees
    the same source the controller does. ``exclude_patterns`` (from the
    IsolatedWorkspace config) filters on top of .gitignore so guarded paths
    like ``.council/**`` and ``.claude/**`` still stay out even if they
    escaped gitignore.
    """

    def _git_lines(*args: str) -> list[str]:
        completed = subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            return []
        return [line.strip() for line in completed.stdout.splitlines() if line.strip()]

    untracked = _git_lines("ls-files", "--others", "--exclude-standard")

    modified: list[str] = []
    deleted: list[str] = []
    for raw in _git_lines("diff", "--name-status", "HEAD"):
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status_code = parts[0]
        # Diff-filter codes we care about:
        #   M  modified (overlay new content)
        #   A  added in index (overlay — not yet committed at HEAD)
        #   T  type changed (overlay as modified)
        #   D  deleted in working tree (remove from worktree copy of HEAD)
        #   R  rename — last path is the new name; the old path is gone at
        #      HEAD in the new worktree already, so we only need to overlay
        #      the new path. git emits `R100\told\tnew`; take parts[-1].
        #   C  copy — overlay the new path.
        if status_code.startswith("D"):
            deleted.append(parts[-1])
        else:
            modified.append(parts[-1])

    overlaid: list[str] = []
    for rel_path in (*untracked, *modified):
        posix_path = rel_path.replace("\\", "/")
        if _should_exclude(posix_path, exclude_patterns):
            continue
        src = project_root / posix_path
        if not src.is_file():
            continue
        dst = workspace_path / posix_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        overlaid.append(posix_path)

    removed: list[str] = []
    for rel_path in deleted:
        posix_path = rel_path.replace("\\", "/")
        if _should_exclude(posix_path, exclude_patterns):
            continue
        dst = workspace_path / posix_path
        if dst.is_file() or dst.is_symlink():
            try:
                dst.unlink()
                removed.append(posix_path)
            except OSError as exc:
                _logger.debug(
                    "materialize.overlay_delete_failed path=%s reason=%s",
                    posix_path,
                    exc,
                )

    if overlaid or removed:
        _logger.info(
            "materialize.overlay workspace=%s copied=%d removed=%d",
            str(workspace_path),
            len(overlaid),
            len(removed),
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


def _iter_workspace_files(workspace_path: Path) -> list[tuple[Path, str]]:
    """Yield (absolute_path, posix_relative_str) for regular files in the
    workspace, skipping symlinks and _SCAN_SKIP_PATTERNS.

    Symlinks / Windows junctions are skipped by design so that the
    dependency-symlink feature (TASK-057) does not cause the scanner to walk
    into the real source ``node_modules`` / ``.venv`` tree across the link.
    """

    skip_patterns = list(_SCAN_SKIP_PATTERNS)
    entries: list[tuple[Path, str]] = []
    for candidate in workspace_path.rglob("*"):
        try:
            if candidate.is_symlink() or _is_windows_junction(candidate):
                continue
            if not candidate.is_file():
                continue
        except OSError:
            continue
        relative = candidate.relative_to(workspace_path)
        relative_str = str(relative).replace("\\", "/")
        if _should_exclude(relative_str, skip_patterns):
            continue
        entries.append((candidate, relative_str))
    return entries


def snapshot_workspace_baseline(workspace_path: Path) -> WorkspaceBaseline:
    """Capture the set of files (and their hashes) in the workspace right
    after materialization so detect_workspace_changes can later tell which
    paths the sidecar added / modified / deleted."""

    hashes: dict[str, str] = {}
    for path, relative in _iter_workspace_files(workspace_path):
        try:
            hashes[relative] = _file_hash(path)
        except (OSError, PermissionError):
            continue
    return WorkspaceBaseline(hashes=hashes)


def detect_workspace_changes(
    baseline: WorkspaceBaseline,
    workspace_path: Path,
) -> list[WorkspaceFileChange]:
    """Diff the workspace AFTER the provider ran against the BASELINE taken
    right after materialization.

    Only sidecar-driven changes end up in the manifest — host source files
    that were never in the workspace to begin with are invisible here, which
    closes the TASK-058 data-loss window where uncommitted source files got
    imported back as ``deleted``.
    """

    changes: list[WorkspaceFileChange] = []
    current_hashes: dict[str, str] = {}
    current_sizes: dict[str, int] = {}

    for path, relative in _iter_workspace_files(workspace_path):
        try:
            current_hashes[relative] = _file_hash(path)
            current_sizes[relative] = path.stat().st_size
        except (OSError, PermissionError):
            continue

    for relative, current_hash in current_hashes.items():
        baseline_hash = baseline.hashes.get(relative)
        byte_size = current_sizes.get(relative, 0)
        if baseline_hash is None:
            changes.append(
                WorkspaceFileChange(
                    path=relative,
                    change_type="added",
                    byte_size=byte_size,
                )
            )
        elif baseline_hash != current_hash:
            changes.append(
                WorkspaceFileChange(
                    path=relative,
                    change_type="modified",
                    byte_size=byte_size,
                )
            )

    for relative in baseline.hashes:
        if relative not in current_hashes:
            changes.append(
                WorkspaceFileChange(
                    path=relative,
                    change_type="deleted",
                    byte_size=0,
                )
            )

    changes.sort(key=lambda change: (change.path, change.change_type))
    return changes


def classify_import_changes(
    changes: list[WorkspaceFileChange],
    guardrails: ExecutionGuardrails,
) -> list[WorkspaceFileChange]:
    """Mark each change as imported or rejected based on the guardrails manifest.

    Empty ``import_manifest.writable_globs`` means "import nothing": the caller
    must explicitly opt into which paths are allowed back. This is the safe
    default for tester / reviewer stages and was incorrectly lenient before
    TASK-058 (an empty list silently approved every change, which destroyed
    uncommitted user work during one real chess-project tester run).
    """

    classified: list[WorkspaceFileChange] = []
    manifest = guardrails.import_manifest
    writable = manifest.writable_globs
    total_bytes = 0
    imported_count = 0

    for change in changes:
        reason: str | None = None
        if _protected_path_covers(change.path, guardrails.protected_paths):
            reason = "path is covered by execution_guardrails.protected_paths"
        elif not _path_matches_any(change.path, writable):
            # Empty writable_globs rejects everything; explicit globs must
            # match, otherwise the change is rejected. Both arms go through
            # the same reason string so the manifest stays inspectable.
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

    # Unlink any top-level junctions / symlinks first so subsequent rmtree or
    # git worktree remove does not accidentally descend into the real source
    # dependency directory (e.g. deleting node_modules under source).
    _unlink_top_level_links(workspace_path)

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


def _unlink_top_level_links(workspace_path: Path) -> None:
    """Remove top-level junctions / symlinks inside the workspace without
    descending into their targets. Windows junctions and Unix symlinks both
    get detected via os.path.islink / junction heuristics."""

    try:
        entries = list(workspace_path.iterdir())
    except OSError:
        return

    for entry in entries:
        try:
            is_link = entry.is_symlink() or _is_windows_junction(entry)
        except OSError:
            is_link = False
        if not is_link:
            continue
        try:
            if sys.platform == "win32":
                # For junctions on Windows, os.rmdir unlinks without following.
                os.rmdir(entry)
            else:
                entry.unlink()
        except OSError as exc:
            _logger.debug(
                "cleanup.unlink_top_level_failed entry=%s reason=%s",
                entry,
                exc,
            )


def _is_windows_junction(path: Path) -> bool:
    """Best-effort junction detection for Windows NTFS directories."""

    if sys.platform != "win32":
        return False
    try:
        attrs = os.stat(path, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    reparse_flag = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
    return bool(attrs & reparse_flag)


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
