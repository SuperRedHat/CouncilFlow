"""Path helpers for the .council local state layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CouncilPaths:
    """Resolved paths for the standard CouncilFlow state layout."""

    project_root: Path
    council_root: Path
    config: Path
    state: Path
    plans: Path
    discuss: Path
    delegations: Path
    runs: Path
    transcripts: Path
    artifacts: Path

    def directories(self) -> tuple[Path, ...]:
        """Return every directory that should exist under .council."""

        return (
            self.council_root,
            self.plans,
            self.discuss,
            self.delegations,
            self.runs,
            self.transcripts,
            self.artifacts,
        )


def build_council_paths(project_root: Path) -> CouncilPaths:
    """Build the canonical .council path layout for a project root."""

    resolved_root = project_root.resolve()
    council_root = resolved_root / ".council"
    return CouncilPaths(
        project_root=resolved_root,
        council_root=council_root,
        config=council_root / "config.yaml",
        state=council_root / "state.json",
        plans=council_root / "plans",
        discuss=council_root / "discuss",
        delegations=council_root / "delegations",
        runs=council_root / "runs",
        transcripts=council_root / "transcripts",
        artifacts=council_root / "artifacts",
    )


def ensure_council_paths(paths: CouncilPaths) -> CouncilPaths:
    """Create the standard .council directory layout if it is missing."""

    for directory in paths.directories():
        directory.mkdir(parents=True, exist_ok=True)
    return paths

