# research-project-os

`research-project-os` 是一个**通用的长期项目工作台 harness**。它不是某一个课题、某一个物种、某一类生信任务或 TypeII PKS 的专用流程；TypeII PKS、深度学习模型构建、R 绘图分析、系统发育、数据整理、论文证据包等都只是它可以承载的项目类型。

它的核心目标是：在每个项目目录内维护一个可迁移、可恢复、可审计的 `.project_os/` 工作台，让 agent 和人类都能围绕同一套项目状态继续工作。

## 它解决什么问题

长期项目常见问题：

- “继续”时不知道当前任务、上次运行、最新结果在哪里；
- 文件很多，`final/v2/new/current` 混乱；
- 运行命令、环境、输入输出、图表和结论没有 provenance；
- 大文件在不同硬盘、机器、挂载点之间迁移后引用断裂；
- agent 直接执行领域命令，绕过项目状态，导致后续无法恢复。

`research-project-os` 的做法是：所有长期项目先进入 `.project_os/` 上下文，再执行具体领域命令。

```text
自然语言触发 / 项目命令
        ↓
project_os.py route / start / status
        ↓
branch / task / run / result / asset / session 上下文
        ↓
执行 Python/R/shell/领域工具
        ↓
登记 inputs、commands、outputs、metrics、results、assets、decisions
```

## 核心对象

`.project_os/` 下维护这些索引和状态：

- `branch`：项目分支/阶段/路线，不等同于 git branch；
- `task`：可执行任务单元，记录目标、上下文、依赖和阶段；
- `run`：一次运行的 provenance，包括输入、命令、参数、环境、输出、指标；
- `result`：可被接受、提升、发布的结果对象；
- `asset`：数据和大文件的逻辑资产；
- `asset_locations.tsv`：资产位置表，支持 primary / backup / mirror；
- `release`：对外发布或阶段交付包；
- `session`：agent runtime focus，支持暂停、恢复、收尾；
- `recovery`：崩溃/中断后的 report-only 恢复规划；
- `hooks`：默认关闭的报告型 hook 层，不能拥有核心逻辑。

## 关键原则

1. **通用架构优先**：不绑定 TypeII PKS，也不绑定生信；领域工具只是任务执行层。
2. **先路由再执行**：长期项目中的“继续/计划/状态/运行/结果/绘图/系统发育/训练模型/外置数据”等触发，先进入 `project_os.py route`、`start` 或 `status`。
3. **provenance 必须可恢复**：run 记录输入、命令、输出、参数、指标和环境摘要。
4. **结果需要显式提升**：`promote-result`、`build-release`、`restore-journal --apply` 等写入性动作必须带 `--approved`。
5. **大文件不使用 hard link**：canonical 引用是 `asset_id + .project_os/indexes/asset_locations.tsv`；symlink 只能是可选本地兼容层，不能作为恢复依据。
6. **report-only 优先**：迁移、恢复、清理、外置资产规划默认只报告，不擅自删除、移动或覆盖。

## 快速开始

从本仓库中的 harness 脚本创建项目骨架：

```bash
python3 harness/research-project-os/scripts/project_os.py new-project \
  --root /path/to/my_project \
  --title "My Long Project" \
  --apply
```

在已有项目中初始化 `.project_os/`：

```bash
python3 harness/research-project-os/scripts/project_os.py init \
  --root /path/to/existing_project \
  --apply
```

查看当前状态：

```bash
python3 harness/research-project-os/scripts/project_os.py status --root /path/to/my_project
```

解释短触发词会如何进入 harness：

```bash
python3 harness/research-project-os/scripts/project_os.py route \
  --root /path/to/my_project \
  --trigger "继续下一步"
```

运行 smoke test：

```bash
python3 harness/research-project-os/scripts/smoke_project_os_e2e.py
```

## 文档

- [Architecture](docs/ARCHITECTURE.md)：通用对象模型和生命周期。
- [Assets](docs/ASSETS.md)：no-hardlink 外置资产策略。
- [Agent integration](docs/AGENT_INTEGRATION.md)：agent 如何把它作为第一路由。
- [Use cases](docs/USE_CASES.md)：不同领域项目如何套用。

## 当前关系

这个独立仓库用于解释和发布通用 harness。Codex skill 库中的 `research-project-os` skill 是它的 agent 入口/适配层；二者应保持同一原则：**通用 `.project_os/` 项目架构为主，领域 workflow 为插件式执行层**。
