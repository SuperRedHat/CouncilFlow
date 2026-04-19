# CouncilFlow 0.1.0 全量冒烟测试报告

- **日期**: 2026-04-19
- **版本**: `councilflow 0.1.0`（editable install at `D:/project/CouncilFlow`）
- **测试项目**: `D:/AIProjects/test/councilflow-smoke-2026-04-19` @ `8910b2d`
- **驱动脚本**: `.smoke/full_live_smoke.py`（真实 `council` CLI 子进程 + Python 内部编排驱动混合）
- **原始结果**: `.smoke/smoke-results-2026-04-19.json`
- **结论**: **22 / 22 PASS**，回归 `ruff . --check`、`pytest -q` 全绿（189 tests）

---

## 一、环境

| 项 | 值 |
| --- | --- |
| OS | Windows 11 Home China 10.0.26200 |
| Shell | bash (MINGW) |
| Python | 系统默认 `python` |
| councilflow | `0.1.0` (editable) |
| Test fixture git HEAD | `8910b2d` |
| Test fixture layout | `package.json`, `src/main.ts`, `tests/main.test.ts`, `node_modules/.bin/fake-eslint`, `.gitignore` (`node_modules/`, `.council/`, `dist/`) |

### 回归基线

| 检查 | 结果 |
| --- | --- |
| `python -m ruff check .` | All checks passed |
| `python -m ruff check .smoke/full_live_smoke.py` | All checks passed |
| `python -m pytest -q` | `189 passed` |

---

## 二、场景总表（22 / 22）

| # | 场景 | 验证内容 | 结果 |
| --- | --- | --- | --- |
| S01 | `council --version` | 版本号正确返回 | PASS (`0.1.0`) |
| S02 | 配置 bootstrap | 首次 `council status` 自动生成 `.council/config.yaml` + state | PASS |
| S03 | 配置默认值 | `roles.implementer=claude`, `roles.synthesizer=codex`, `discussion.min_rounds=2`, `max_rounds=5` | PASS |
| S04 | `controller_override: codex` | 覆盖生效，`detect_controller()` 返回 codex | PASS |
| S05 | 路由 `local_execution` | 当 controller==target 时走本地 | PASS (`target=codex`) |
| S06 | 路由 `delegated` | controller!=target 且 sidecar 可用时委派 | PASS (`via_sidecar=True`) |
| S07 | `adapter_missing` 失败报告 | 目标模型无 adapter 时返回结构化 error JSON + delegation_id | PASS |
| S08 | 递归守卫 | `COUNCILFLOW_DELEGATED_STAGE=1` 环境下再调 `delegate` 被拦截 | PASS (`recursive_workflow_violation`, `exit=2`) |
| S09 | 被委派阶段允许 status | 在 delegated stage 下 `council status` 正常返回 | PASS |
| S10 | `discuss` 同 controller 短路 | 请求讨论模型等于当前 controller 时返回 warning + `rounds_completed=0` | PASS |
| S11 | `synthesize` 合并 artifact | 两个 artifact 文本都出现在 synthesis，中文输出 | PASS |
| S12 | 模型名校验 | `claude` / `gpt` / gemini alias (`gemini-1.5-flash → gemini`) / gemini passthrough (`gemini-2.5-pro`) / 未知 `clood` 被拒 | PASS |
| S13 | Orchestrator materialize + allowed import | `writable_globs=['src/**']` 时新增 `src/feature/new_module.ts` 被落盘 | PASS (`effective_strategy=git_worktree`) |
| S14 | Baseline 忽略源端 untracked | 源端存在但不在 baseline 的文件不会被当作删除 | PASS (`manifest_size=0`) |
| S15 | 空 writable_globs 默认拒绝 | `ImportManifest(writable_globs=[])` 时任何写入都被拒 | PASS |
| S16 | 受保护路径拦截 | `.claude/state/…` 写入被 `classify_import_changes` 拒绝 | PASS |
| S17 | 沙箱 env 剥离 controller 信号 | `build_sandboxed_env` 清除 `CLAUDECODE`, `CODEX_*`, `GEMINI_CLI` 等 | PASS (`leaked_keys=[]`) |
| S18 | Dependency symlink 暴露 node_modules | worktree 里通过 junction 暴露 `node_modules`，原目录不被清空 | PASS (`link_ok=True`, `source_survived=True`) |
| S19 | 注册表派发 `gpt` 家族 | `resolve_adapter('gpt')` 与 `resolve_adapter('gpt-4o-mini')` 都返回 `OpenAIChatAdapter` | PASS |
| S20 | `build_sandboxed_env` 注入 markers | `COUNCILFLOW_DELEGATED_STAGE=1` + `COUNCILFLOW_DELEGATION_ID` | PASS |
| S21 | `DEFAULT_PROTECTED_PATHS` 覆盖 workflow 目录 | 默认保护 6 条路径（state / skills / workflow-core） | PASS |
| S22 | CLI `--writable-glob` 等选项接受 | 新增的 import-manifest / guardrail CLI 选项被 Typer 正常解析 | PASS (`adapter_missing` 说明进入了执行阶段) |

---

## 三、按能力模块的覆盖说明

### 3.1 CLI 入口与 bootstrap
- **S01 / S02 / S03**: `council --version`、首次启动的配置生成、默认角色/讨论阈值落地。
- **S22**: 新增的 `--writable-glob`、`--readonly-artifact`、`--allow-commit`、`--allow-workflow-state-write` 选项在 Typer 层被接受（Windows 上 `windows_expand_args=False` 保证 glob literal）。

### 3.2 路由决策与 controller 检测
- **S04 → S06**: `controller_override` → `detect_controller` → `build_route_decision` 三层链路。
- **S07**: 路由到未配置 adapter 的模型时，CLI 以结构化错误 JSON 退出，`delegation_id` 保留便于追踪。
- **S09**: `delegate` 被守护，`status` 等只读命令在 `DELEGATED_STAGE` 下仍可调用。

### 3.3 递归守卫与环境隔离
- **S08**: `COUNCILFLOW_DELEGATED_STAGE=1` + `COUNCILFLOW_DELEGATION_ID` 同时存在时再发 `delegate` 返回 `recursive_workflow_violation`，exit=2。
- **S17 / S20**: `build_sandboxed_env(delegation_id)` 注入 `DELEGATED_STAGE_ENV_FLAG`，同时从继承 env 中剥离 `CONTROLLER_ENV_KEYS`（`CLAUDECODE`, `CODEX_SHELL`, `GEMINI_CLI`, …）。

### 3.4 Sidecar 工作区隔离（TASK-057/058 的核心修复）
- **S13**: `git_worktree` 策略生成独立 worktree，`writable_globs` 命中的新文件被落盘到源仓库。
- **S14**: baseline-driven `detect_workspace_changes` 只对比 baseline ↔ worktree 当前态，源端的 untracked 文件**不会**被误判为删除 — 这是此前 chess 数据丢失事故的直接修复点。
- **S15**: `writable_globs=[]` 走 deny-by-default 语义，任何新增文件都被拒（修复了之前 `elif writable and not …` 的空列表等价于「接受所有」的 bug）。
- **S16**: `DEFAULT_PROTECTED_PATHS` 命中 `.claude/state/**` 等路径时直接拒入。
- **S18**: `DEFAULT_DEPENDENCY_SYMLINKS`（`node_modules`, `.venv`, …）通过 Windows `mklink /J` 在 worktree 里暴露，tester 阶段 `pnpm exec` / `pytest` 才有依赖可用；原目录未被清空。
- **S21**: 默认保护路径包含 `.claude/state`, `.council/state.json`, `.workflow-core`, `.claude/skills`, `.codex/skills`, `.gemini/skills`。

### 3.5 Provider 注册表 & 模型校验
- **S12**: `resolve_adapter_model` 四分支均覆盖 — 直连（`claude`/`gpt`）、alias 归一（`gemini-1.5-flash → gemini`）、prefix passthrough（`gemini-2.5-pro`）、未知名拒绝（`clood`）。
- **S19**: `providers/registry.py::REGISTRY` 按 family 派发到 `OpenAIChatAdapter`，模型 id 原样透传。

### 3.6 Discuss / Synthesize
- **S10**: `discuss` 请求仅剩当前 controller 时，返回显式 warning（`Requested discuss models matched the current controller …`），`rounds_completed=0`，不与自己自嵌套。
- **S11**: `synthesize --artifact a --artifact b` 合并两份文本，默认 `output_language=zh-CN`。

---

## 四、修复点的端到端验证

| 此前问题 | 对应场景 | 证据 |
| --- | --- | --- |
| chess 项目 TASK-006 数据丢失（9 文件被误删 + 1 文件回滚到 HEAD） | S14 + S15 | baseline 方案只跟踪 worktree，deny-by-default 阻止误写 |
| Windows 上 `council delegate src/foo/**` 被 Click 预展开 | S22 | CLI 选项接受 `src/features/**` 等未展开 glob，进入执行阶段后报 adapter_missing 而非 argv 解析报错 |
| tester 阶段 `pnpm exec` 缺 node_modules | S18 | `DEFAULT_DEPENDENCY_SYMLINKS` + mklink /J，`link_ok=True`，`content_ok=True` |
| adapter 缺失时失败信息不结构化 | S07 | exit=1，payload 包含 `error_kind=adapter_missing` 与 `delegation_id` |
| 递归调用 `council delegate` 导致控制器自嵌套 | S08 | exit=2，`recursive_workflow_violation` 并回传 parent `delegation_id` |
| 受保护路径 `.claude/state` 可能被外部模型写入 | S16 + S21 | 默认 6 条保护路径，写入被拒 |
| 外部模型 env 泄漏（`CODEX_SHELL` 等） | S17 + S20 | sandboxed env 清零 + 注入委派 marker |
| OpenAI / GPT 模型无 adapter | S19 | registry 派发 `OpenAIChatAdapter`，变体 id 保留 |
| 模型别名解析不一致 | S12 | alias 表 + prefix 两条路径都在测试约束内 |

---

## 五、测试脚本与可复现性

### 运行方式
```powershell
cd D:\project\CouncilFlow
python .smoke\full_live_smoke.py             # 人读 + JSON
python .smoke\full_live_smoke.py > .smoke\smoke-results-2026-04-19.json
```

### 夹具准备
- Test project 仓库：`D:/AIProjects/test/councilflow-smoke-2026-04-19` (git 初始化 + 提交 `8910b2d`)
- `.gitignore` 忽略 `node_modules/`、`.council/`、`dist/`，避免 baseline 污染
- `node_modules/.bin/fake-eslint` 作为依赖符号链接的验证目标
- 夹具为纯本地测试数据，不涉及外部 API、不触发远程调用

### 不触发外部 API 的做法
- 真实 CLI 子进程只跑到路由或守卫阶段就停住：要么命中 `local_execution`，要么命中 `adapter_missing` / `recursive_workflow_violation`
- 需要执行到 provider 的路径一律用 `WriteProvider` / `NoopProvider` 等 fake adapter 注入 `DelegationOrchestrator`

---

## 六、已知局限 / 未覆盖项

| 项 | 说明 | 下一步建议 |
| --- | --- | --- |
| 真机 Codex / Claude / Gemini adapter 调用 | 本次全部走 local_execution / adapter_missing / fake provider；未发真实 HTTP 请求 | 已有 `adapter_contract` 单测 + chess 手动验证覆盖过，发布前视情况再跑一次真机冒烟 |
| 多角色串联（implementer→tester→reviewer→fixer） | 阶段机本身有单测覆盖；本次没跑完整真实四阶段串联 | chess 项目 TASK-006 实测已经覆盖该路径 |
| `copy` 与 `none` 隔离策略 | 本轮以 `git_worktree` 为主 | `test_isolated_workspace.py` 中已覆盖三种策略的行为差异 |
| Linux / macOS 行为 | 仅 Windows 真机冒烟 | CI 跑 pytest（跨平台）即可基本保障 |

---

## 七、结论

- **CouncilFlow 0.1.0 已具备发布质量**：22 个端到端场景全部通过，`ruff . --check` 与 `pytest -q` 双保底通过（189 tests）。
- 之前导致 chess 项目数据丢失的 baseline + deny-by-default 两个 bug 都有针对性的冒烟场景（S14 / S15）在位；再次回归不会悄悄回退。
- **建议下一步**：收口 0.1.0 release（tag + CHANGELOG），并在发布前做一次真机 Codex / Claude / Gemini adapter 的 smoke（需要有效 API key）。
