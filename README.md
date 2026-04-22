# Standard Biometric Information Extraction

## 项目说明

本项目用于将原始结果表中的 `pathogen_old` 字段标准化到病原体字典 `dict_pathogen_feature.xlsx`。

匹配成功后，会在原始表中补齐以下字段：

- `pathogen_name`
- `pathogen_alias`
- `pathogen`
- `pathogen_rank_1`
- `pathogen_rank_2`

如果某条 `pathogen_old` 无法可靠匹配，则以上字段保持为空，同时额外输出未匹配汇总文件，便于后续补充字典。

当前版本除了输出匹配结果、未匹配结果、日志和缓存外，还新增了一个**实时状态表**，用于记录任务开始、结束、失败、耗时和关键统计信息，适合本地批处理和服务器 PBS 提交场景。

## 当前匹配逻辑

项目采用“先规则、后模型”的保守匹配策略，尽量降低误匹配：

1. 读取输入 Excel 和病原体字典 Excel。
2. 校验必要字段。
3. 对字典按 `pathogen_name` 去重。
4. 先做规则匹配：
   - `pathogen_name` 精确匹配
   - `pathogen_alias` 精确匹配
   - `pathogen` 精确匹配
5. 若规则匹配失败，再基于名称相似度召回候选。
6. 将候选列表发送给 `DeepSeek-V3` 做谨慎判定。
7. 仅当模型返回可接受结果时才回填标准字段。
8. 输出匹配结果表、未匹配汇总、缓存、日志和状态表。

## 模型配置

默认使用所内 `DeepSeek-V3` 接口：

- `model_url`: `http://159.226.80.101:1045/v1/chat/completions`
- `model_name`: `DeepSeek-V3`

运行前注意：

- 调用模型前请先关闭 `Clash` 或其他代理。
- 脚本默认会先做一次模型连通性测试。

## 项目结构

```text
Standard_Biometric_Information_Extraction/
├── main.py
├── README.md
├── requirements.txt
├── dict_pathogen_feature.xlsx
├── run_pathogen_mapping_2000.pbs
├── run_pathogen_mapping_3000_more.pbs
├── run_pathogen_mapping_gvn_pub.pbs
└── pathogen_mapping/
    ├── __init__.py
    ├── config.py
    ├── llm_client.py
    ├── logging_utils.py
    ├── matcher.py
    ├── prompts.py
    └── status_table.py
```

## 安装依赖

建议使用 Python 3.10 及以上版本。

```powershell
python -m pip install -r requirements.txt
```

## 命令行参数

`main.py` 当前支持以下主要参数：

- `--input-path`：输入工作簿路径
- `--dict-path`：病原体字典路径
- `--output-path`：匹配结果输出路径
- `--unmatched-path`：未匹配 `pathogen_old` 汇总路径
- `--cache-path`：LLM 匹配缓存路径
- `--log-path`：运行日志路径
- `--status-table-path`：实时状态表路径
- `--model-url`：模型接口地址
- `--model-name`：模型名称
- `--timeout-seconds`：模型请求超时时间
- `--max-retries`：模型最大重试次数
- `--candidate-limit`：发给模型的候选上限
- `--skip-connection-test`：跳过正式处理前的连通性测试
- `--test-connection-only`：只测试模型连通性，不处理 Excel

## 本地运行

### 1. 仅测试模型连通性

```powershell
python main.py --test-connection-only
```

### 2. 正式处理

建议显式传入各输出路径，避免不同批次互相覆盖：

```powershell
python main.py `
  --input-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\biometric_extracted_result_gvn_pub.xlsx" `
  --dict-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\dict_pathogen_feature.xlsx" `
  --output-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\biometric_extracted_result_gvn_pub_matched.xlsx" `
  --unmatched-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\unmatched_pathogen_old_gvn_pub.xlsx" `
  --cache-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\llm_match_cache_gvn_pub.json" `
  --log-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\logs\pipeline_gvn_pub.log" `
  --status-table-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\pathogen_match_status.xlsx"
```

## 输出结果

脚本当前会输出以下文件：

- 匹配结果表：`biometric_extracted_result_*_matched.xlsx`
- 未匹配汇总：`unmatched_pathogen_old_*.xlsx`
- 匹配缓存：`llm_match_cache_*.json`
- 运行日志：`outputs/logs/pipeline_*.log`
- 实时状态表：`outputs/pathogen_match_status.xlsx`

### 状态表说明

状态表由 `pathogen_mapping/status_table.py` 维护。任务开始时会先写入一条“开始”记录；任务结束后会补全该记录，并新增一条最终状态记录；任务异常时会新增失败记录。

状态表中会记录的核心信息包括：

- 数据来源
- 数据类型
- 获取方式
- 当前状态
- 状态说明
- 开始时间
- 结束时间
- 用时
- 原始总行数
- 原始去重后病原体数量
- 去重后未匹配病原体数量
- 匹配成功行数
- 未匹配行数
- 处理后总行数

其中元数据会优先从输入表中自动推断：

- `data_source` 列用于识别数据来源
- `original text` 列可辅助判断是否为非结构化数据
- `source_url` 列可辅助判断是否属于 API 获取

如果无法读取这些信息，则回退为基于文件名和扩展名的默认推断。

## 服务器 PBS 运行

服务器项目目录：

```bash
/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction
```

当前用于服务器提交的脚本为：

```bash
run_pathogen_mapping_gvn_pub.pbs
```

### 提交前准备

确保服务器目录中至少包含：

- `main.py`
- `requirements.txt`
- `dict_pathogen_feature.xlsx`
- `biometric_extracted_result_gvn_pub.xlsx`
- `pathogen_mapping/`
- `run_pathogen_mapping_gvn_pub.pbs`

如 `py39` 环境尚未安装依赖，可执行：

```bash
source /data/homebackup/sunxiuqiang/tools/miniconda3/etc/profile.d/conda.sh
conda activate py39
cd /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction
python -m pip install -r requirements.txt
```

### Windows 转 Linux 换行

```bash
dos2unix run_pathogen_mapping_gvn_pub.pbs
```

### 提交任务

```bash
cd /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction
qsub run_pathogen_mapping_gvn_pub.pbs
```

提交成功后，系统通常会返回一个 `job id`，例如：

```bash
123456.node01
```

### 查看任务状态

```bash
qstat -u sunxiuqiang
```

按任务名筛选：

```bash
qstat -u sunxiuqiang | grep bio_pathogen_match_gvn_pub
```

查看任务详情：

```bash
qstat -f 123456.node01
```

常见 PBS 状态：

- `Q`：排队中
- `R`：运行中
- `C`：已完成
- `E`：结束处理中

### 查看日志与输出

PBS 标准输出：

```bash
tail -f /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_run_gvn_pub.log
```

PBS 标准错误：

```bash
tail -f /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_error_gvn_pub.log
```

程序运行日志：

```bash
tail -f /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/logs/pipeline_gvn_pub.log
```

查看输出目录：

```bash
ls -lh /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs
```

### gvn_pub 脚本当前默认路径

- 输入文件：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/biometric_extracted_result_gvn_pub.xlsx`
- 字典文件：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/dict_pathogen_feature.xlsx`
- 匹配结果：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/biometric_extracted_result_gvn_pub_matched.xlsx`
- 未匹配汇总：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/unmatched_pathogen_old_gvn_pub.xlsx`
- 缓存文件：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/llm_match_cache_gvn_pub.json`
- 运行日志：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/logs/pipeline_gvn_pub.log`
- 状态表：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/pathogen_match_status.xlsx`
- PBS 标准输出：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_run_gvn_pub.log`
- PBS 标准错误：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_error_gvn_pub.log`

## 运行注意事项

- 正式处理前默认会做一次模型连通性测试。
- `--test-connection-only` 模式下不会初始化状态表，也不会处理输入文件。
- 实时状态表默认会持续追加，适合汇总多次批处理任务的执行记录。
- 如果不同批次不希望共用同一个状态表，可为每次任务单独指定 `--status-table-path`。
- 当前仓库还保留了其他 PBS 脚本，如 `run_pathogen_mapping_2000.pbs`、`run_pathogen_mapping_3000_more.pbs`，如需统一接入状态表，可按 `gvn_pub` 脚本同样方式补充 `--status-table-path`。
