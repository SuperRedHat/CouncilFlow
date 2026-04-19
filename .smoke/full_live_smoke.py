"""Full-stack smoke for CouncilFlow against D:/AIProjects/test/councilflow-smoke-2026-04-19.

Runs each scenario, collects pass/fail + evidence, prints a single JSON report at
the end. Scenarios mix:
  * real council CLI subprocesses (no external API use — we either force
    local_execution or trigger adapter_missing)
  * Python-level DelegationOrchestrator drives with fake providers
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path

REPO = Path("D:/project/CouncilFlow")
TEST_ROOT = Path("D:/AIProjects/test/councilflow-smoke-2026-04-19")

sys.path.insert(0, str(REPO / "src"))

from councilflow.config.loader import load_config  # noqa: E402
from councilflow.controller.delegation_orchestrator import (  # noqa: E402
    DelegationOrchestrator,
)
from councilflow.controller.host_context import detect_controller  # noqa: E402
from councilflow.controller.routing import build_route_decision  # noqa: E402
from councilflow.models.delegation import (  # noqa: E402
    DEFAULT_DEPENDENCY_SYMLINKS,
    DEFAULT_ISOLATION_EXCLUDE_PATTERNS,
    ExecutionGuardrails,
    ImportManifest,
    IsolatedWorkspace,
)
from councilflow.models.roles import (  # noqa: E402
    RoleName,
    resolve_adapter_model,
    validate_model_name,
)
from councilflow.providers.base import (  # noqa: E402
    CONTROLLER_ENV_KEYS,
    DELEGATED_STAGE_ENV_FLAG,
    ProviderRequest,
    ProviderResponse,
    build_sandboxed_env,
)
from councilflow.providers.registry import resolve_adapter  # noqa: E402
from councilflow.state.store import CouncilStateStore  # noqa: E402

RESULTS: dict[str, dict] = {}


def record(name: str, passed: bool, **details) -> None:
    RESULTS[name] = {"passed": bool(passed), **details}
    tag = "PASS" if passed else "FAIL"
    tail = " ".join(f"{k}={v!r}" for k, v in details.items() if k != "traceback")
    print(f"[{tag}] {name} {tail}")


@contextmanager
def env_overrides(**overrides):
    original = {k: os.environ.get(k) for k in overrides}
    for k, v in overrides.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, prev in original.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


def _scrub_controller_env(env: dict[str, str]) -> dict[str, str]:
    env = dict(env)
    for k in CONTROLLER_ENV_KEYS:
        env.pop(k, None)
    return env


def _run_council(args: list[str], *, env_extra: dict[str, str] | None = None,
                 strip_controllers: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if strip_controllers:
        env = _scrub_controller_env(env)
    if env_extra:
        env.update({k: v for k, v in env_extra.items() if v is not None})
    return subprocess.run(
        [sys.executable, "-m", "councilflow.cli.app", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        timeout=60,
    )


# ---------- Fake provider helpers ---------- #

class WriteProvider:
    model_name = "claude"

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.cwd: Path | None = None

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        self.cwd = Path(request.cwd) if request.cwd else None
        assert self.cwd is not None
        for rel, content in self.files.items():
            t = self.cwd / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(content, encoding="utf-8")
        return ProviderResponse(model="claude", content="ok")


class QuietProvider:
    model_name = "claude"

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(model="claude", content="quiet")


class CapturingProvider:
    model_name = "claude"

    def __init__(self) -> None:
        self.env_override: dict[str, str] | None = None
        self.cwd: str | None = None

    def ask(self, request: ProviderRequest) -> ProviderResponse:
        self.env_override = dict(request.env_override or {})
        self.cwd = request.cwd
        return ProviderResponse(model="claude", content="captured")


# ---------- Scenarios ---------- #

def s01_version() -> None:
    r = _run_council(["version"])
    record("S01_version", r.returncode == 0 and "0.1.2" in r.stdout, exit=r.returncode,
           out=r.stdout.strip()[:40])


def s02_config_bootstrap_creates_template() -> None:
    # Ensure no .council present
    council_dir = TEST_ROOT / ".council"
    if council_dir.exists():
        shutil.rmtree(council_dir)
    r = _run_council([
        "status", "--project-root", str(TEST_ROOT),
    ], env_extra={"CODEX_SHELL": "1"})
    cfg_exists = (TEST_ROOT / ".council" / "config.yaml").is_file()
    state_exists = (TEST_ROOT / ".council" / "state.json").is_file()
    record("S02_config_bootstrap", r.returncode == 0 and cfg_exists and state_exists,
           exit=r.returncode, cfg_exists=cfg_exists, state_exists=state_exists)


def s03_config_defaults_match_template() -> None:
    cfg = load_config(TEST_ROOT / ".council" / "config.yaml")
    template_roles_ok = cfg.roles.implementer == "claude" and cfg.roles.synthesizer == "codex"
    min_rounds_ok = cfg.discussion.min_rounds >= 1
    record("S03_config_defaults_match_template", template_roles_ok and min_rounds_ok,
           implementer=cfg.roles.implementer, synthesizer=cfg.roles.synthesizer,
           min_rounds=cfg.discussion.min_rounds, max_rounds=cfg.discussion.max_rounds)


def s04_set_controller_override_codex() -> None:
    cfg_path = TEST_ROOT / ".council" / "config.yaml"
    text = cfg_path.read_text(encoding="utf-8")
    text = text.replace("controller_override: null", "controller_override: codex")
    cfg_path.write_text(text, encoding="utf-8")
    after = load_config(cfg_path)
    record("S04_controller_override_codex", after.controller_override is not None,
           controller_override=str(after.controller_override))


def s05_route_local_execution() -> None:
    cfg = load_config(TEST_ROOT / ".council" / "config.yaml")
    with env_overrides(
        CODEX_SHELL="1", CODEX_THREAD_ID="smoke",
        CLAUDECODE=None, CLAUDE_CODE=None, CLAUDE_CODE_SHELL=None,
        CLAUDE_SHELL=None, CLAUDECODE_SHELL=None,
        GEMINI_CLI=None, GEMINI_CLI_SESSION=None, GEMINI_CLI_IDE_PID=None,
    ):
        ctx = detect_controller(config=cfg)
        d = build_route_decision(
            role=RoleName.REVIEWER,
            controller=ctx.controller,
            target_model=cfg.roles.for_role(RoleName.REVIEWER),
        )
    record("S05_route_local_execution", ctx.controller.value == "codex" and
           d.status == "local_execution", controller=ctx.controller.value,
           status=d.status, target=d.target_model)


def s06_route_delegated() -> None:
    cfg = load_config(TEST_ROOT / ".council" / "config.yaml")
    with env_overrides(
        CODEX_SHELL="1", CODEX_THREAD_ID="smoke",
        CLAUDECODE=None, CLAUDE_CODE=None, CLAUDE_CODE_SHELL=None,
        CLAUDE_SHELL=None, CLAUDECODE_SHELL=None,
        GEMINI_CLI=None, GEMINI_CLI_SESSION=None, GEMINI_CLI_IDE_PID=None,
    ):
        ctx = detect_controller(config=cfg)
        d = build_route_decision(
            role=RoleName.IMPLEMENTER,
            controller=ctx.controller,
            target_model=cfg.roles.for_role(RoleName.IMPLEMENTER),
        )
    record("S06_route_delegated", d.status == "delegated" and d.via_sidecar and
           d.target_model == "claude",
           status=d.status, via_sidecar=d.via_sidecar, target=d.target_model)


def s07_adapter_missing_failure_report() -> None:
    r = _run_council([
        "delegate", "--role", "reviewer", "--model", "clood",
        "--objective", "adapter_missing smoke",
        "--task-summary", "trigger adapter_missing",
        "--project-root", str(TEST_ROOT),
    ], env_extra={"CODEX_SHELL": "1"})
    payload = json.loads(r.stdout)
    err = payload.get("error") or {}
    record("S07_adapter_missing_failure_report",
           r.returncode == 1 and err.get("error_kind") == "adapter_missing"
           and err.get("delegation_id", "").startswith("del_"),
           exit=r.returncode, error_kind=err.get("error_kind"),
           has_delegation_id=bool(err.get("delegation_id")))


def s08_recursion_guard_blocks() -> None:
    r = _run_council([
        "delegate", "--role", "implementer",
        "--objective", "recurse",
        "--task-summary", "should be rejected",
        "--project-root", str(TEST_ROOT),
    ], env_extra={
        "COUNCILFLOW_DELEGATED_STAGE": "1",
        "COUNCILFLOW_DELEGATION_ID": "del_smoke_parent",
    })
    payload = json.loads(r.stdout)
    err = payload.get("error") or {}
    record("S08_recursion_guard_blocks", r.returncode == 2 and
           err.get("error_kind") == "recursive_workflow_violation" and
           err.get("delegation_id") == "del_smoke_parent",
           exit=r.returncode, error_kind=err.get("error_kind"),
           parent_id=err.get("delegation_id"))


def s09_status_allowed_in_delegated_stage() -> None:
    r = _run_council([
        "status", "--project-root", str(TEST_ROOT),
    ], env_extra={"COUNCILFLOW_DELEGATED_STAGE": "1", "CODEX_SHELL": "1"},
      strip_controllers=False)
    payload = json.loads(r.stdout)
    data = payload.get("data") or {}
    record("S09_status_allowed_in_delegated_stage",
           r.returncode == 0 and data.get("current_controller") == "codex",
           exit=r.returncode, current_controller=data.get("current_controller"))


def s10_discuss_same_controller_short_circuits() -> None:
    r = _run_council([
        "discuss", "How should we slice module boundaries?",
        "--models", "codex", "--project-root", str(TEST_ROOT),
    ], env_extra={"CODEX_SHELL": "1"})
    payload = json.loads(r.stdout)
    data = payload.get("data") or {}
    record("S10_discuss_same_controller_short_circuits",
           r.returncode == 0 and data.get("rounds_completed") == 0
           and "controller" in str(data.get("warning", "")).lower(),
           exit=r.returncode, warning=(data.get("warning") or "")[:80],
           rounds_completed=data.get("rounds_completed"))


def s11_synthesize_combines_artifacts() -> None:
    a = TEST_ROOT / ".council" / "artifacts" / "alpha.md"
    b = TEST_ROOT / ".council" / "artifacts" / "beta.md"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_text("# alpha\nfirst", encoding="utf-8")
    b.write_text("# beta\nsecond", encoding="utf-8")
    r = _run_council([
        "synthesize", "--artifact", str(a), "--artifact", str(b),
        "--project-root", str(TEST_ROOT),
    ], env_extra={"CODEX_SHELL": "1"})
    payload = json.loads(r.stdout)
    data = payload.get("data") or {}
    synth = data.get("synthesis", "")
    record("S11_synthesize_combines_artifacts",
           r.returncode == 0 and "alpha" in synth and "beta" in synth
           and data.get("output_language") == "zh-CN",
           exit=r.returncode, artifact_count=len(data.get("sources") or []),
           language=data.get("output_language"))


def s12_validate_model_name_rejects_unknown() -> None:
    ok_claude = resolve_adapter_model("claude") == "claude"
    # MODEL_ALIASES entry: gemini-1.5-flash -> gemini (canonical)
    ok_gemini_alias = resolve_adapter_model("gemini-1.5-flash") == "gemini"
    # Prefix passthrough: variant not in alias table returns as-is
    ok_gemini_passthrough = resolve_adapter_model("gemini-2.5-pro") == "gemini-2.5-pro"
    ok_gpt = resolve_adapter_model("gpt") == "gpt"
    rejected = False
    try:
        validate_model_name("clood")
    except ValueError:
        rejected = True
    record("S12_validate_model_name_rejects_unknown",
           ok_claude and ok_gemini_alias and ok_gemini_passthrough
           and ok_gpt and rejected,
           claude=ok_claude, gemini_alias=ok_gemini_alias,
           gemini_passthrough=ok_gemini_passthrough, gpt=ok_gpt,
           rejected_clood=rejected)


def s13_orchestrator_materialize_imports_allowed_change() -> None:
    target_rel = "src/feature/new_module.ts"
    target_abs = TEST_ROOT / target_rel
    if target_abs.exists():
        target_abs.unlink()
    store = CouncilStateStore(TEST_ROOT)
    provider = WriteProvider({target_rel: "export const two = 2;\n"})
    orchestrator = DelegationOrchestrator(
        store=store, participant_factory=lambda _: provider,
    )
    result = orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller="codex",
        target_model="claude",
        objective="smoke import",
        task_summary="write src/feature/new_module.ts",
        constraints=[], relevant_files=[target_rel], inputs={},
        execution_guardrails=ExecutionGuardrails(
            import_manifest=ImportManifest(writable_globs=["src/**"]),
        ),
        expected_output="",
    )
    imported_ok = (
        result.import_outcome == "applied" and target_abs.exists()
        and target_abs.read_text(encoding="utf-8").startswith("export const two")
        and provider.cwd is not None
        and provider.cwd != TEST_ROOT
    )
    manifest_entry = next(
        (c for c in result.workspace_manifest if c.path == target_rel), None,
    )
    record("S13_orchestrator_materialize_imports",
           imported_ok and manifest_entry is not None and manifest_entry.imported,
           import_outcome=result.import_outcome,
           manifest_size=len(result.workspace_manifest),
           effective_strategy=result.execution_guardrails.isolated_workspace.strategy)
    if target_abs.exists():
        target_abs.unlink()
    parent = target_abs.parent
    while parent != TEST_ROOT and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def s14_baseline_ignores_source_untracked_files() -> None:
    # Plant an untracked-in-source file BEFORE delegation. Then run a
    # QuietProvider that writes nothing. workspace_manifest must be empty
    # and the file must survive.
    untracked = TEST_ROOT / "src" / "untracked_smoke.ts"
    untracked.write_text("export const lost_if_regression = true;\n", encoding="utf-8")
    store = CouncilStateStore(TEST_ROOT)
    provider = QuietProvider()
    orchestrator = DelegationOrchestrator(
        store=store, participant_factory=lambda _: provider,
    )
    result = orchestrator.run(
        role=RoleName.TESTER,
        controller="codex",
        target_model="claude",
        objective="TASK-058 regression",
        task_summary="Quiet tester must not unlink untracked source files",
        constraints=[], relevant_files=[], inputs={},
        execution_guardrails=ExecutionGuardrails(
            import_manifest=ImportManifest(writable_globs=["**"]),
        ),
        expected_output="",
    )
    survived = untracked.exists()
    content_ok = (
        survived and untracked.read_text(encoding="utf-8")
        == "export const lost_if_regression = true;\n"
    )
    record("S14_baseline_ignores_source_untracked_files",
           result.workspace_manifest == [] and content_ok
           and result.import_outcome == "none",
           import_outcome=result.import_outcome,
           manifest_size=len(result.workspace_manifest),
           untracked_survived=survived)
    if untracked.exists():
        untracked.unlink()


def s15_empty_writable_globs_denies_all() -> None:
    # sidecar writes file under src/** but default guardrails have empty
    # writable_globs → import must be rejected.
    store = CouncilStateStore(TEST_ROOT)
    provider = WriteProvider({"src/should_not_land.ts": "nope\n"})
    orchestrator = DelegationOrchestrator(
        store=store, participant_factory=lambda _: provider,
    )
    result = orchestrator.run(
        role=RoleName.TESTER,
        controller="codex",
        target_model="claude",
        objective="TASK-058 deny-default",
        task_summary="Default ImportManifest rejects sidecar writes",
        constraints=[], relevant_files=[], inputs={}, expected_output="",
    )
    host_missing = not (TEST_ROOT / "src" / "should_not_land.ts").exists()
    rejected = any(
        c.path == "src/should_not_land.ts" and c.imported is False
        for c in result.workspace_manifest
    )
    record("S15_empty_writable_globs_denies_all",
           result.import_outcome == "rejected" and host_missing and rejected,
           import_outcome=result.import_outcome, host_missing=host_missing,
           rejected_entry=rejected)


def s16_protected_paths_reject_state_writes() -> None:
    store = CouncilStateStore(TEST_ROOT)
    provider = WriteProvider({".claude/state/smoke_poison.json": '{"x":1}'})
    orchestrator = DelegationOrchestrator(
        store=store, participant_factory=lambda _: provider,
    )
    poison = TEST_ROOT / ".claude" / "state" / "smoke_poison.json"
    result = orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller="codex",
        target_model="claude",
        objective="try to write workflow state",
        task_summary="protected paths must reject this",
        constraints=[], relevant_files=[], inputs={},
        execution_guardrails=ExecutionGuardrails(
            import_manifest=ImportManifest(writable_globs=[".claude/**"]),
        ),
        expected_output="",
    )
    host_clean = not poison.exists()
    rejected = any(
        c.path.startswith(".claude/state/") and c.imported is False
        for c in result.workspace_manifest
    )
    record("S16_protected_paths_reject_state_writes",
           result.import_outcome == "rejected" and host_clean and rejected,
           import_outcome=result.import_outcome, host_clean=host_clean,
           rejected=rejected)


def s17_sandboxed_env_strips_controller_signals() -> None:
    store = CouncilStateStore(TEST_ROOT)
    provider = CapturingProvider()
    orchestrator = DelegationOrchestrator(
        store=store, participant_factory=lambda _: provider,
    )
    orchestrator.run(
        role=RoleName.IMPLEMENTER,
        controller="codex",
        target_model="claude",
        objective="env scrub check",
        task_summary="capture sandboxed env",
        constraints=[], relevant_files=[], inputs={}, expected_output="",
    )
    env = provider.env_override or {}
    stripped = all(k not in env for k in CONTROLLER_ENV_KEYS)
    flag_ok = env.get(DELEGATED_STAGE_ENV_FLAG) == "1"
    record("S17_sandboxed_env_strips_controller_signals",
           stripped and flag_ok,
           flag=env.get(DELEGATED_STAGE_ENV_FLAG),
           leaked_keys=[k for k in CONTROLLER_ENV_KEYS if k in env])


def s18_dependency_symlink_exposes_node_modules() -> None:
    # Force-touch: manually drive materialize and verify node_modules link
    # exists (sidecar would see the fake-eslint binary).
    from councilflow.utils.io import cleanup_workspace, materialize_workspace

    isolated = IsolatedWorkspace(
        strategy="git_worktree",
        exclude_patterns=list(DEFAULT_ISOLATION_EXCLUDE_PATTERNS),
        dependency_symlinks=list(DEFAULT_DEPENDENCY_SYMLINKS),
    )
    mat = materialize_workspace(
        project_root=TEST_ROOT,
        council_root=TEST_ROOT / ".council",
        delegation_id="dep_symlink_probe",
        isolated=isolated,
    )
    try:
        link_ok = (mat.workspace_path / "node_modules" / ".bin" / "fake-eslint").exists()
        content_ok = False
        if link_ok:
            content = (mat.workspace_path / "node_modules" / ".bin" / "fake-eslint").read_text(
                encoding="utf-8"
            )
            content_ok = "fake-eslint ran" in content
        record("S18_dependency_symlink_exposes_node_modules",
               link_ok and content_ok,
               effective_strategy=mat.effective_strategy,
               link_ok=link_ok, content_ok=content_ok)
    finally:
        cleanup_workspace(TEST_ROOT, mat.workspace_path, mat.effective_strategy)
        # source must still have the binary
    source_ok = (TEST_ROOT / "node_modules" / ".bin" / "fake-eslint").exists()
    RESULTS["S18_dependency_symlink_exposes_node_modules"]["source_survived"] = source_ok


def s19_registry_dispatches_gpt_family() -> None:
    ad = resolve_adapter("gpt")
    from councilflow.providers.openai_api import OpenAIChatAdapter

    ad_variant = resolve_adapter("gpt-4o-mini")
    record("S19_registry_dispatches_gpt_family",
           isinstance(ad, OpenAIChatAdapter) and isinstance(ad_variant, OpenAIChatAdapter)
           and ad_variant.openai_model == "gpt-4o-mini",
           gpt_type=type(ad).__name__,
           variant_type=type(ad_variant).__name__,
           variant_model=ad_variant.openai_model)


def s20_build_sandboxed_env_injects_markers() -> None:
    env = build_sandboxed_env("del_probe_123")
    ok = (env.get("COUNCILFLOW_DELEGATED_STAGE") == "1"
          and env.get("COUNCILFLOW_DELEGATION_ID") == "del_probe_123"
          and all(k not in env for k in CONTROLLER_ENV_KEYS))
    record("S20_build_sandboxed_env_injects_markers", ok,
           flag=env.get("COUNCILFLOW_DELEGATED_STAGE"),
           delegation_id=env.get("COUNCILFLOW_DELEGATION_ID"))


def s21_protected_paths_defaults_cover_workflow_dirs() -> None:
    guardrails = ExecutionGuardrails()
    need = [".claude/state", ".council/state.json", ".workflow-core",
            ".claude/skills", ".codex/skills", ".gemini/skills"]
    ok = all(p in guardrails.protected_paths for p in need)
    record("S21_protected_paths_defaults_cover_workflow_dirs", ok,
           protected_paths=guardrails.protected_paths)


def s22_deny_default_exposed_at_cli_level() -> None:
    # CLI: pass no --writable-glob, default guardrails should mean import
    # is rejected even if sidecar writes.
    # We rely on --model clood → adapter_missing, but actually we want a
    # passing round. Instead, use --model claude which will fail on real
    # Claude CLI invocation. Skip — the Python-level S15 covers this.
    # Here we just verify the CLI accepts the new options without error.
    r = _run_council([
        "delegate", "--role", "implementer", "--model", "clood",
        "--objective", "cli options smoke",
        "--task-summary", "check new CLI surface",
        "--writable-glob", "src/**",
        "--readonly-artifact", "docs/readme.md",
        "--allow-commit",
        "--project-root", str(TEST_ROOT),
    ], env_extra={"CODEX_SHELL": "1"})
    payload = json.loads(r.stdout)
    err = payload.get("error") or {}
    record("S22_cli_writable_glob_options_accepted",
           r.returncode == 1 and err.get("error_kind") == "adapter_missing",
           exit=r.returncode, error_kind=err.get("error_kind"))


def s23_delegation_wait_reports_completed_record() -> None:
    delegation_id = "del_smoke_completed"
    delegation_dir = TEST_ROOT / ".council" / "delegations" / delegation_id
    delegation_dir.mkdir(parents=True, exist_ok=True)
    (delegation_dir / "handoff.yaml").write_text("role: implementer\n", encoding="utf-8")
    (delegation_dir / "result.md").write_text("# smoke result\n", encoding="utf-8")
    (delegation_dir / "record.json").write_text(json.dumps({
        "id": delegation_id,
        "role": "implementer",
        "target_model": "claude",
        "status": "completed",
        "handoff_path": f".council/delegations/{delegation_id}/handoff.yaml",
        "result_path": f".council/delegations/{delegation_id}/result.md",
    }), encoding="utf-8")

    r = _run_council([
        "delegation", "wait", delegation_id,
        "--project-root", str(TEST_ROOT),
        "--timeout", "3", "--poll-interval", "1",
    ])
    payload = json.loads(r.stdout)
    data = payload.get("data") or {}
    record("S23_delegation_wait_reports_completed",
           r.returncode == 0 and data.get("status") == "completed"
           and data.get("delegation_id") == delegation_id,
           exit=r.returncode, status=data.get("status"),
           elapsed=data.get("elapsed_seconds"))


def s24_delegation_wait_times_out_without_record() -> None:
    delegation_id = "del_smoke_pending"
    delegation_dir = TEST_ROOT / ".council" / "delegations" / delegation_id
    delegation_dir.mkdir(parents=True, exist_ok=True)
    (delegation_dir / "handoff.yaml").write_text("role: tester\n", encoding="utf-8")
    record_path = delegation_dir / "record.json"
    if record_path.exists():
        record_path.unlink()

    r = _run_council([
        "delegation", "wait", delegation_id,
        "--project-root", str(TEST_ROOT),
        "--timeout", "2", "--poll-interval", "1",
    ])
    payload = json.loads(r.stdout)
    err = payload.get("error") or {}
    data = payload.get("data") or {}
    record("S24_delegation_wait_times_out",
           r.returncode == 1 and err.get("error_kind") == "wait_timeout"
           and data.get("record_exists") is False
           and data.get("handoff_exists") is True,
           exit=r.returncode, error_kind=err.get("error_kind"))


def s25_delegation_wait_rejects_unknown_id() -> None:
    r = _run_council([
        "delegation", "wait", "del_does_not_exist_ever",
        "--project-root", str(TEST_ROOT),
        "--timeout", "2", "--poll-interval", "1",
    ])
    payload = json.loads(r.stdout)
    err = payload.get("error") or {}
    record("S25_delegation_wait_rejects_unknown_id",
           r.returncode == 1 and err.get("error_kind") == "delegation_not_found",
           exit=r.returncode, error_kind=err.get("error_kind"))


def s26_mcp_policy_denies_implementer_writes_settings() -> None:
    from councilflow.providers.mcp_policy import (
        plan_mcp_policy,
        role_allows_mcp,
        write_empty_mcp_configs,
    )
    tmp = TEST_ROOT / ".council" / "workspaces" / "mcp_probe"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    implementer_allowed = role_allows_mcp(RoleName.IMPLEMENTER)
    synthesizer_allowed = role_allows_mcp(RoleName.SYNTHESIZER)
    written = write_empty_mcp_configs(tmp)
    claude_ok = (tmp / ".claude" / "settings.json").is_file()
    codex_ok = (tmp / ".codex" / "settings.json").is_file()
    gemini_ok = (tmp / ".gemini" / "settings.json").is_file()
    empty_content = json.loads((tmp / ".claude" / "settings.json").read_text("utf-8"))
    plan = plan_mcp_policy(RoleName.IMPLEMENTER, TEST_ROOT, tmp)

    record("S26_mcp_policy_denies_implementer_writes_settings",
           implementer_allowed is False and synthesizer_allowed is True
           and claude_ok and codex_ok and gemini_ok
           and empty_content == {"mcpServers": {}}
           and len(written) == 3
           and plan.get("denied_by_policy") is True,
           implementer_allowed=implementer_allowed,
           synthesizer_allowed=synthesizer_allowed,
           written=len(written), empty_ok=empty_content == {"mcpServers": {}},
           plan_denied=plan.get("denied_by_policy"))
    shutil.rmtree(tmp, ignore_errors=True)


def s28_overlay_uncommitted_file_visible_in_git_worktree() -> None:
    """0.1.2 regression: an untracked host file must appear in the sidecar
    worktree without the controller having to commit first."""
    import tempfile

    from councilflow.models.delegation import IsolatedWorkspace
    from councilflow.utils.io import cleanup_workspace, materialize_workspace

    with tempfile.TemporaryDirectory(prefix="councilflow-overlay-") as tmp:
        source = Path(tmp) / "repo"
        source.mkdir()
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "s@t.local"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "smoke"],
                       check=True, capture_output=True)
        (source / "README.md").write_text("# base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "-A"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "base"],
                       check=True, capture_output=True)

        untracked_rel = "src/feature/new.ts"
        (source / untracked_rel).parent.mkdir(parents=True, exist_ok=True)
        (source / untracked_rel).write_text("export const x = 1;\n", encoding="utf-8")

        modified_rel = "README.md"
        (source / modified_rel).write_text("# edited\n", encoding="utf-8")

        isolated = IsolatedWorkspace(
            strategy="git_worktree",
            exclude_patterns=[".council/**"],
        )
        mat = materialize_workspace(
            project_root=source,
            council_root=source / ".council",
            delegation_id="smoke_overlay",
            isolated=isolated,
        )
        try:
            untracked_visible = (mat.workspace_path / untracked_rel).is_file()
            modified_applied = (
                (mat.workspace_path / modified_rel).read_text("utf-8") == "# edited\n"
            )
            strategy_ok = mat.effective_strategy == "git_worktree"
        finally:
            cleanup_workspace(source, mat.workspace_path, mat.effective_strategy)

    record("S28_overlay_uncommitted_file_visible_in_git_worktree",
           untracked_visible and modified_applied and strategy_ok,
           untracked_visible=untracked_visible,
           modified_applied=modified_applied,
           strategy=mat.effective_strategy)


def s29_overlay_respects_gitignore_and_exclude_patterns() -> None:
    """Ignored paths and IsolatedWorkspace.exclude_patterns must still
    suppress copying during the overlay pass."""
    import tempfile

    from councilflow.models.delegation import IsolatedWorkspace
    from councilflow.utils.io import cleanup_workspace, materialize_workspace

    with tempfile.TemporaryDirectory(prefix="councilflow-overlay-exc-") as tmp:
        source = Path(tmp) / "repo"
        source.mkdir()
        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "s@t.local"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "smoke"],
                       check=True, capture_output=True)
        (source / ".gitignore").write_text("secrets.env\n", encoding="utf-8")
        (source / "README.md").write_text("# base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "-A"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "base"],
                       check=True, capture_output=True)

        (source / "secrets.env").write_text("API_KEY=x\n", encoding="utf-8")
        (source / ".claude").mkdir(exist_ok=True)
        (source / ".claude" / "leaked.json").write_text("{}\n", encoding="utf-8")

        isolated = IsolatedWorkspace(
            strategy="git_worktree",
            exclude_patterns=[".claude/**", ".council/**"],
        )
        mat = materialize_workspace(
            project_root=source,
            council_root=source / ".council",
            delegation_id="smoke_overlay_exc",
            isolated=isolated,
        )
        try:
            gitignored_blocked = not (mat.workspace_path / "secrets.env").exists()
            exclude_pattern_blocked = not (mat.workspace_path / ".claude" / "leaked.json").exists()
        finally:
            cleanup_workspace(source, mat.workspace_path, mat.effective_strategy)

    record("S29_overlay_respects_gitignore_and_exclude_patterns",
           gitignored_blocked and exclude_pattern_blocked,
           gitignored_blocked=gitignored_blocked,
           exclude_pattern_blocked=exclude_pattern_blocked)


def s27_provider_total_timeout_default_is_two_hours() -> None:
    from councilflow.providers.base import (
        DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
        default_runtime_settings,
    )
    settings = default_runtime_settings()
    record("S27_provider_total_timeout_default_is_two_hours",
           DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS == 7200.0
           and settings.total_timeout_seconds == 7200.0,
           constant=DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
           runtime=settings.total_timeout_seconds)


# ---------- Orchestration ---------- #

def main() -> int:
    if not TEST_ROOT.exists():
        print(f"Test project missing: {TEST_ROOT}", file=sys.stderr)
        return 2

    scenarios = [
        s01_version,
        s02_config_bootstrap_creates_template,
        s03_config_defaults_match_template,
        s04_set_controller_override_codex,
        s05_route_local_execution,
        s06_route_delegated,
        s07_adapter_missing_failure_report,
        s08_recursion_guard_blocks,
        s09_status_allowed_in_delegated_stage,
        s10_discuss_same_controller_short_circuits,
        s11_synthesize_combines_artifacts,
        s12_validate_model_name_rejects_unknown,
        s13_orchestrator_materialize_imports_allowed_change,
        s14_baseline_ignores_source_untracked_files,
        s15_empty_writable_globs_denies_all,
        s16_protected_paths_reject_state_writes,
        s17_sandboxed_env_strips_controller_signals,
        s18_dependency_symlink_exposes_node_modules,
        s19_registry_dispatches_gpt_family,
        s20_build_sandboxed_env_injects_markers,
        s21_protected_paths_defaults_cover_workflow_dirs,
        s22_deny_default_exposed_at_cli_level,
        s23_delegation_wait_reports_completed_record,
        s24_delegation_wait_times_out_without_record,
        s25_delegation_wait_rejects_unknown_id,
        s26_mcp_policy_denies_implementer_writes_settings,
        s27_provider_total_timeout_default_is_two_hours,
        s28_overlay_uncommitted_file_visible_in_git_worktree,
        s29_overlay_respects_gitignore_and_exclude_patterns,
    ]

    for sc in scenarios:
        try:
            sc()
        except Exception:
            record(sc.__name__, passed=False, traceback=traceback.format_exc())

    print("\n=== SMOKE REPORT ===")
    print(json.dumps(RESULTS, indent=2, ensure_ascii=False, default=str))
    failed = [name for name, v in RESULTS.items() if not v["passed"]]
    print(f"\nTotal: {len(RESULTS)}, Passed: {len(RESULTS) - len(failed)}, Failed: {len(failed)}")
    if failed:
        print("Failed scenarios:", failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
