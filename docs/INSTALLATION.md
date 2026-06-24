# Installation for AI use

`research-project-os` 不是给用户手工记命令的单独代码工具，而是一套安装到 AI 中使用的 project workflow skill。安装完成后，用户通过自然语言告诉 AI 要创建项目、继续项目、记录运行、登记结果或管理外置资产；AI 再按照 skill 规则维护 `.project_os/`。

## 安装后的使用方式

用户面向 AI 的入口是自然语言，例如：

```text
在这个目录接入 research-project-os 工作流，先 dry-run，不要改文件。
```

```text
继续当前项目。请先读取 .project_os/ 状态，告诉我当前任务、上次运行、已有结果和下一步建议。
```

```text
这次运行用了 data/raw.csv，命令是 Rscript scripts/plot.R，输出是 results/figure1.pdf。
请记录 run provenance，并把 figure1.pdf 登记为候选结果。
```

```text
这个 80GB 数据文件已经在外部硬盘上，请登记为 asset，不要复制，不要 hardlink。
```

AI 内部可以调用 harness 脚本或适配层，但用户不需要把这些脚本当成日常接口。

## 安装到 Codex

将本仓库中的 skill 目录安装到 Codex skills 目录：

```bash
git clone https://github.com/Teng-bio/research-project-os.git
mkdir -p ~/.codex/skills
cp -a research-project-os/harness/research-project-os ~/.codex/skills/research-project-os
```

然后重启 Codex 会话，或开启一个新会话。

验证方式：在任意项目目录中对 Codex 说：

```text
请检查 research-project-os 是否可用。不要改文件，只解释如果我说“继续项目”会如何路由。
```

如果 Codex 识别到 `research-project-os` skill，它应该先读取 skill 规则，并说明会通过 `.project_os/` 状态层处理长期项目。

## 安装到 Claude / 其他 agent

如果 agent 支持本地 skills 目录，可以把同一个 skill 目录复制到对应位置。例如：

```bash
mkdir -p ~/.claude/skills
cp -a research-project-os/harness/research-project-os ~/.claude/skills/research-project-os
```

或：

```bash
mkdir -p ~/.agents/skills
cp -a research-project-os/harness/research-project-os ~/.agents/skills/research-project-os
```

不同 AI 客户端的 skills 路径可能不同；关键要求是：AI 能读取该目录下的 `SKILL.md`、`references/`、`templates/` 和 `scripts/`。

## 通过 skill 库集中管理

如果你已经有自己的 skill 仓库，可以把：

```text
harness/research-project-os/
```

作为一个 skill 加入你的 skill library，然后由该 skill library 同步到 Codex、Claude 或其他 agent 的 skills 目录。

推荐目录结构：

```text
skills/local/research-project-os/
├── SKILL.md
├── references/
├── scripts/
└── templates/
```

这样 `research-project-os` 会成为 AI 的一个工作流能力，而不是用户手工运行的一组独立脚本。

## 第一次在项目中使用

安装 skill 后，进入一个项目目录，对 AI 说：

```text
请为这个项目接入 research-project-os 工作流。
要求：
1. 先检查当前目录结构；
2. 说明将创建哪些 .project_os/ 文件；
3. 先 dry-run；
4. 不移动、不删除、不覆盖现有文件；
5. 等我确认后再应用。
```

确认 dry-run 后再说：

```text
我确认，按刚才的计划应用。
```

## 日常使用指令

### 查看状态

```text
查看当前项目状态。请先读取 .project_os/，总结当前 branch、task、run、result、asset 和下一步建议。
```

### 继续下一步

```text
继续下一步。不要直接跑分析，先告诉我你准备接着哪个 task 做，为什么。
```

### 新建任务

```text
为“整理输入数据并生成字段说明”新建一个任务，设为当前任务，并写清楚 objective 和 handoff。
```

### 记录运行

```text
我要运行一次模型训练。请为当前任务创建 run，并准备记录输入、命令、参数、环境、输出和指标。
```

### 记录结果

```text
把 results/model_eval.csv 登记为候选结果，关联到刚才的 run。不要设为 current，先给我审阅。
```

### 提升结果

```text
我批准把 result_model_eval_v1 设为当前结果。请执行 promotion，并保留审计记录。
```

### 外置资产

```text
/path/on/storage/large_dataset.parquet 是项目输入数据。请登记为外置资产，计算 checksum，记录 primary location。不要 hardlink，不要依赖 symlink。
```

### 恢复检查

```text
项目可能中断过。请做 recovery 检查，只生成报告，不要删除、移动、重放或修复任何文件。
```

### 发布交付

```text
我批准基于当前结果生成 release_v1。请构建 release 包，并记录使用了哪些 result、run 和 asset。
```

## 安装成功的判断标准

安装成功后，AI 应该表现为：

- 听到“继续项目 / 当前状态 / 新建任务 / 记录结果”等指令时，优先检查 `.project_os/`；
- 不直接跳到领域命令，而是先建立 branch/task/run/result 上下文；
- 写入性动作先 dry-run 或请求确认；
- promotion、release、restore-journal 这类动作需要明确批准；
- 大文件使用 asset registry，不使用 hard link 作为功能路径；
- 能把自然语言指令转成可审计的项目状态更新。
