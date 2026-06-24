# Simulated AI workflow

本文展示 `research-project-os` 安装到 AI 之后，用户如何通过自然语言指令驱动一个长期项目。这里不介绍底层代码，也不要求用户记住脚本命令；重点是展示“你对 AI 说什么”，以及 AI 应该如何把这些指令落实到 `.project_os/` 项目工作台中。

## 模拟项目

项目名称：`urban-signal-forecast`

项目目标：建立一个长期维护的数据分析项目，用历史传感器数据预测未来 24 小时的城市信号强度。项目会经历数据盘点、清洗、建模、评估、结果确认、图表生成和阶段发布。

用户只需要把工作交给 AI：

```text
我要新建一个长期项目，名称是 urban-signal-forecast。
目标是用历史传感器数据预测未来 24 小时的城市信号强度。
请用 research-project-os 工作流管理这个项目。
```

AI 应该做的事：

- 识别这是一个长期项目；
- 创建或规划 `.project_os/` 工作台；
- 生成项目状态、任务、运行、结果和资产索引；
- 告诉用户会创建哪些文件；
- 在真正写入前先给出 dry-run 计划。

## 1. 创建项目工作台

用户指令：

```text
在 /projects/urban-signal-forecast 新建项目工作台。
先 dry-run，列出将创建的目录、索引和说明文件，不要立即写入。
```

AI 预期响应：

```text
我会创建 .project_os/ 工作台，包括项目元信息、workflow、branch/task/run/result/asset 索引、runtime current 指针，以及 AGENTS.md 入口说明。
当前是 dry-run，不会改文件。
```

用户确认：

```text
确认，按这个计划创建。
```

AI 执行后应记录：

- 项目名称和目标；
- 初始化时间；
- 初始 branch；
- 初始 task；
- agent 使用规则。

## 2. 让 AI 建立项目路线

用户指令：

```text
请为这个项目建立三个工作分支：
1. baseline：先做最小可运行的基线流程；
2. feature_engineering：后续做特征工程改进；
3. release_v1：整理第一版可交付结果。

创建后把 baseline 设为当前分支。
```

AI 应该做的事：

- 在 `.project_os/` 中登记三个 branch；
- 为每个 branch 写清楚目标和边界；
- 把 current branch 指向 `baseline`；
- 不把这些 branch 混同于 git branch。

用户之后可以直接说：

```text
当前项目在哪个分支？下一步是什么？
```

AI 应该从 `.project_os/` 读取，而不是凭聊天上下文猜。

## 3. 让 AI 拆解任务

用户指令：

```text
在 baseline 分支下，把第一阶段拆成可执行任务。
我希望至少包括：数据盘点、数据清洗、基线模型、指标报告。
请给出任务顺序、依赖关系和每个任务的完成标准。
```

AI 预期输出：

```text
我会创建这些任务：
- data_inventory：盘点输入数据、字段、时间范围和缺失情况；
- cleaning_pipeline：生成可重复的数据清洗流程；
- baseline_model：训练一个最小可用预测模型；
- metric_report：汇总 MAE/RMSE 等指标和误差分析。

依赖关系：
data_inventory -> cleaning_pipeline -> baseline_model -> metric_report
```

用户确认：

```text
确认创建这些任务，并把 data_inventory 设为当前任务。
```

AI 应该把任务写入项目状态，并更新 current task。

## 4. 纳管外部数据

用户指令：

```text
原始数据在 /storage/datasets/urban-signal/raw_2024.parquet，文件很大。
请把它登记为项目资产，作为 baseline 的输入数据。
不要复制回项目目录，不要 hardlink，也不要把 symlink 当作恢复依据。
请记录 checksum、用途和当前位置。
```

AI 应该做的事：

- 创建一个稳定的 `asset_id`；
- 在 asset registry 中记录数据用途；
- 在 `asset_locations.tsv` 中记录 primary location；
- 如用户要求，计算 checksum；
- 报告“run input 应引用 asset_id，而不是直接依赖某个本机路径”。

AI 不应该做的事：

- 不应该创建 hard link；
- 不应该默认复制几十 GB 数据；
- 不应该把 symlink 当作 canonical 引用；
- 不应该把路径散落写进多个临时文档里。

## 5. 开始一次运行

用户指令：

```text
现在开始 baseline_model 的第一次运行。
输入使用刚才登记的原始数据资产。
计划运行：python scripts/train_baseline.py --config configs/baseline.yaml
请为这次运行创建 run，并记录输入、命令、参数和环境。
```

AI 应该先回应：

```text
我会在当前 branch=baseline、task=baseline_model 下创建一次 run。
这次 run 会记录：输入 asset、执行命令、配置文件、运行环境、输出路径和后续指标。
```

如果用户确认执行，AI 再继续运行或指导运行。

运行结束后，用户可以说：

```text
运行完成。输出文件是 results/baseline/metrics.json 和 results/baseline/predictions.parquet。
MAE 是 0.184，RMSE 是 0.231。
请把这些信息记录到刚才的 run。
```

AI 应该把输出和指标写入 run provenance，并关闭或更新 run 状态。

## 6. 登记候选结果

用户指令：

```text
把 results/baseline/metrics.json 登记为候选结果。
它关联刚才的 baseline run。
不要设为当前结果，先让我审阅。
```

AI 应该做的事：

- 创建 result 记录；
- 状态设为 candidate；
- 关联来源 run；
- 标明 result 类型，例如 metrics/report/table；
- 提醒用户：candidate 还不是 current。

用户审阅后说：

```text
我批准这个 metrics 结果作为 baseline 当前结果。
```

AI 才能执行 promotion，并保留 approval / audit 记录。

## 7. 继续项目

几天后，用户只需要说：

```text
继续这个项目。
```

AI 应该先做状态恢复，而不是直接执行分析：

```text
我会先读取 .project_os/ 状态，确认 current branch、current task、最近 run、候选结果、当前结果和未完成任务。
```

AI 给出的摘要应该类似：

```text
当前 branch：baseline
当前 task：metric_report
最近 run：baseline_model 第一次运行，已完成
候选结果：metrics.json，已提升为 current
下一步建议：生成指标报告和误差分析图；如果确认，我会创建 metric_report run。
```

用户可以继续：

```text
好的，继续生成指标报告。先列计划，不要直接改文件。
```

## 8. 记录图表或文档产物

用户指令：

```text
我用 R 生成了一张误差分布图，命令是：Rscript scripts/plot_error.R。
输出是 results/figures/error_distribution.pdf。
运行环境是 conda 环境 Renv。
请记录这次运行，并把图登记为候选结果。
```

AI 应该记录：

- 当前 task；
- run command；
- conda 环境名；
- R session 信息如果可用；
- 输入数据；
- 输出 PDF；
- result 类型为 figure；
- 状态为 candidate。

如果环境细节还没有捕获，AI 应该提醒：

```text
为了完整 provenance，建议补充 R sessionInfo() 或环境导出信息。
```

## 9. 外置资产迁移

用户指令：

```text
我准备把 results/intermediate/large_features.parquet 外置到 /storage/project-assets/。
请先生成外置计划，说明会复制到哪里、如何校验 checksum、如何更新 asset_locations.tsv。
不要执行 move，不要 hardlink。
```

AI 应该输出 report-only 计划：

```text
计划：
1. 为 large_features.parquet 创建 asset_id；
2. 复制到 /storage/project-assets/urban-signal-forecast/；
3. 复制后校验 checksum；
4. 登记 primary location；
5. 保留 old path mapping；
6. 不创建 hardlink；
7. 不依赖 symlink。
```

用户确认后再说：

```text
确认执行外置，复制后校验 checksum，并报告映射关系。
```

## 10. 恢复检查

如果项目中断过，用户说：

```text
这个项目可能中断过。请做恢复检查，只生成报告。
不要删除文件，不要移动文件，不要重放运行，不要自动修复。
```

AI 应该检查并报告：

- 是否存在 stale lock；
- 当前指针是否指向不存在的 branch/task/run；
- 索引是否漂移；
- 外置资产是否可用；
- 是否有未关闭 run；
- 是否有 candidate result 未处理；
- 建议用户确认哪些修复动作。

## 11. 生成阶段交付

用户指令：

```text
我批准基于当前 baseline 结果生成 release_v1。
请打包第一版交付，包含当前 metrics、误差分布图、run provenance、asset manifest 和简短说明。
```

AI 应该：

- 检查 result 是否已 accepted/current；
- 检查来源 run 是否完整；
- 检查输入 asset 是否有 location 和 checksum；
- 生成 release manifest；
- 保留 approval 记录；
- 输出交付包位置和内容摘要。

## 12. 完整指令流示例

下面是一段用户可能真实给 AI 的连续指令：

```text
1. 在 /projects/urban-signal-forecast 新建长期项目工作台，先 dry-run。
2. 确认创建。
3. 建立 baseline、feature_engineering、release_v1 三个分支，把 baseline 设为当前。
4. 在 baseline 下拆解数据盘点、数据清洗、基线模型、指标报告四个任务。
5. 把 /storage/datasets/urban-signal/raw_2024.parquet 登记为外置输入资产，不复制、不 hardlink。
6. 开始 baseline_model 第一次运行，记录输入、命令、参数和环境。
7. 运行完成，记录 metrics.json、predictions.parquet、MAE 和 RMSE。
8. 把 metrics.json 登记为候选结果，先不要设为 current。
9. 我批准 metrics.json 作为 baseline 当前结果。
10. 继续项目，告诉我下一步。
11. 记录 R 绘图运行，环境是 conda Renv，输出 error_distribution.pdf。
12. 我批准生成 release_v1，包含当前结果、图表、run provenance 和 asset manifest。
```

这就是 `research-project-os` 的使用方式：用户给 AI 高层指令，AI 负责把长期项目状态维护在 `.project_os/` 中，并在每一步保留可恢复、可审计的记录。
