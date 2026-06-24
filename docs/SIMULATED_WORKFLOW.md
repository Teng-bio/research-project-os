# Simulated workflow

本文用一个虚构项目说明 `research-project-os` 如何组织长期工作。示例不依赖真实数据，也不代表某个特定领域；重点是展示 `.project_os/` 如何把计划、运行、结果、数据资产和交付串成一条可恢复的流程。

## 模拟项目

项目名称：`urban-signal-forecast`

目标：构建一个长期维护的数据分析项目，用历史传感器数据预测未来 24 小时的城市信号强度，并持续迭代数据清洗、建模、评估和结果发布流程。

项目目录示意：

```text
urban-signal-forecast/
├── AGENTS.md
├── README.md
├── data/
├── notebooks/
├── scripts/
├── results/
└── .project_os/
```

其中 `.project_os/` 是项目状态层；`data/`、`scripts/`、`results/` 是领域执行层。

## 1. 初始化项目工作台

创建项目时，先生成 `.project_os/` scaffold：

```bash
python3 harness/research-project-os/scripts/project_os.py new-project \
  --root /projects/urban-signal-forecast \
  --title "Urban Signal Forecast" \
  --profile research \
  --platforms codex claude \
  --apply
```

初始化后，项目会获得：

- `.project_os/project.json`：项目元信息；
- `.project_os/workflow.md`：项目工作流说明；
- `.project_os/indexes/*.tsv`：branch、task、run、result、asset 等索引；
- `.project_os/runtime/*`：current branch/task/run/session 指针；
- `.project_os/templates` 派生出的任务和规范文件；
- `AGENTS.md` / `CLAUDE.md`：agent 入口规则。

## 2. 建立项目分支

项目初期创建三个 branch：

```text
main_baseline      基线流程：清洗数据、训练简单模型、建立指标口径
feature_engineering 特征工程：增加滚动窗口、节假日、异常标记等特征
release_v1         第一版交付：整理结果、图表、说明文档和 release 包
```

示例命令：

```bash
python3 harness/research-project-os/scripts/project_os.py create-branch \
  --root /projects/urban-signal-forecast \
  --branch-id main_baseline \
  --title "Baseline forecasting workflow" \
  --set-current
```

作用：后续“继续”“当前状态”“记录结果”都会落到明确的 branch 上，而不是混在整个仓库根目录里。

## 3. 拆解任务

在 `main_baseline` branch 下创建第一批任务：

```text
task_001_data_inventory     盘点输入数据和字段含义
task_002_cleaning_pipeline  编写数据清洗脚本
task_003_baseline_model     训练基线预测模型
task_004_metric_report      汇总评估指标和误差分析
```

示例命令：

```bash
python3 harness/research-project-os/scripts/project_os.py create-task \
  --root /projects/urban-signal-forecast \
  --title "Build baseline model" \
  --kind analysis \
  --set-current
```

每个 task 可以记录：

- objective：这一步要完成什么；
- context：相关背景和输入；
- dependencies：依赖哪些上游任务；
- context manifest：本任务允许优先读取哪些文件；
- handoff：中断后给下一次继续的说明。

## 4. 登记数据资产

假设原始数据较大，实际存放在外部存储：

```text
/storage/datasets/urban-signal/raw_2024.parquet
/storage/datasets/urban-signal/raw_2025.parquet
```

在项目中不依赖 hard link，也不把外部路径写死到脚本里作为唯一来源，而是登记为 asset：

```bash
python3 harness/research-project-os/scripts/project_os.py adopt-external-asset \
  --root /projects/urban-signal-forecast \
  --path /storage/datasets/urban-signal/raw_2024.parquet \
  --asset-id asset_raw_signal_2024 \
  --usage "baseline training input" \
  --write-report
```

登记后，项目通过如下链路恢复数据引用：

```text
run input -> asset_raw_signal_2024
asset_raw_signal_2024 -> .project_os/indexes/asset_locations.tsv
asset location -> absolute path / checksum / availability / role
```

这样未来换机器、换硬盘、换挂载点时，只需要更新 asset location，而不是重写所有 run 记录。

## 5. 创建并记录一次运行

开始训练基线模型时，先创建 run：

```bash
python3 harness/research-project-os/scripts/project_os.py create-run \
  --root /projects/urban-signal-forecast \
  --task-id task_003_baseline_model \
  --slug baseline-random-forest
```

然后把输入、命令、参数、环境和输出写入 run：

```bash
python3 harness/research-project-os/scripts/project_os.py add-run-input \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --asset-id asset_raw_signal_2024

python3 harness/research-project-os/scripts/project_os.py add-run-command \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --command "python scripts/train_baseline.py --config configs/baseline.yaml"

python3 harness/research-project-os/scripts/project_os.py add-run-parameter \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --param model=random_forest \
  --param horizon=24h

python3 harness/research-project-os/scripts/project_os.py capture-run-env \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --pip-freeze
```

运行完成后登记输出和指标：

```bash
python3 harness/research-project-os/scripts/project_os.py add-run-output \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --path results/baseline/metrics.json

python3 harness/research-project-os/scripts/project_os.py add-run-metric \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --name mae \
  --value 0.184

python3 harness/research-project-os/scripts/project_os.py close-run \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --status completed
```

此时，即使几周后再继续项目，也能知道这个结果来自什么输入、什么命令、什么参数和什么环境。

## 6. 登记和提升结果

把模型评估表登记为 candidate result：

```bash
python3 harness/research-project-os/scripts/project_os.py register-result \
  --root /projects/urban-signal-forecast \
  --run-id run_20260624_baseline_random_forest \
  --path results/baseline/metrics.json \
  --status candidate \
  --type metrics
```

人工确认后，可以接受结果：

```bash
python3 harness/research-project-os/scripts/project_os.py accept-result \
  --root /projects/urban-signal-forecast \
  --result-id result_baseline_metrics_v1 \
  --approved
```

如果要把它提升为 current result，需要显式 approval gate：

```bash
python3 harness/research-project-os/scripts/project_os.py promote-result \
  --root /projects/urban-signal-forecast \
  --result-id result_baseline_metrics_v1 \
  --to current/main_baseline/metrics.json \
  --apply \
  --approved
```

这条规则避免 agent 在没有确认的情况下把候选结果覆盖成正式结果。

## 7. “继续项目”的恢复路径

几天后用户只说：

```text
继续
```

agent 不应该直接猜下一步，而应先进入项目状态：

```bash
python3 harness/research-project-os/scripts/project_os.py status \
  --root /projects/urban-signal-forecast
```

状态摘要会回答：

- 当前 branch 是什么；
- 当前 task 是什么；
- 最近一次 run 是否完成；
- 当前 accepted/current result 是什么；
- 是否有 candidate result 未处理；
- 是否有外部资产不可用；
- 下一步建议从哪个 task 继续。

如果需要解释短触发：

```bash
python3 harness/research-project-os/scripts/project_os.py route \
  --root /projects/urban-signal-forecast \
  "继续下一步"
```

route 只生成确定性计划，不直接绕过状态执行领域命令。

## 8. 生成 dashboard 和交付包

项目阶段完成后，可以导出 dashboard：

```bash
python3 harness/research-project-os/scripts/project_os.py export-dashboard \
  --root /projects/urban-signal-forecast \
  --apply \
  --sqlite
```

如果要形成阶段交付：

```bash
python3 harness/research-project-os/scripts/project_os.py build-release \
  --root /projects/urban-signal-forecast \
  --release-id release_v1 \
  --result-id result_baseline_metrics_v1 \
  --apply \
  --approved
```

release 会保留：

- 使用了哪些 result；
- result 来自哪些 run；
- run 使用了哪些 input asset；
- checksum / manifest / 版本信息；
- 人类可读说明。

## 9. 中断和恢复

如果上次运行中断、机器重启或出现 stale lock，先生成恢复报告：

```bash
python3 harness/research-project-os/scripts/project_os.py plan-recovery \
  --root /projects/urban-signal-forecast \
  --write-report
```

恢复规划默认 report-only：它可以指出 stale lock、tmp 文件、索引漂移、缺失路径、asset 不可用等问题，但不会自动删除、移动、覆盖或重放历史状态。

## 完整工作流概览

```text
new-project / init
    ↓
create-branch
    ↓
create-task + add-context + add-dependency
    ↓
register/adopt asset
    ↓
create-run
    ↓
add-run-input / command / parameter / env / output / metric
    ↓
close-run
    ↓
register-result
    ↓
accept-result / promote-result --apply --approved
    ↓
status / summarize-state / export-dashboard
    ↓
build-release --apply --approved
    ↓
plan-recovery / verify-external-assets / continue
```

这个模拟流程展示的是 `research-project-os` 的核心价值：让长期项目的每一步都能被定位、解释、复现、迁移和继续。
