# Architecture

`research-project-os` 是项目内的状态层，而不是领域分析层。它不决定你必须用 Python、R、Nextflow、Snakemake、PyTorch、DESeq2 或 IQ-TREE；它只要求这些执行被放入可追踪的 branch/task/run/result/asset 结构中。

## 分层

```text
Agent / Human prompt
  └─ router: project_os.py route / start / status
      └─ project state: .project_os/
          ├─ branch: 路线、阶段、实验分支
          ├─ task: 目标、上下文、依赖、状态
          ├─ run: 命令、输入、输出、参数、指标、环境
          ├─ result: 可接受/可提升/可发布的结果
          ├─ asset: 数据和大文件逻辑引用
          ├─ session: 当前 runtime focus
          ├─ release: 交付包
          └─ recovery/hooks: 报告型恢复和扩展层
              └─ domain tools: Python/R/shell/生信/ML/绘图/数据库等
```

## 生命周期

1. `new-project` 或 `init` 创建 `.project_os/`。
2. `start` / `status` 建立当前 branch/task/session 上下文。
3. `create-task` 定义下一步工作。
4. `create-run` 记录一次实际运行。
5. `add-run-input` / `add-run-command` / `add-run-output` / `capture-run-env` 补齐 provenance。
6. `register-result` 把输出变成可追踪结果。
7. `accept-result` 或 `promote-result --apply --approved` 标记采用结果。
8. `build-release --apply --approved` 生成阶段交付。

## 设计边界

- `.project_os/` 是 canonical 项目状态。
- AGENTS.md / CLAUDE.md 是 agent 入口说明，不是 canonical 数据库。
- hooks 默认关闭，只能生成报告或建议，不能替代核心状态迁移。
- domain workflow 可以很多，但都应该回写 run/result/asset provenance。
