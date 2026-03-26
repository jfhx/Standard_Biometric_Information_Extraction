# Standard Biometric Information Extraction

## 项目目标

本项目用于把原始结果表 `biometric_extracted_result_1000.xlsx` 中的 `pathogen_old` 字段，匹配到字典表 `dict_pathogen_feature.xlsx` 中的标准病原体名称 `pathogen_name`。匹配时会同时参考字典表中的 `pathogen_name` 和 `pathogen_alias` 两列，其中 `pathogen_alias` 为病原体别名列，多个别名使用英文分号 `;` 分隔，并与对应的 `pathogen_name` 一一对应。

匹配成功后，会在原始结果表中补齐以下字段：

- `pathogen_name`
- `pathogen_alias`
- `pathogen`
- `pathogen_rank_1`
- `pathogen_rank_2`

其中：

- 如果 `pathogen_old` 与字典表中的 `pathogen_name` 精确匹配成功，则直接回填该条标准记录。
- 如果 `pathogen_name` 没有命中，但 `pathogen_old` 与某个 `pathogen_alias` 高精度、无歧义地匹配成功，则回填该 `pathogen_alias` 对应的 `pathogen_name`。
- 如果 `pathogen_name` 和 `pathogen_alias` 都不能高置信度匹配成功，则 `pathogen_name` 和 `pathogen_alias` 等输出字段保持为空。

最终会在原表中把这五个字段插入到 `pathogen_old` 后面：

- `pathogen_name`
- `pathogen_alias`
- `pathogen`
- `pathogen_rank_1`
- `pathogen_rank_2`

如果 `pathogen_old` 无法准确匹配到标准 `pathogen_name`，则这五个字段保持为空，并额外输出未匹配成功的 `pathogen_old` 汇总文件，方便后续补充到字典表中。

## 模型接口

本项目默认使用所内 DeepSeek-V3 接口：

- 地址：`http://159.226.80.101:1045/v1/chat/completions`
- 模型名：`DeepSeek-V3`
- API Key：不需要

运行前请注意：

- **调用该模型前请先退出 Clash**
- 接口仅接受 JSON 请求，本项目已经按 JSON 请求格式实现

## 匹配逻辑

项目采用“保守匹配”策略，尽量避免错配：

1. 先读取原始 Excel 和字典 Excel。
2. 校验必要字段是否存在，字典表中至少需要包含 `pathogen_name`、`pathogen_alias`、`pathogen`、`pathogen_rank_1`、`pathogen_rank_2`。
3. 对字典表中的 `pathogen_name` 做去重，并同时读取每个标准病原体对应的 `pathogen_alias`。
4. 先做规则级匹配：
   - 标准名精确匹配
   - `pathogen_alias` 精确匹配
   - 缩写精确匹配
   - 如果 `pathogen_alias` 精确命中且只指向唯一标准病原体，则回填该 alias 对应的 `pathogen_name`
5. 若规则匹配不到，则基于名称相似度召回一批候选项。
6. 把候选项和 `pathogen_old` 一起发给 DeepSeek-V3，让模型只在候选列表中做谨慎判断；候选项中会同时提供 `pathogen_name` 和 `pathogen_alias`。
7. 只有模型明确判断为同一个病原体，且置信度足够时，才接受匹配结果；如果只是 alias 看起来相似但不够确定，则保持为空。
8. 若模型认为不确定或没有准确对应项，则保持为空，不强行匹配。
9. 根据匹配到的 `pathogen_name` 回填 `pathogen_alias`、`pathogen`、`pathogen_rank_1`、`pathogen_rank_2`。
10. 输出补齐后的 Excel、未匹配汇总、日志和缓存文件。

## 项目结构

```text
Standard_Biometric_Information_Extraction/
├─ biometric_extracted_result_1000.xlsx
├─ dict_pathogen_feature.xlsx
├─ main.py
├─ README.md
├─ requirements.txt
└─ pathogen_mapping/
   ├─ __init__.py
   ├─ config.py
   ├─ llm_client.py
   ├─ logging_utils.py
   ├─ matcher.py
   └─ prompts.py
```

## 安装依赖

建议使用 Python 3.10 及以上版本。

```powershell
python -m pip install -r requirements.txt
```

## 先测试模型连通性

```powershell
python main.py --test-connection-only
```

如果连接成功，会输出连接测试成功信息，并在日志中记录模型返回内容。

## 处理 Excel

直接运行：

```powershell
python main.py
```

## 本地运行示例

先测试模型连通性：

```powershell
python main.py --test-connection-only
```

正式处理：

```powershell
python main.py \
  --input-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\biometric_extracted_result_1000.xlsx" \
  --dict-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\dict_pathogen_feature.xlsx" \
  --output-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\biometric_extracted_result_1000_matched.xlsx" \
  --unmatched-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\unmatched_pathogen_old.xlsx"
```

## 可选参数

```powershell
python main.py \
  --input-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\biometric_extracted_result_1000.xlsx" \
  --dict-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\dict_pathogen_feature.xlsx" \
  --output-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\biometric_extracted_result_1000_matched.xlsx" \
  --unmatched-path "C:\Users\imcas\Desktop\Standard_Biometric_Information_Extraction\outputs\unmatched_pathogen_old.xlsx"
```

常用可选参数：

- `--skip-connection-test`：跳过运行前的模型连通性测试
- `--test-connection-only`：只测试模型连接，不处理 Excel
- `--candidate-limit`：每条 `pathogen_old` 发给模型的候选项上限
- `--timeout-seconds`：模型请求超时时间
- `--max-retries`：模型请求失败后的重试次数
- `--model-url`：自定义模型地址
- `--model-name`：自定义模型名称

## 服务器运行

服务器项目路径：

```bash
/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction
```

项目中已提供 PBS 脚本：

```bash
run_pathogen_mapping_1000.pbs
```

### 服务器端准备

确保服务器目录中至少包含以下文件：

- `main.py`
- `requirements.txt`
- `biometric_extracted_result_1000.xlsx`
- `dict_pathogen_feature.xlsx`
- `pathogen_mapping/`
- `run_pathogen_mapping_1000.pbs`

### 服务器端安装依赖

如果 `py39` 环境里还没有安装依赖，可先执行：

```bash
source /data/homebackup/sunxiuqiang/tools/miniconda3/etc/profile.d/conda.sh
conda activate py39
cd /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction
python -m pip install -r requirements.txt
```

### window 转linux 系统的命令行
```bash
dos2unix run_pathogen_mapping_1000.pbs
```

### 提交 PBS 任务
```bash
cd /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction
qsub run_pathogen_mapping_1000.pbs
```

提交成功后，系统通常会返回一个 `job id`，例如：
```bash
123456.node01
```

### 查看任务状态
查看当前用户全部 PBS 任务：
```bash
qstat -u sunxiuqiang
```

按任务名筛选当前项目任务：
```bash
qstat -u sunxiuqiang | grep bio_pathogen_match_1000
```

查看某个指定任务的详细信息：
```bash
qstat -f 123456.node01
```

常见任务状态含义：

- `Q`：排队中
- `R`：运行中
- `C`：已完成
- `E`：任务结束处理中

### 查看日志文件

查看 PBS 标准输出日志：
```bash
cat /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_run_1000.log
```

实时追踪 PBS 标准输出日志：
```bash
tail -f /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_run_1000.log
```

查看 PBS 标准错误日志：
```bash
cat /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_error_1000.log
```

实时追踪 PBS 标准错误日志：
```bash
tail -f /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_error_1000.log
```

查看程序运行日志：
```bash
cat /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/logs/pipeline_1000.log
```

实时追踪程序运行日志：
```bash
tail -f /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/logs/pipeline_1000.log
```

查看未匹配病原体汇总文件是否已生成：
```bash
ls -lh /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/
```

### 常见排查命令

查看项目目录文件：
```bash
ls -lh /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction
```

查看输出目录文件：
```bash
ls -lh /data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs
```

如果任务长时间没有运行，可先检查是否仍在排队：
```bash
qstat -u sunxiuqiang
```

如果任务已经结束，但没有生成结果，优先查看：
- `task_error_1000.log`
- `task_run_1000.log`
- `outputs/logs/pipeline_1000.log`

如果 `task_run_1000.log` 和 `task_error_1000.log` 都不存在，先优先检查 PBS 脚本中的 `#PBS -o`、`#PBS -e` 和 `PROJECT_DIR` 路径是否真实存在；如果这些路径写错，PBS 任务虽然会结束，但日志文件可能不会被正常落盘，此时通常还会收到系统邮件提醒：

```bash
mail
```

或直接查看邮箱文件：

```bash
cat /var/spool/mail/sunxiuqiang
```

### PBS 脚本中的默认输入输出路径

- 输入原表：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/biometric_extracted_result_1000.xlsx`
- 输入字典表：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/dict_pathogen_feature.xlsx`
- 匹配结果表：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/biometric_extracted_result_1000_matched.xlsx`
- 未匹配汇总：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/unmatched_pathogen_old_1000.xlsx`
- 缓存文件：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/llm_match_cache_1000.json`
- 运行日志：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/outputs/logs/pipeline_1000.log`
- PBS 标准输出：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_run_1000.log`
- PBS 标准错误：`/data7/sunxiuqiang/nhp/Standard_Biometric_Information_Extraction/task_error_1000.log`

### 服务器运行注意事项

- 提交任务前请确保调用模型时不会经过 Clash 或其他代理。
- 当前脚本会在正式处理前先做模型连通性测试。
- 若需要修改输入输出文件名，可直接编辑 `run_pathogen_mapping_1000.pbs` 中的路径变量。

## 输出结果

默认输出到 `outputs/` 目录：

- `biometric_extracted_result_1000_matched.xlsx`
  - 在 `pathogen_old` 后新增五列：
    - `pathogen_name`
    - `pathogen_alias`
    - `pathogen`
    - `pathogen_rank_1`
    - `pathogen_rank_2`
  - 即使某条 `pathogen_old` 没有匹配成功，也仍然会保留这些新增列，只是对应单元格为空
- `unmatched_pathogen_old.xlsx`
  - 统计所有未匹配成功的原始 `pathogen_old`
  - 包含每个名字出现的次数 `count`
- `llm_match_cache.json`
  - 缓存已判断过的病原体名称，避免重复请求模型
- `run.log`
  - 运行日志、异常信息、处理汇总

## 日志与异常处理

项目已经包含：

- 文件日志与控制台日志
- 输入列校验
- 模型请求重试
- 模型响应 JSON 解析
- 失败异常记录
- 缓存容错读取

## 说明

- 本项目强调 **不要匹配错**，因此策略是宁可空着，也不强行猜测。
- `pathogen_alias` 只在能够高把握确认其与某个标准 `pathogen_name` 一一对应时才会用于回填。
- 如果字典表中确实没有对应的标准病原体名称，结果会保持为空，并进入未匹配汇总。
- 未匹配汇总可作为后续补充 `dict_pathogen_feature.xlsx` 的依据。
