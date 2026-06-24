# Use cases

`research-project-os` 是通用架构，可以承载很多类型的长期项目。

## 深度学习模型构建

- branch：baseline、ablation、new-architecture、data-cleaning；
- task：准备数据、训练模型、评估指标、生成图表；
- run：训练命令、config、checkpoint、seed、GPU/环境；
- result：best checkpoint、metrics table、plots；
- asset：训练集、验证集、预训练权重、大模型 checkpoint。

## 生信分析项目

- branch：数据质控、差异分析、富集分析、系统发育；
- run：软件版本、数据库版本、输入 FASTA/FASTQ/TSV；
- result：图表、表格、候选基因、系统树；
- asset：原始数据、数据库、外置中间结果。

## R 绘图项目

- branch：figure1、figure2、supplement；
- run：Rscript 命令、R sessionInfo、输入表格、输出 PDF/PNG/SVG；
- result：可投稿图、源数据、绘图脚本。

## 文档/论文证据包

- task：整理证据、生成 Methods、整理结果、审稿回复；
- run：检索命令、数据导出、图表生成；
- result：EVIDENCE_PACK、manuscript draft、response letter。

这些都使用同一个 `.project_os/` 结构；区别只在领域命令和项目 overlay。
