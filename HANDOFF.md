# 交接 README（HANDOFF）

> **用途**：新会话 / 新 agent 接手本仓库时的第一份状态快照。
> **与 `AGENTS.md` 分工**：`AGENTS.md` 讲「必须怎么做」（规则），本文讲「现在做到哪」（状态）。
> **命名说明**：未占用根目录 `README.md`，因为那是上游维护的产品说明，同步上游会被覆盖。
> **更新追踪**：每次任务收尾更新 §1 / §3 / §4 / §8，并在 §9 追加一行；本文与代码同仓提交，不滞后于 HEAD。

---

## 1. 30 秒速览

| 项 | 当前值 |
|---|---|
| 分支 / HEAD | `main` / `98cea20`（已推 `fork/feat-brush-duration`） |
| 相对上游 | 领先 `origin/main` **66 个提交**（含归档线历史）；上游基线 `99dc849`（v3.9.18） |
| 版本 | 标签 `v3.9.18-fork.1`；`APP_VERSION = "3.9.18"`（与上游对齐，fork 用后缀区分） |
| 测试 | **9 套 151 项**（Python 95 + Node 56），已全部接入 CI，2026-11-27 18:2x 实测 |
| 主要阻塞 | ① D-19 `origin` 403（需账号权限）② D-11 结构治理第一批完成、51 个顶层类待分批 ③ D-16/D-17 需真机看 GUI 按钮与 loop 到头 |
| 接手第一件事 | 读 `README.md` 的「维护须知」+ §4；改代码前读 `AGENTS.md` |

---

## 2. 仓库坐标（我从哪来）

| 远端 | 地址 | 状态 |
|---|---|---|
| `origin` | `github.com/YSJohnson/UnipusAI-Helper` | 上游；`main` = `99dc849`（v3.9.18，2026-11-26，PR #74）；**本机凭据 `xj-hr` 无写权限，push 返回 403** |
| `fork` | `github.com/xj-hr/UnipusAI-Helper` | 个人 fork；`main` = `f54d14a`（上游 `99dc849` + `ci.yml`、`requirements.lock`、`time_brushing.py`、`assets/`、`tests/` 共 6 个文件，用于让 main 分支 CI 也绿）；工作分支 `feat-brush-duration`；**向上游提 PR 时须剔除这 6 个文件** |
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
| 2026-11-27 | CI 首次全绿：run `45878270277`（2m26s，static/tests/js 三 job 通过） | `2303e27` |
| 2026-11-27 | `fork/main` 补齐 lock/tests/assets/模块，main 分支 run `45879373438` 三 job 全绿 | `f54d14a` |
| 2026-11-27 | 低风险缺陷修复：QML Shortcut 警告、`shell=True`、启动脚本示例 | `889feff` / `f368033` / `3f8732a` |
| 2026-11-27 | 刷时长参数接入配置面板（启用/层级/间隔/范围/循环） | `b51d032` |
| 2026-11-27 | 探针/实测脚本迁回 `scripts/`，真机跑通；课程地址改 `--url` 必填 | `b15a5b0` |
| 2026-11-27 | 挂机真机验证：2 分钟两次切换（60.2s/次）+ 控制器启停与 `ModeGuard` 释放通过 | 见 `logs/pilot_3min_20261127_150232` |
| 2026-11-27 | 修复 D-22 互斥文案、D-21 首屏采样、D-05 六十二处 sleep 可中断 | `3bd2729` / `fe371fc` / `d778c80` |
| 2026-11-27 | D-02 收尾：主文件 72 处裸 except 收敛 | `5dedb46` |
| 2026-11-27 | D-01：176 处静默 except 分支加 `log_swallowed` 留痕 | `047bef3` |
| 2026-11-27 | D-01 传导闭环：告警队列 + `snapshot.degraded`，新增 `test_swallow.py` 入 CI | `f273809` |
| 2026-11-27 | D-03 第一步：抽出 `_split_record_questions()`，455→435 行 | `9197cdb` |
| 2026-11-27 | 新增 `scripts/sweep_question_pages.py`：遍历单元采样，命中题目页即停 | `3d340cb` |
| 2026-11-27 | 页面解析基线测试（无头 Edge + 合成页/真实样本），CI 缺浏览器自动跳过 | `999fc9b` |
| 2026-11-27 | D-03 阶段二：抽出 `_handle_special_questions()`，435→407 行 | `895a777` |
| 2026-11-27 | D-03 阶段三：抽出 `_advance_to_next_question()`，407→391 行 | 见 HEAD |
| 2026-11-27 | 录音作答段行为基线（5 项），为下一刀拆分做准备 | `c681794` |
| 2026-11-27 | D-03 阶段四：抽出 `_answer_record_questions()`，391→348 行 | 见 HEAD |
| 2026-11-27 | D-03 阶段五：抽出 `_answer_normal_questions()`，348→171 行 | 见 HEAD |
| 2026-11-27 | D-03 收尾：发布页 196→114、判分 183→83；D-10 测试默认入库 | `812ab12` |
| 2026-11-27 | D-04 日志结构化、D-12 标签 `v3.9.18-fork.1`、D-18 真实显示验证 | 见 HEAD |
| 2026-11-27 | D-11 第一步：外迁 12 个工具函数（submit_hooks/text_utils/record_utils） | `0eb616c` |
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
| 答题链路（解析 / 提示词 / 执行 / 特殊页处理器） | 主流程已拆分（171/114/83 行）并配 6 套基线测试；真机验证覆盖到解析与录音/普通题作答 |
| 日志与异常 | `log_print` 统一 548 处输出；`log_swallowed` 留痕 176 处，热点告警进 `snapshot.degraded` |
| PySide6 + QML 界面 | 可启动（离屏实测），本地依赖 `PySide6-Essentials 6.12.0` |
| 刷时长：页面内控制器 + Python 宿主 | 已真机验证：脚本级 2 分钟两次切换（60.2s/次）、控制器级启停、单元遍历采样 |
| 刷时长：界面入口与模式互斥 | 已接通（`Main.qml` → `NativeBridge` → `WorkbenchController` → `UCampusBot`） |
| 刷时长：参数可视化配置 | **已有**：配置面板「刷时长」卡片可改启用/层级/间隔/范围/循环，保存后写回 `time_brushing` |
| CI | 11 个步骤（static / 7 套 Python / Node / 解析基线 / 上传日志），最新 run `45978811206` 全绿 |

---

## 4. 未完成 / 待办

| 优先级 | 事项 | 具体下一步 | 完成判据 | 阻塞 |
|---|---|---|---|---|
| P2 | D-11 结构治理 | 按依赖倒序分批：日志/配置 → 解析器 → 各 Handler → AISolver；每批只搬无依赖块并跑全量测试 | 主文件降到 1 万行以内、类分布到 `unipus_helper/` | 51 个顶层类互相耦合，需多轮 |
| P2 | D-16 刷时长 GUI 按钮验收 | 桌面执行 `启动.cmd` → 登录 → 点「刷时长」→ 看按钮变「停止刷时长」、日志节次推进 | 按钮态、节次推进、停止后可答题 | 需桌面会话 |
| P3 | D-17 loop 到头 / 范围末端 | 配置范围 1–2、loop 开，跑到越界观察归位与日志 | 越界后归位、日志如实显示「范围外」 | 需真机跑满一轮 |
| P3 | D-19 `origin` 推送权限 | 换有权限账号重登 GCM，或配 `repo` PAT，或走 fork + PR | `git push origin main` 成功 | 需账号侧操作 |
| P3 | 上游同步 | 上游发新版后 `git fetch origin` + 变基；冲突优先保留本 fork 的 `unipus_helper/` 新模块与测试 | 同步后 9 套测试仍全绿 | 无 |

**已知遗留**

- `logs/samples/sweep15_parse.html`（真实题目页样本）不入库，换机器后解析基线只跑合成页用例。
- `tests/test_page_parse_baseline.py` 在无 Edge 环境自动 SKIP，CI 上等同「未验证解析」。
- 主文件仍有 51 个顶层类，`AISolver` 与 `UCampusBot` 依旧庞大，`D-11` 未完成前新增逻辑请一律放 `unipus_helper/`。

---|---|---|---|---|
| P0 | 刷时长 GUI 入口验收 | 桌面会话执行 `启动.cmd` → 登录 → 点「刷时长」→ 观察按钮变「停止刷时长」与日志节次推进 | 按钮态切换正确、节次推进、停止后可答题 | 脚本级与控制器级已验，仅差按钮点击本身 |
| P2 | CI 覆盖扩展 | 新增测试套件时同步加 job | 新套件纳入流水线 | 需先有测试文件 |
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
| 2026-11-27 16:2x | 答题真机采样 | 真实登录 → 扫描 → 逐任务解析（提交被拦截） | 2 个任务均为材料页（音频 170.2s / 视频阅读），无题目；样本 `logs/samples/s01~s03*.html`（本地，gitignore） |
| 2026-11-27 16:5x | 单元遍历采样 | `scripts/sweep_question_pages.py`（侧栏 `pc-slider-menu-unit` 切换 + 拦提交 + 停播放） | 第 4 个单元命中题目页：3 道判断/选择题作答并填充，无 XHR 提交；样本 `logs/samples/sweep15_parse.html`、`sweep16_after.html`（各 1.2 MB） |

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
| 2026-11-27 | `on.push.branches` 加 `feat-brush-duration`；该分支 push 自动跑通三 job | `2303e27` |
| 2026-11-27 | `fork/main` 补 lock/tests/assets 后 CI 在 main 上同样全绿 | `f54d14a` |
| 2026-11-27 | 补记 §3：D-13 参数面板、D-14 脚本迁移、D-16/D-17 真机验证、D-05/D-21/D-22 修复 | `docs(缺陷台账)` 提交 |
