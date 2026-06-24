# research-project-os

`research-project-os` 是一个面向长期科研与工程工作的项目工作台。它为每个项目提供一套本地 `.project_os/` 状态层，用来组织计划、任务、运行记录、结果、数据资产、阶段发布和恢复信息，让人类与 agent 能够在同一套项目上下文中持续推进工作。

这个项目关注的是**长期项目如何被可靠地继续、复盘、迁移和交付**。它把散落在聊天记录、脚本目录、临时文件、运行日志和手工笔记里的信息，整理成项目内可追踪的结构化工作流。

## 这个流程能做什么

`research-project-os` 提供的是一套 project lifecycle harness，主要能力包括：

- **初始化项目工作台**：在项目目录中创建 `.project_os/`，生成标准配置、索引、任务模板和 agent 入口说明。
- **管理项目分支和阶段**：用 branch 表示项目路线、阶段或并行工作流，避免把所有工作混在一个目录状态里。
- **拆解和延续任务**：把长期目标拆成 task，记录任务目标、上下文、依赖、当前阶段和 handoff 信息。
- **记录运行 provenance**：为每次 run 记录输入、命令、参数、环境、输出文件、指标和状态，方便复现与审计。
- **管理结果生命周期**：把输出登记为 result，支持 candidate、accepted、current、superseded 等状态，并通过 approval gate 控制结果提升。
- **管理数据资产和大文件**：用 asset_id 管理项目数据，支持 primary / backup / mirror 位置登记、checksum 校验和跨机器迁移。
- **支持外置资产**：通过 `asset_id + asset_locations.tsv` 引用外部数据，不依赖 hard link 或本机挂载语义。
- **维护当前上下文**：记录 current branch、current task、current run、current session，让“继续”可以恢复到明确位置。
- **支持 agent 会话管理**：用 session 表示一次 agent 工作焦点，支持暂停、恢复、关闭和清理规划。
- **生成状态摘要和 dashboard**：从 canonical indexes 导出人类可读的项目状态、结果索引、运行索引和 dashboard。
- **提供恢复和健康检查**：对中断、缺失索引、stale lock、路径漂移、资产不可用等情况生成 report-only 恢复建议。
- **支持发布/交付流程**：把已确认结果打包成 release，保留来源、manifest、校验和审计记录。
- **统一 agent 入口**：让“继续、计划、状态、运行、记录结果、外置数据、发布”等触发先进入项目状态层，再执行具体命令。

## 它解决什么问题

长期项目常见问题：

- “继续”时不知道当前任务、上次运行、最新结果在哪里；
- 文件很多，`final/v2/new/current` 混乱；
- 运行命令、环境、输入输出、图表和结论没有 provenance；
- 大文件在不同硬盘、机器、挂载点之间迁移后引用断裂；
- agent 直接执行领域命令，绕过项目状态，导致后续无法恢复。

`research-project-os` 的做法是：项目先进入 `.project_os/` 上下文，再执行具体领域命令，并把关键输入、命令、输出和结果写回项目状态。

```text
自然语言触发 / 项目命令
        ↓
AI workflow skill：路由、状态恢复、上下文确认
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

1. **项目状态优先**：`.project_os/` 是长期项目的状态层；领域工具、脚本和分析流程是任务执行层。
2. **先路由再执行**：长期项目中的“继续/计划/状态/运行/结果/绘图/系统发育/训练模型/外置数据”等触发，先进入 AI workflow skill，由 AI 恢复项目状态并确认上下文。
3. **provenance 必须可恢复**：run 记录输入、命令、输出、参数、指标和环境摘要。
4. **结果需要显式提升**：`promote-result`、`build-release`、`restore-journal --apply` 等写入性动作必须带 `--approved`。
5. **大文件不使用 hard link**：canonical 引用是 `asset_id + .project_os/indexes/asset_locations.tsv`；symlink 只能是可选本地兼容层，不能作为恢复依据。
6. **report-only 优先**：迁移、恢复、清理、外置资产规划默认只报告，不擅自删除、移动或覆盖。

## 快速开始

`research-project-os` 的主要使用方式是**安装到 AI 的 skill / workflow 系统中**，然后通过自然语言让 AI 帮你维护项目工作台。用户不需要把它当作一个单独命令行工具来记忆。

安装完成后，可以直接对 AI 说：

```text
在 /path/to/my_project 新建一个长期项目工作台，主题是 “My Long Project”。
先给我看 dry-run 计划，确认后再应用。
```

已有项目可以说：

```text
这个目录是一个已经存在的长期项目。请为它接入 research-project-os 工作流，
创建 .project_os/，保留现有文件，不要移动或删除历史结果。
```

继续项目时可以说：

```text
继续这个项目。先读取 .project_os/ 的当前状态，告诉我当前 branch、task、run、
已有结果和下一步建议，然后再等我确认执行。
```

记录一次运行时可以说：

```text
我要开始一次新的分析运行。请为当前任务创建 run，
记录输入数据、执行命令、环境、输出文件和关键指标。
```

登记大文件时可以说：

```text
这个大文件已经在外部硬盘上。请把它登记为外置资产，
不要复制回项目，不要 hardlink；用 asset_id 和 asset_locations.tsv 记录位置和 checksum。
```

## 文档

- [Architecture](docs/ARCHITECTURE.md)：通用对象模型和生命周期。
- [Assets](docs/ASSETS.md)：no-hardlink 外置资产策略。
- [Agent integration](docs/AGENT_INTEGRATION.md)：agent 如何把它作为第一路由。
- [Installation](docs/INSTALLATION.md)：如何把这套工作流安装到 AI 中使用。
- [Simulated workflow](docs/SIMULATED_WORKFLOW.md)：一个从建项到发布的模拟工作流。
- [Use cases](docs/USE_CASES.md)：不同领域项目如何套用。

## 当前关系

这个独立仓库用于解释和发布通用 harness。Codex skill 库中的 `research-project-os` skill 是它的 agent 入口/适配层；二者应保持同一原则：**通用 `.project_os/` 项目架构为主，领域 workflow 为插件式执行层**。
