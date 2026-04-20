#!/usr/bin/env python3
"""Ceremony-token baseline measurement for CouncilFlow workflows.

Analyzes `.council/delegations/<id>/` directories to quantify how many
tokens are spent on workflow "ceremony" — the overhead introduced by
the stage machine (handoff writes + artifact reads + per-stage context
re-establishment) — versus actual delegated work.

Deterministic: same input → same token counts. Uses `tiktoken` when
available for accurate counts, falls back to char/4 heuristic otherwise
(noted explicitly in the report).

Usage::

    python scripts/measure_ceremony_tokens.py \\
        --input .council/delegations/ \\
        --output docs/ceremony-baseline-<date>.md

    python scripts/measure_ceremony_tokens.py --input <dir> --dry-run

Exit codes: 0 success, 1 usage error, 2 input error, 3 I/O error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tokenizer abstraction
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised via integration
    import tiktoken  # type: ignore
    _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
    TOKENIZER = "tiktoken:cl100k_base"
except Exception:  # noqa: BLE001 - tiktoken is optional
    _TIKTOKEN_ENCODING = None
    TOKENIZER = "fallback:chars/4"


def count_tokens(text: str) -> int:
    """Return a deterministic token count for `text`.

    Uses `tiktoken` when available (cl100k_base encoding, same family as
    modern OpenAI/Claude models), falls back to `len(text) // 4` which
    underestimates ~10-15% but is stable.
    """

    if not text:
        return 0
    if _TIKTOKEN_ENCODING is not None:
        return len(_TIKTOKEN_ENCODING.encode(text))
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ArtifactMeasurement:
    path: str
    role: str | None
    kind: str  # "handoff" / "result" / "record" / "other"
    bytes: int
    tokens: int


@dataclass
class DelegationMeasurement:
    delegation_id: str
    dir_path: str
    role: str | None
    target_model: str | None
    status: str | None  # "completed" / "local_execution" / "failed" / ...
    via_sidecar: bool | None
    artifacts: list[ArtifactMeasurement] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(a.tokens for a in self.artifacts)

    @property
    def handoff_tokens(self) -> int:
        return sum(a.tokens for a in self.artifacts if a.kind == "handoff")

    @property
    def result_tokens(self) -> int:
        return sum(a.tokens for a in self.artifacts if a.kind == "result")


@dataclass
class AggregateReport:
    tokenizer: str
    scanned_inputs: list[str]
    delegations: list[DelegationMeasurement]

    @property
    def total_delegations(self) -> int:
        return len(self.delegations)

    @property
    def total_tokens(self) -> int:
        return sum(d.total_tokens for d in self.delegations)

    @property
    def total_handoff_tokens(self) -> int:
        return sum(d.handoff_tokens for d in self.delegations)

    @property
    def total_result_tokens(self) -> int:
        return sum(d.result_tokens for d in self.delegations)

    @property
    def local_execution_count(self) -> int:
        return sum(1 for d in self.delegations if (d.status or "").lower() == "local_execution")

    @property
    def delegated_count(self) -> int:
        return sum(1 for d in self.delegations if d.via_sidecar is True)

    @property
    def role_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for d in self.delegations:
            role = d.role or "<unknown>"
            dist[role] = dist.get(role, 0) + 1
        return dist

    @property
    def model_distribution(self) -> dict[str, int]:
        dist: dict[str, int] = {}
        for d in self.delegations:
            model = d.target_model or "<unknown>"
            dist[model] = dist.get(model, 0) + 1
        return dist

    @property
    def ceremony_ratio_pct(self) -> float:
        """Handoff tokens as share of total — a proxy for ceremony cost.

        Handoff payloads are the "context re-establishment" tax each stage
        pays: objective + constraints + relevant files summary + prior
        artifact references. result.md is the actual delegated work.
        """

        if self.total_tokens == 0:
            return 0.0
        return 100.0 * self.total_handoff_tokens / self.total_tokens

    @property
    def reread_estimate_tokens(self) -> int:
        """Estimate of tokens spent re-reading artifacts across same-model chains.

        Heuristic: for each consecutive pair of `local_execution` delegations
        (same controller, no cross-model switch), the later stage's handoff
        typically includes a `--required-artifact` reference to the prior
        stage's result. That reference plus the controller's working-memory
        reload costs ~= the prior stage's result token count.
        """

        total = 0
        prev_result: DelegationMeasurement | None = None
        for d in self.delegations:
            if (d.status or "").lower() == "local_execution":
                if prev_result is not None and prev_result.result_tokens > 0:
                    total += prev_result.result_tokens
                prev_result = d
            else:
                prev_result = None
        return total


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


_HANDOFF_PATTERNS = ("handoff.yaml", "handoff.yml", "handoff.json")
_RESULT_PATTERNS = ("result.md", "result.json")
_RECORD_PATTERNS = ("record.json",)


def _classify(name: str) -> str:
    lower = name.lower()
    if any(lower == p for p in _HANDOFF_PATTERNS):
        return "handoff"
    if any(lower == p for p in _RESULT_PATTERNS):
        return "result"
    if any(lower == p for p in _RECORD_PATTERNS):
        return "record"
    if lower.endswith(".md"):
        return "result"
    return "other"


_ROLE_FROM_HANDOFF = re.compile(r"^role:\s*['\"]?(\w+)['\"]?", re.MULTILINE)
_MODEL_FROM_HANDOFF = re.compile(r"^(?:target_model|model):\s*['\"]?([\w\-]+)['\"]?", re.MULTILINE)
_STATUS_FROM_RECORD = re.compile(r'"status"\s*:\s*"(\w+)"')
_VIA_SIDECAR_FROM_RECORD = re.compile(r'"via_sidecar"\s*:\s*(true|false)', re.IGNORECASE)


_MetadataTuple = tuple[str | None, str | None, str | None, bool | None]


def _extract_metadata(
    artifacts: list[ArtifactMeasurement], root: Path
) -> _MetadataTuple:
    """Scan handoff/record files for role / model / status / via_sidecar."""
    role = model = status = None
    via_sidecar: bool | None = None

    for art in artifacts:
        p = root / art.path
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if art.kind == "handoff":
            m = _ROLE_FROM_HANDOFF.search(text)
            if m and not role:
                role = m.group(1).strip()
            m = _MODEL_FROM_HANDOFF.search(text)
            if m and not model:
                model = m.group(1).strip()
        if art.kind == "record":
            m = _STATUS_FROM_RECORD.search(text)
            if m and not status:
                status = m.group(1)
            m = _VIA_SIDECAR_FROM_RECORD.search(text)
            if m and via_sidecar is None:
                via_sidecar = m.group(1).lower() == "true"

    return role, model, status, via_sidecar


def scan_delegation_dir(dir_path: Path) -> DelegationMeasurement:
    if not dir_path.is_dir():
        raise FileNotFoundError(f"not a directory: {dir_path}")

    artifacts: list[ArtifactMeasurement] = []
    for entry in sorted(dir_path.iterdir()):
        if not entry.is_file():
            continue
        kind = _classify(entry.name)
        try:
            data = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            data = ""
        rel = entry.name
        artifacts.append(
            ArtifactMeasurement(
                path=rel,
                role=None,  # filled in below
                kind=kind,
                bytes=len(data.encode("utf-8", errors="replace")),
                tokens=count_tokens(data),
            )
        )

    role, model, status, via_sidecar = _extract_metadata(artifacts, dir_path)
    for art in artifacts:
        art.role = role

    return DelegationMeasurement(
        delegation_id=dir_path.name,
        dir_path=str(dir_path),
        role=role,
        target_model=model,
        status=status,
        via_sidecar=via_sidecar,
        artifacts=artifacts,
    )


def scan_input(input_path: Path) -> list[DelegationMeasurement]:
    if not input_path.exists():
        raise FileNotFoundError(f"input path does not exist: {input_path}")

    out: list[DelegationMeasurement] = []
    if input_path.is_dir():
        subs = [p for p in sorted(input_path.iterdir()) if p.is_dir()]
        _known = (*_HANDOFF_PATTERNS, *_RESULT_PATTERNS)
        if subs and any((s / f).exists() for s in subs for f in _known):
            # looks like a root containing multiple delegations
            for sub in subs:
                try:
                    out.append(scan_delegation_dir(sub))
                except FileNotFoundError:
                    continue
        else:
            # a single delegation dir
            out.append(scan_delegation_dir(input_path))
    else:
        raise NotADirectoryError(f"expected a directory: {input_path}")

    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(report: AggregateReport) -> str:
    lines: list[str] = []
    lines.append("# CouncilFlow Ceremony-Token Baseline Report\n")
    lines.append(f"- **Tokenizer**: `{report.tokenizer}`")
    lines.append(f"- **Scanned inputs**: {', '.join(report.scanned_inputs) or '(none)'}")
    lines.append(f"- **Total delegations**: {report.total_delegations}")
    lines.append("")

    lines.append("## Totals\n")
    lines.append(f"- Total tokens across all artifacts: **{report.total_tokens}**")
    lines.append(f"- Handoff tokens (ceremony proxy): **{report.total_handoff_tokens}**")
    lines.append(f"- Result tokens (actual work): **{report.total_result_tokens}**")
    lines.append(f"- Ceremony ratio (handoff / total): **{report.ceremony_ratio_pct:.1f}%**")
    lines.append(f"- Estimated same-model reread tokens: **{report.reread_estimate_tokens}**")
    lines.append(f"- local_execution delegations: {report.local_execution_count}")
    lines.append(f"- sidecar-delegated delegations: {report.delegated_count}")
    lines.append("")

    lines.append("## Role distribution\n")
    for role, count in sorted(report.role_distribution.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{role}`: {count}")
    lines.append("")

    lines.append("## Model distribution\n")
    for model, count in sorted(report.model_distribution.items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{model}`: {count}")
    lines.append("")

    lines.append("## Per-delegation breakdown\n")
    lines.append("| ID | Role | Model | Status | Via Sidecar | Handoff | Result | Total |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for d in report.delegations:
        lines.append(
            f"| `{d.delegation_id}` | {d.role or '-'} | {d.target_model or '-'} | "
            f"{d.status or '-'} | {d.via_sidecar if d.via_sidecar is not None else '-'} | "
            f"{d.handoff_tokens} | {d.result_tokens} | {d.total_tokens} |"
        )
    lines.append("")

    lines.append("## Methodology\n")
    lines.append(
        "- **Tokenizer**: `tiktoken` with `cl100k_base` encoding when the package "
        "is installed; otherwise `len(text) // 4` heuristic (underestimates by "
        "~10-15% but stable across runs)."
    )
    lines.append(
        "- **Ceremony proxy**: the sum of tokens inside `handoff.yaml/json` files "
        "across all delegations. This captures the per-stage context "
        "re-establishment cost (objective + constraints + required artifact refs "
        "+ expected output + inputs summary)."
    )
    lines.append(
        "- **Reread estimate**: for each consecutive pair of `local_execution` "
        "delegations, the later stage's handoff references the prior stage's "
        "`result.md`; the controller re-tokenizes that result when planning the "
        "next stage. We attribute the prior stage's result-token count to this "
        "re-read. This *underestimates* if the controller also needs to re-read "
        "its own implementer artifact during tester/reviewer, and *overestimates* "
        "if the controller session's prompt cache keeps the prior result warm."
    )
    lines.append(
        "- **Uncertainty interval**: real token costs are within ±15% of the "
        "reported numbers under the heuristic tokenizer; under `tiktoken` the "
        "numbers track closely with what OpenAI/Claude charge."
    )
    lines.append(
        "- **Not counted**: prompts generated by CouncilFlow's Python layer (role "
        "prompt templates, orchestrator framing), cross-model discuss summaries, "
        "and sidecar workspace materialize overhead."
    )
    return "\n".join(lines) + "\n"


def render_json(report: AggregateReport) -> str:
    payload: dict[str, Any] = {
        "tokenizer": report.tokenizer,
        "scanned_inputs": report.scanned_inputs,
        "summary": {
            "total_delegations": report.total_delegations,
            "total_tokens": report.total_tokens,
            "total_handoff_tokens": report.total_handoff_tokens,
            "total_result_tokens": report.total_result_tokens,
            "ceremony_ratio_pct": round(report.ceremony_ratio_pct, 2),
            "reread_estimate_tokens": report.reread_estimate_tokens,
            "local_execution_count": report.local_execution_count,
            "delegated_count": report.delegated_count,
            "role_distribution": report.role_distribution,
            "model_distribution": report.model_distribution,
        },
        "delegations": [
            {
                "delegation_id": d.delegation_id,
                "dir_path": d.dir_path,
                "role": d.role,
                "target_model": d.target_model,
                "status": d.status,
                "via_sidecar": d.via_sidecar,
                "handoff_tokens": d.handoff_tokens,
                "result_tokens": d.result_tokens,
                "total_tokens": d.total_tokens,
                "artifacts": [asdict(a) for a in d.artifacts],
            }
            for d in report.delegations
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="measure_ceremony_tokens",
        description="Baseline ceremony-token measurement for CouncilFlow delegations.",
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help=(
            "Path to a delegation directory or a root containing multiple "
            "delegations. Can be repeated."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown path. Companion JSON is written alongside with .json extension.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the report but do not write to disk. Print a summary to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    all_delegations: list[DelegationMeasurement] = []
    scanned: list[str] = []
    for raw in args.input:
        path = Path(raw).resolve()
        try:
            delegations = scan_input(path)
        except FileNotFoundError as err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        except NotADirectoryError as err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        scanned.append(str(path))
        all_delegations.extend(delegations)

    if not all_delegations:
        print("warning: no delegations found under provided inputs", file=sys.stderr)

    report = AggregateReport(
        tokenizer=TOKENIZER,
        scanned_inputs=scanned,
        delegations=all_delegations,
    )

    md = render_markdown(report)
    js = render_json(report)

    if args.dry_run:
        print(f"[dry-run] tokenizer={report.tokenizer}")
        print(
            f"[dry-run] delegations={report.total_delegations} "
            f"total_tokens={report.total_tokens}"
        )
        print(
            f"[dry-run] ceremony_ratio_pct={report.ceremony_ratio_pct:.1f}% "
            f"reread_estimate={report.reread_estimate_tokens}"
        )
        print(f"[dry-run] would write markdown to {args.output or '<not specified>'}")
        return 0

    if not args.output:
        # Default: print markdown to stdout when output not specified
        sys.stdout.write(md)
        return 0

    out_md = Path(args.output)
    out_json = out_md.with_suffix(".json")
    try:
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(md, encoding="utf-8")
        out_json.write_text(js, encoding="utf-8")
    except OSError as err:
        print(f"error writing report: {err}", file=sys.stderr)
        return 3

    print(f"wrote markdown report: {out_md}")
    print(f"wrote json data:       {out_json}")
    print(f"tokenizer:             {report.tokenizer}")
    print(f"delegations:           {report.total_delegations}")
    print(f"total tokens:          {report.total_tokens}")
    print(f"ceremony ratio:        {report.ceremony_ratio_pct:.1f}%")
    print(f"reread estimate:       {report.reread_estimate_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
