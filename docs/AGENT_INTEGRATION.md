# Agent integration

Agent 使用本 harness 的规则很简单：长期项目中，不要先猜当前状态，也不要直接跑领域命令；先让 `project_os.py` 建立上下文。

## 第一入口

常见触发词：

- 继续、继续项目、继续下一步；
- 当前状态、项目状态、总结进展；
- 制定计划、拆解任务；
- 开始运行、先跑、记录结果；
- 绘图、R 绘图、Python 分析；
- 深度学习、模型训练；
- 系统发育、进化树、alignment；
- 外置数据、纳管外置数据、大文件迁移；
- release、打包、阶段交付。

都应先经过：

```bash
python3 harness/research-project-os/scripts/project_os.py route --root <project> --trigger "<用户触发词>"
python3 harness/research-project-os/scripts/project_os.py status --root <project>
```

## AGENTS.md / CLAUDE.md

每个具体项目可以有自己的 AGENTS.md，但它应该是 overlay：

- 通用规则来自 `.project_os/` harness；
- 项目特定内容只写主题、环境、常用命令、数据位置、禁止事项；
- 不把项目特定路径写回通用 harness 模板。

## 环境记录

如果某个项目使用 conda 环境、R 环境或特殊工具链，例如 `conda activate Renv` 后运行 R 包绘图，应在 run 中记录：

- environment name；
- interpreter path；
- package/session info；
- command；
- input/output；
- generated figure/result。

这类信息不是靠 agent “记忆”，而是通过 run provenance 写入项目状态。
