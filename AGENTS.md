# AGENTS.md — 本仓库的 agent 宪法

> **生效范围**：任何 agent（含自动化脚本）在本仓库开始开发、修复或维护前，必须先通读本文。
> **优先级**：用户当次明确指令 > 本文 > README / CHANGELOG / docs。
> 三者冲突时，先指出冲突点，再按上述顺序执行，不得默默选择。
> **基线**：`main` = 上游 v3.9.18 + 刷时长接入（2026-11-27）。本文随项目演进更新，见 §11。

---

## 1. 项目目标与边界

**是什么**：Windows 桌面工具。Selenium 驱动 Edge 打开 U 校园课程页，解析题目 → 调大模型（或官方答案接口）作答 → 提交；另含「刷时长」模块，按节次自动切换页面累计学习时长。界面为 PySide6 + QML。

**核心链路**（定位问题时按此顺序排查）：

```
UCampusBot（登录/建驱动）
  → WorkbenchController（扫描任务 → 选择 → 调度）
  → AISolver（逐页处理）
      → QuestionParser（Selectors + Strategy 链）
      → PromptBuilder / OpenAICompatibleClient
      → AnswerExecutor（填写与提交）
      → ContentHandler（音频/视频/闪卡/自检/讨论等特殊页）
  → 结果回写 snapshot → QML 渲染
```

**边界（不得越界）**：

| 不做 | 原因 |
|---|---|
| 服务端、云同步、多账号托管 | 单机工具，无后端 |
| 绕过验证码、风控、付费 | 合规红线，仓库不提供规避手段 |
| 承诺 Linux/macOS 运行 | 目标环境仅 Windows + Edge（`winsound` 有 mock，但驱动目标为 Edge） |
| 内置题库/答案库分发 | 答案来自模型或官方接口，仓库不存答案 |
| 高频压站 | 所有节奏参数必须可配置，且默认保守 |

---

## 2. 目录与模块职责

改动前先确认「这件事属于谁」，不要往巨石文件里继续堆。

| 路径 | 职责 | 改动规则 |
|---|---|---|
| `UnipusAI_Helper.py` | 约 1.4 万行巨石：`Config`、`Question`/`Option` 模型、`Selectors`、`QuestionParser` + 全部 `*Strategy`、`PromptBuilder`、`AnswerExecutor`、`ContentHandler` 系、`AISolver`、`UCampusBot`、`PopupWatcher`、`main` 入口 | **新增能力优先放 `unipus_helper/`**；只有必须复用既有类时才改这里，改动前先 `git grep -n` 找全部调用点 |
| `unipus_helper/native_ui.py` | Qt/QML 启动、`NativeBridge`（QML 唯一入口对象）、`ConfigEditor`、日志与主题 | QML 能调用的方法必须挂 `@Slot`，见 §9.4 |
| `unipus_helper/workbench_controller.py` | 任务扫描/选择/调度、日志汇聚、模式互斥、`snapshot()` 数据出口 | 新增界面动作在此加方法，并在 `snapshot()` 暴露字段 |
| `unipus_helper/course_catalog.py` | 课程目录/单元/章节扫描与切换 | 站点结构变更时优先改这里 |
| `unipus_helper/answer_api.py` | 官方答案接口（解密、缓存、降级） | 失败必须降级到 AI 作答，不得直接报错中断 |
| `unipus_helper/accuracy_control.py` | 目标正确率解析与判分阈值 | 与 `Config.target_accuracy*` 强相关，改一处要同步另一处 |
| `unipus_helper/task_grading.py` | 任务可选性判定（是否计分/是否跳过） | 影响批量选择范围，改动需回归 |
| `unipus_helper/browser.py` | 浏览器规格、驱动生命周期 | 只管进程与能力，不写业务逻辑 |
| `unipus_helper/environment_checker.py` | 启动前环境自检与修复引导 | 不得在 `--skip-check` 路径上阻塞 |
| `unipus_helper/audio_recognizer.py` | Whisper 封装 | 模型懒加载，禁止在 import 期加载 |
| `unipus_helper/record_skip.py` | 录音/跟读跳过策略 | — |
| `unipus_helper/paths.py` | `PROJECT_ROOT`、`QML_DIR` | 唯一路径真源，禁止另算 |
| `time_brushing.py` | 刷时长宿主：归一化配置、注入脚本、看护循环、模式门闩 | **只依赖标准库**，禁止反向 import 主程序 |
| `assets/time_brushing_controller.js` | 页面内 UMD 控制器：节次推进、范围归位、层级熔断、日志透传 | 零依赖；协议见 §9.5 |
| `tests/` | 离线测试（`test_time_brushing.py` 59 项、`test_time_brushing_controller.js` 56 项） | 见 §6；`.gitignore` 对本目录设了例外，仅放行这两个文件 |
| `scripts/` | 一次性工具（当前只有上游 macOS 启动脚本） | 新增诊断脚本放这里，**不要放根目录** |
| `docs/` | 决策与可行性报告 | 新增方案文档需在 CHANGELOG 注明 |
| `logs/` | 运行产物（`ucampus_*.log`、`native-ui.log`、落盘页面） | 已 gitignore，禁止入库 |

---

## 3. 开发与维护原则（按优先级排序）

1. **先读后改**：动任何函数前，先 `git grep -n "<符号>"` 找全部调用点与测试引用；找不到调用点不等于没人用（QML、动态导入、脚本）。
2. **失败必须可传导**：禁止「捕获后当作成功」。历史事故：`ContentHandler.handle()` 返回值被丢弃，失败被静默判成功。任何降级都要落日志并影响最终状态。
3. **日志分级即契约**：预期情形（stale element、重渲染、元素不可见、页面跳转）用 `debug`/`warning`；真异常（未适配题型、转录失败、切换失败、播放停滞）必须 `warning` 以上并带上下文。
4. **选择器多候选**：站点类名是 webpack 哈希（`...__fXBxR` 这类），禁止单点硬编码；新增/修改选择器统一进 `Selectors`，并给出至少 2 个候选。
5. **策略互斥要穷举**：新增 `*Strategy` 时必须检查与既有策略 `can_parse` 的组合，历史上出现过「有材料但无选项池」两边都不接的空档。注册顺序影响命中，改顺序等于改行为。
6. **配置向后兼容**：`Config` 是 `@dataclass(frozen=True)`，新增字段必须有默认值，并同步 `from_json`；旧 `config.json` 不改也能启动。
7. **依赖最小化**：`unipus_helper/` 内新增第三方依赖必须先说明理由并写入 `requirements.txt`；能在标准库解决的不要加包。
8. **小步提交**：一次提交只做一件事；行为变化与格式化不混在同一次提交里。
9. **不猜数据**：没有实测结果的性能/兼容性结论一律标注「未验证」，不得用「应该」「理论上」充当结论。
10. **可回滚**：涉及 git 历史、远端、发布、文件删除的操作，先给影响清单，得到明确同意再动手。

---

## 4. 命名与代码风格

| 范围 | 约定 |
|---|---|
| Python 命名 | 模块/函数/变量 `snake_case`；类 `CamelCase`；常量 `UPPER_SNAKE`；私有前缀 `_` |
| Python 格式 | 4 空格；行宽约 120；同文件内保持既有风格（本仓未强制 ruff/black） |
| Qt 边界 | 暴露给 QML 的 `@Slot` / `@Property` 用 `camelCase`（`startBrushing`、`copyLogs`），与 QML 命名一致 |
| 类型标注 | 公开函数写标注；新模块建议 `from __future__ import annotations`（现有 4 个模块已用，非强制） |
| QML | 组件文件名 PascalCase（`ActionButton.qml`）；属性 camelCase；**可被测试或自动化定位的控件必须给 `objectName`** |
| JS（`assets/`） | UMD 包裹、零依赖、ES5 兼容；导出统一挂在既有的日志/状态变量上 |
| 日志文案 | 中文短句；模块前缀 `[刷时长]`、`[页面]`；禁止打印 `password`/`api_key`/`token_full`（走 `_redact`） |
| 提交信息 | `type(scope): 中文说明`，首行 ≤ 72 字；`type ∈ feat/fix/refactor/perf/test/docs/chore/revert`；**说明必须含中文**，否则被 hook 拒收 |
| 分支名 | `feat-*` / `fix-*` / `chore-*`；**禁止 `/`**（本机实测含 `/` 不生成 ref） |
| 标签 | 归档用 `archive-*`；正式版本 `vX.Y.Z`，与 `APP_VERSION` 一致 |

---

## 5. 配置与运行（本机固定事实）

| 项 | 值 |
|---|---|
| venv | `C:\Users\xjykx\.workbuddy\binaries\python\envs\unipus-helper`（Python 3.12） |
| 装包 | **venv 没有 pip**，必须 `uv pip install --python "<venv>/Scripts/python.exe" ...` |
| 启动 | `<venv>/Scripts/python.exe UnipusAI_Helper.py --skip-check` |
| 配置真源 | `config.json`（已 gitignore）；`config.example.json` 只放占位值 |
| GUI 依赖 | `PySide6-Essentials>=6.8,<7`（本机实测 6.12.0 可用） |

**本机环境坑（会让人误判为代码 bug）**：

| 现象 | 真实原因 | 正确做法 |
|---|---|---|
| `No module named pip` | venv 由 uv 创建 | 用 `uv pip` |
| `execute_script` 拿到 `None` | 脚本被当作函数体执行 | 注入脚本必须 `return (function(){...})();` |
| Git Bash 扫描结果为空 | `xargs -r` 断言崩溃，被 `if` 吞成「无命中」 | 批量检索用 `git grep`，不要 `xargs grep` |
| 提交被 hook 拒收 | 提交说明无中文 | 改成中文功能描述 |
| 杀掉 `msedgewebview2` 后系统搜索/小组件异常 | 那是 `SearchHost.exe`/`Widgets.exe` 持有的系统进程 | 只清理本项目 `msedgedriver` 及其子进程 |

---

## 6. 测试与验证要求

**必须跑**（改 `time_brushing.py` 或 `assets/time_brushing_controller.js` 时，两套都要跑）：

```bash
<venv>/Scripts/python.exe tests/test_time_brushing.py      # 期望 59/59
node tests/test_time_brushing_controller.js                # 期望 56/56
```

**GUI/QML 改动的离屏冒烟**（不需要真实浏览器）：

```python
# QT_QPA_PLATFORM=offscreen 下执行；bot 用 SimpleNamespace 假体
from types import SimpleNamespace
from unipus_helper.native_ui import NativeModernGUI
bot = SimpleNamespace(config=SimpleNamespace(username="", password="", token_full="",
                                             api_key="", base_url="", model=""))
gui = NativeModernGUI(None, None, bot, {})
gui._ready = True
gui.mainloop(close_after=2500)   # 正常退出且无 QML 报错即为通过
```

**没有自动化覆盖的改动**（当前绝大多数）必须做到：

1. 在提交说明或交接中写「改了什么 + 怎么手动验证 + 期望现象」；
2. 有日志产出的，附 `logs/` 下文件名与关键行；
3. **不得声称「已验证」**——只能说「离线测试通过 / 离屏冒烟通过 / 待真机确认」。

**真机验证**（登录、点按钮、页面切换）只能在有桌面会话时进行；离屏环境跑 `--skip-check` 会出现 Edge `tab crashed`，那是环境限制，不能据此判断功能好坏。

---

## 7. 变更流程

```
定位（读代码/日志） → 计划（影响面 + 回滚方式） → 实施 → 验证 → 提交 → 汇报
```

| 阶段 | 硬性要求 |
|---|---|
| 计划 | 涉及 ≥3 个文件、或改公共函数签名、或改配置结构时，先给方案再动手 |
| 实施 | 沿用既有模式（策略类、Handler、Slot），不自创第二套抽象 |
| 验证 | 按 §6 执行；改配置项要验证旧 `config.json` 仍可加载 |
| 提交 | 按 §8 清单；一次提交一件事 |
| 汇报 | 明确「做了什么 / 验证了什么 / 没验证什么 / 风险在哪」 |

**必须先获确认的操作**（列出对象、范围、后果后再执行）：`git reset --hard`、`push --force`、删除分支/标签、改远端、发布、批量改文件名、删除 `logs/` 或 `config.json`、`pip/uv uninstall`。

**推送约定**：`origin` 是上游（当前凭据无写权限）；个人改动推 `fork` 的**新分支**，不覆盖 `fork/main`（`fork/main` 始终等于上游）。

---

## 8. 提交前检查清单

- [ ] `git status` 只包含本次预期文件（无临时脚本、无 `logs/`、无 `config.json`）
- [ ] `git diff --cached` 无凭据：无 `token_full`、`api_key`、真实账号、`eyJ...` 长串
- [ ] 改动的模块跑过对应测试，并在提交说明/汇报中贴出通过数
- [ ] 新增/修改的日志符合 §3.3 分级，无 `print` 调试残留
- [ ] 新增配置字段有默认值，`config.example.json` 同步
- [ ] 行为变化已写 `CHANGELOG.md`（`## 未发布（本 fork）` 段）
- [ ] 提交信息为 `type(scope): 中文说明`，且一条提交只做一件事
- [ ] 没有用 `git add -A`（逐路径 add）

---

## 9. 场景速查（改代码 / 排查 / 新增功能）

### 9.1 修改既有逻辑
1. `git grep -n "<函数名>"` 找调用点 → 2. 看是否有测试引用 → 3. 改最小面 → 4. 跑 §6 全套 → 5. 检查失败路径是否仍可传导。

### 9.2 排查问题
1. 先读 `logs/` 最近一份日志（`ucampus_*.log`、`native-ui.log`），按 `ERROR`/`WARNING` 过滤；
2. 定位是「环境（驱动/网络/代理）」还是「页面结构（选择器）」还是「业务（解析/提示词）」；
3. 页面类问题优先要一份落盘 HTML 再判断，不凭猜测改选择器；
4. 改完必须说明「原现象 → 根因 → 修改点 → 复验方式」。

### 9.3 新增题型（五步，缺一不可）
1. `Selectors` 增加多候选选择器；
2. 新建 `XxxStrategy(QuestionParserStrategy)`，实现 `can_parse` / 解析；
3. 在 `QuestionParser.strategies` 里按优先级插入（顺序即命中顺序，靠前优先）；
4. `PromptBuilder` 补该题型的提示词约束（格式、数量、上下文）；
5. 若页面无需 AI（音频/视频/闪卡类），改走 `ContentHandler` + `AISolver.content_handlers`。

### 9.4 新增界面入口（QML）
1. `qml/Main.qml` 加控件并给 `objectName`；
2. `native_ui.NativeBridge` 加 `@Slot` 薄封装；
3. `workbench_controller` 实现业务方法，返回 `{"ok": bool, "error": str}`；
4. 需要的状态字段加进 `snapshot()`（QML 通过 `workbench.state` 读取）；
5. 离屏冒烟（§6）确认无 QML 报错。

### 9.5 改刷时长模块
- 节奏由**页面内 JS 控制器**掌握，Python 只做注入/看护/日志，不要在 Python 再加定时器；
- 日志走 `JS_LOG_VAR = "__unipusTimeBrushingLogs"`（上限 200 条），改协议要同步 `time_brushing.py` 与两套测试；
- 越界要「归位」而不是 clamp；`idx === end` 才受 `loop` 约束；
- 与答题互斥靠 `ModeGuard`（`brushing` / `solving`），新增长任务模式要一并纳入。

### 9.6 新增配置项
`Config` 字段（带默认值）→ `from_json` 透传 → `config.example.json` → 使用处读取 → CHANGELOG「未发布」段。

---

## 10. 明确禁止

| # | 禁止行为 | 替代做法 |
|---|---|---|
| 1 | 提交 `config.json`、`token_full`、`api_key`、真实账号 | 只改 `config.example.json` 的占位值 |
| 2 | `git add -A` / `git commit -a` | 逐路径 `git add <file>` |
| 3 | `--force` 推送、`reset --hard` 覆盖他人提交、`--no-verify` 跳过 hook | 先沟通，用 revert 或新分支 |
| 4 | 在根目录新增临时脚本、测试数据、抓取页面 | 放 `scripts/`；产物放 `logs/`（已忽略） |
| 5 | 删除或覆盖 `config.json`、`logs/`、`.workbuddy/` | 需要时先备份并说明 |
| 6 | 杀系统 `msedgewebview2`（`SearchHost`/`Widgets` 持有）或 `explorer` 等系统进程 | 只清理本项目驱动及其子进程 |
| 7 | 用 `xargs grep` 做批量扫描 | `git grep -n` |
| 8 | 未跑测试就写「已验证/已修复」 | 写「离线测试通过，真机待确认」 |
| 9 | 为通过测试而放宽断言、跳过用例 | 修实现，不改判据 |
| 10 | 在 `unipus_helper/` 里反向 import 巨石文件造成循环依赖 | 抽公共函数到叶子模块（如 `paths.py`、`task_grading.py`） |
| 11 | 把大模型返回内容直接落库/落盘当答案库 | 只作本次作答，缓存需显式开关 |
| 12 | 提高默认点击频率、缩短间隔来"提升效果" | 节奏参数保持保守默认，由用户显式调 |

---

## 11. 本文档的维护

**触发更新**（与代码同批提交，不允许长期滞后）：

1. 目录或模块增删、职责变化；
2. 测试命令、用例数量基线变化；
3. 新增硬约束或已知坑（尤其是耗时排查超过 30 分钟的问题）；
4. 禁止项调整、提交规范变化；
5. 上游同步（架构调整、依赖换代）。

**维护方式**：改动本文时提交信息用 `docs(agent宪法): <说明>`，并在 `CHANGELOG.md`「未发布（本 fork）」段记一行。
**复核周期**：每个 minor 版本发布前、每次架构迁移后各复核一次；发现本文与代码不一致时，以代码事实为准并立即修正本文。
