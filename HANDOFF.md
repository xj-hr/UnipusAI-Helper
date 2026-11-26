# 交接 README（HANDOFF）

> **用途**：新会话 / 新 agent 接手本仓库时的第一份状态快照。
> **与 `AGENTS.md` 分工**：`AGENTS.md` 讲「必须怎么做」（规则），本文讲「现在做到哪」（状态）。
> **命名说明**：未占用根目录 `README.md`，因为那是上游维护的产品说明，同步上游会被覆盖。
> **更新追踪**：每次任务收尾更新 §1 / §3 / §4 / §8，并在 §9 追加一行；本文与代码同仓提交，不滞后于 HEAD。

---

## 1. 30 秒速览

| 项 | 当前值 |
|---|---|
| 分支 / HEAD | `main` / `7a06b31` |
| 相对上游 | 领先 `origin/main` **15 个提交**；已推 `fork/feat-brush-duration`（`45c1c6f`），`fork/main` 仍等于上游 |
| 版本 | `APP_VERSION = "3.9.18"`（沿用上游版本，**未自行升版**） |
| 测试 | `59/59`（Python）+ `56/56`（Node），2026-11-27 00:40 实测 |
| 主要阻塞 | ① `origin` 403 无法推送 ② 刷时长真机链路未验证 |
| 接手第一件事 | 读 §4 的 P0 两项；改代码前读 `AGENTS.md` |

---

## 2. 仓库坐标（我从哪来）

| 远端 | 地址 | 状态 |
|---|---|---|
| `origin` | `github.com/YSJohnson/UnipusAI-Helper` | 上游；`main` = `99dc849`（v3.9.18，2026-11-26，PR #74）；**本机凭据 `xj-hr` 无写权限，push 返回 403** |
| `fork` | `github.com/xj-hr/UnipusAI-Helper` | 个人 fork；`main` = `3ef2223`（上游 `99dc849` + 仅 `ci.yml` 一个文件，用于登记工作流）；本地全部工作推到 `feat-brush-duration`（`5eb920a`）；**勿再覆盖 `fork/main`** |
| 本地 | `F:\UnipusAI-Helper` | `main` = 上游 + 7 个本地提交 |

**归档标签（历史线，勿删）**

| 标签 | 指向 | 内容 |
|---|---|---|
| `archive-s0-s1-20261127` | 旧线 7 提交 | PyQt5 时代的 S0/S1 成果：186 项回归、CI、`run_tests.py`、4 篇文档 |
| `archive-feature-brush-20261126` | `cf5c87a` | 原始 63 提交的刷时长分支顶点 |
| `archive-v3.6.0` | 旧线发布点 | 自定版本 3.6.0（已废弃，勿再使用该版本号） |
| `archive-fix-silent-failure` | `93b390b` | 僵尸分支归档 |

---

## 3. 已完成（按时间倒序，带提交号）

| 日期 | 事项 | 提交 |
|---|---|---|
| 2026-11-27 | 新增 `AGENTS.md`（agent 宪法） | `7a06b31` |
| 2026-11-27 | 本地 15 个提交推到 `fork/feat-brush-duration` | `45c1c6f` |
| 2026-11-27 | `config.example.json` 补 `time_brushing` 段 + CHANGELOG「未发布」 | `bb0c9a4` |
| 2026-11-27 | QML 新增「刷时长」入口，工作台接入模式互斥 | `b2a7031` |
| 2026-11-27 | `UCampusBot` 接入 `ModeGuard` 与刷时长宿主构建 | `e635129` |
| 2026-11-27 | 忽略 `.workbuddy/`、`启动.cmd` | `823f9aa` |
| 2026-11-27 | `.gitignore` 放行两套刷时长测试 | `060be66` |
| 2026-11-27 | 对齐上游 v3.9.18，保留刷时长纯逻辑层 | `1833ff0` |
| — | 上游基线（v3.9.18） | `99dc849` |

**能力现状**

| 能力 | 状态 |
|---|---|
| 答题链路（解析 / 提示词 / 执行 / 特殊页处理器） | 上游实现，可用（未在本地改动） |
| PySide6 + QML 界面 | 可启动（离屏实测），本地依赖 `PySide6-Essentials 6.12.0` |
| 刷时长：页面内控制器 + Python 宿主 | 代码完整、离线测试通过；**未接真机验证** |
| 刷时长：界面入口与模式互斥 | 已接通（`Main.qml` → `NativeBridge` → `WorkbenchController` → `UCampusBot`） |
| 刷时长：参数可视化配置 | **没有**，只能改 `config.json` 的 `time_brushing` 段 |
| CI | **已复建** `.github/workflows/ci.yml`（static / tests / js），GitHub 上尚未运行 |

---

## 4. 未完成 / 待办

| 优先级 | 事项 | 具体下一步 | 完成判据 | 阻塞 |
|---|---|---|---|---|
| P0 | 刷时长真机验收 | 桌面会话执行 `启动.cmd` → 登录 → 点「刷时长」→ 观察日志出现 `[页面]` 节次推进 | 日志有连续节次切换、按钮变「停止刷时长」、停止后能答题 | 需桌面环境（离屏会 `tab crashed`） |
| P1 | 刷时长参数进 QML 配置面板 | `ConfigEditor.qml` 加分组 + `ConfigEditor` Qt 侧读写 `time_brushing` | 改间隔/范围后重启生效 | 无 |
| P1 | 探针脚本迁移 | `archive-s0-s1-20261127:scripts/{probe_time_brushing,brush_pilot_3min}.py` 适配新 bot API 后放回 `scripts/` | 能跑通一次普查 | 依赖旧 `build_time_brushing_runner` 签名（已加 `manual` 参数） |
| P2 | CI 首次成功运行 | `Actions` → `ci` → `Run workflow` → 分支选 `feat-brush-duration`（该分支有 lock/tests/assets） | 三个 job 全绿 | 工作流已登记（`active`）；`main` 上触发的第 1 次运行 3 job 全失败，因 main 缺 `requirements.lock`/`tests/`/`assets/` |
| P2 | 版本号策略 | 等上游发版后跟随递增；**不要**再自定 `v3.6.0` 这类低于上游的号 | `APP_VERSION` 与 tag 一致且不低于上游 | 无 |
| P3 | `origin` 推送权限 | 换有权限的账号重登 GCM，或用 PAT，或走 fork + PR | `git push origin main` 成功 | 需账号侧操作 |

---

## 5. 环境与启动（最短路径）

```bash
# 依赖安装（venv 无 pip，必须用 uv）
uv pip install --python "C:/Users/xjykx/.workbuddy/binaries/python/envs/unipus-helper/Scripts/python.exe" -r requirements.txt

# 启动（有桌面会话；--skip-check 跳过环境自检，避免交互菜单阻塞）
"C:/Users/xjykx/.workbuddy/binaries/python/envs/unipus-helper/Scripts/python.exe" UnipusAI_Helper.py --skip-check

# 离线测试（改刷时长模块后必跑）
"C:/Users/xjykx/.workbuddy/binaries/python/envs/unipus-helper/Scripts/python.exe" tests/test_time_brushing.py   # 59/59
node tests/test_time_brushing_controller.js                                                                     # 56/56
```

其余硬约束（venv 位置、`execute_script` 返回约定、Git Bash `xargs` 崩溃、提交须中文等）见 `AGENTS.md` §5，不在本文重复。

---

## 6. 已知问题

| 问题 | 影响 | 现状 |
|---|---|---|
| `origin` push 403（`xj-hr` 无写权限） | 上游无法同步，CI 无法触发 | 已知，重试无用；走 fork |
| 刷时长真机未验证 | 不能确认真实页面上的切换与提交 | 离屏环境 Edge `tab crashed`，需桌面复验 |
| `time_brushing` 无 UI 配置 | 用户需手改 JSON | 默认值可用；`enabled=false` 时界面点击按手动模式放行 |
| 主文件 1.4 万行 | 定位成本高 | 新逻辑一律进 `unipus_helper/` |
| 上游 `.gitignore` 忽略 `tests/` | 新测试默认不入库 | 本 fork 用 `!tests/` 例外，仅放行两套刷时长测试 |
| 无 CI | 回归靠人工 | 见 §4 P2 |

> 完整缺陷与治理短板清单（20 条，含证据、影响与修复建议）见 **`docs/缺陷台账.md`**；本文只保留影响判断的摘要。

---

## 7. 本地实测记录（区分「已验证」与「未验证」）

| 时间 | 对象 | 方式 | 结果 |
|---|---|---|---|
| 2026-11-27 00:40 | 刷时长两套测试 | 直接运行 | 59/59、56/56 |
| 2026-11-27 00:41 | QML 加载 | 离屏 `QQmlApplicationEngine.load(Main.qml)` | `rootObjects = 1`，`state` 含 `brushing`，无报错 |
| 2026-11-27 00:42 | 控制器接线 | 假 bot + 假 runner | 启动/重复启动被拒/停止/答题被互斥拦截，均符合预期 |
| 2026-11-27 00:42 | GUI 主循环 | 离屏 `mainloop(close_after=2500)` | 正常退出；仅 `ConfigEditor.qml` 既有 Shortcut 警告 |
| 2026-11-27 00:38 | 真机启动 | 离屏直跑 80s | GUI 与登录页正常，约 70s 后 Edge `tab crashed`，**登录未完成** |

---

## 8. 已定决策（避免重复讨论）

| 决策 | 理由 | 代价 |
|---|---|---|
| 对齐上游 v3.9.18，而非把旧线合入 | 上游已重构为 PySide6/QML，旧线 63 提交的架构基础消失 | 旧线 186 项回归作废（依赖符号在上游 0 命中） |
| 不覆盖 `fork/main` | 保持与上游可比对，随时能提 PR | 自己的改动只能走分支 |
| 刷时长界面点击无视 `enabled=false` | 点击即显式意图，避免「装了却点不动」 | 与旧版行为不同（旧版会拒绝并提示） |
| 只提交两套刷时长测试 | 尊重上游「测试不入库」约定 | 其余测试仍只在本地 |
| 提交信息必须含中文 | 本机 wb-hook 强制 | 纯英文提交会被拒 |

---

## 9. 更新记录

| 日期 | 变更 | 对应提交 |
|---|---|---|
| 2026-11-27 | 首次建立：记录对齐 v3.9.18、刷时长接入、AGENTS.md 落地后的状态与待办 | `docs(交接README)` 提交 |
| 2026-11-27 | §6 增加缺陷台账指针；台账登记 20 条问题 | `docs(缺陷台账)` 提交 |
| 2026-11-27 | 按台账顺序修复：依赖锁定、CI 复建、裸 except 收敛；台账状态回写 | `e60204c` / `767c5e0` / `37f1723` |
| 2026-11-27 | 推送 `feat-brush-duration` 到 fork；fork Actions 默认关闭，CI 未触发 | `45c1c6f` |
| 2026-11-27 | `ci.yml` 增加 `workflow_dispatch`，可手动触发；已推 fork | `aa0d38b` |
| 2026-11-27 | 仅 `ci.yml` 推到 `fork/main`（`3ef2223`）登记工作流；推送触发的首次运行 3 job 全失败（main 缺 lock/tests/assets） | `3ef2223` |
