# DICOM 上传解析真实场景覆盖与兜底措施

> 目的：回答“当前 repo 在上传、扫描、解析、存储、报告过程中，对真实场景中各种异常情况考虑得是否全面，以及已有兜底措施是什么”。
>
> 日期：2026-05-21  
> 分支：`main`  
> 范围：后端 DICOM ingestion 上传/解析链路，不讨论 PACS、医院系统接入、通用 DICOMweb 产品化。

---

## 1. 一句话结论

当前 repo 对上传解析链路的异常场景已经不是只覆盖 happy path。它已经把真实数据接入中最容易出问题的几类情况拆成了显式层次：

```text
上传接收
  ↓
原始字节持久化
  ↓
输入源枚举：ZIP / 本地文件夹 / 文件列表 manifest / curated manifest
  ↓
扫描：DICOM 候选识别 + ZIP 安全
  ↓
解析：header-only + required tag 校验 + private tag warning
  ↓
存储：Local/NAS 或对象存储 + hash/idempotency + 路径兜底
  ↓
item 级状态轴
  ↓
terminal report
  ↓
duplicate/conflict/replay/reindex
```

核心设计不是“尽量不报错”，而是：

1. **任何输入都要有明确 outcome**：accepted / rejected / failed / quarantined。
2. **坏文件不能吞掉好文件**：局部失败进入 report，不能让整个批次静默消失。
3. **原始字节优先持久化**：后续 retry/replay 不应要求用户重新上传。
4. **安全问题优先拒绝**：ZIP bomb、路径穿越、越权路径不能被“宽容解析”。
5. **重复和冲突不静默覆盖**：同 SOP、同内容、Series 级冲突需要变成显式 finding/summary。
6. **报告不能泄漏敏感细节**：不暴露 PHI 字段和内部绝对路径。

---

## 2. 主要实现入口

| 层 | 关键文件 | 作用 |
|---|---|---|
| 上传持久化 | `backend/src/dicom_ingestion/services/upload/upload_service.py` | 接收 bytes/file-like，计算 hash，写 RawObjectStore，返回 UploadPackage |
| 原始对象存储 | `backend/src/dicom_ingestion/services/storage/raw_object_store.py` | hash 路径、原子写、路径边界检查、按 hash 幂等 |
| ZIP 扫描 | `backend/src/dicom_ingestion/services/scanner/scan_service.py` | 识别 DICOM/非 DICOM，扫描 ZIP/nested ZIP，汇总 ScanManifest |
| ZIP 安全 | `backend/src/dicom_ingestion/services/scanner/zip_safety.py` | zip bomb、路径穿越、entry 数量、entry 大小、嵌套深度限制 |
| 输入源抽象 | `backend/src/dicom_ingestion/sources/*.py` | LocalFolderSource、FileListManifestSource、ZipArchiveSourceAdapter、CuratedUploadManifestSource |
| Pipeline | `backend/src/dicom_ingestion/pipeline/scheduler.py` | 顺序处理 source item，生成 item 状态和 Batch7 报告 |
| Pipeline 报告 | `backend/src/dicom_ingestion/pipeline/report.py` | accepted/rejected/failed/fallback/source_errors 汇总，清理绝对路径和 PHI |
| DICOM 解析 | `backend/src/dicom_ingestion/parser/factory.py`、`backend/src/dicom_ingestion/services/parser/dicom_parser.py` | header-only 解析、required tag 校验、private tag 提取、large file warning |
| 状态模型 | `backend/src/dicom_ingestion/models/ingestion_item.py`、`backend/src/dicom_ingestion/models/ingestion_job.py` | item 七状态轴、terminal outcome、retryable stage、job 状态机 |
| 存储路径 | `backend/src/dicom_ingestion/storage/*.py`、`backend/src/dicom_ingestion/path_generator/local_nas.py` | Local/NAS 路径生成、路径长度兜底、hash fallback、对象存储路径 |
| 重复检测 | `backend/src/dicom_ingestion/services/detection/duplicate_detection.py` | identity duplicate、content duplicate、finding 记录，不静默覆盖 canonical |
| Series 冲突 | `backend/src/dicom_ingestion/services/conflict/series_conflict.py` | exact duplicate / partial overlap / content conflict / UID conflict 分类 |
| replay/reindex | `backend/src/dicom_ingestion/services/replay/replay_service.py`、`backend/src/dicom_ingestion/services/reindex/reindex_workflow.py` | 从已存储字节重放、失败项重试、投影重建 |
| 输入安全 | `backend/src/dicom_ingestion/security/input_validator.py` | 路径、UID、文件名基础校验 |

---

## 3. 异常覆盖矩阵

### 3.1 上传接收与原始字节持久化

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| 空上传 | `UploadService.accept` 对空 bytes 抛 `ValueError("Empty upload not allowed")` | 请求不进入后续 pipeline，避免空对象变成假成功 | 已实现 + 测试 |
| 输入类型错误，例如传字符串路径 | 只接受 `bytes` 或 file-like；字符串路径被拒绝 | 防止后端误把用户提供路径当本地可信路径读取 | 已实现 + 测试 |
| 对象存储写失败 | 抛 `UploadPackageStoreFailed` | 不返回 UploadPackage，避免“用户以为上传成功但字节丢失” | 已实现 + 测试 |
| 写入后无法验证存在 | `exists(uri)` 校验失败则抛 `UploadPackageStoreFailed` | 写入必须可读才算成功 | 已实现 |
| 同内容重复上传 | RawObjectStore 使用 content hash 作为存储 key | 同 bytes 得到同 URI，存储幂等，不重复占用 | 已实现 + 测试 |
| 相同内容、不同文件名 | URI 相同，但 `original_filename` 分别保留在 package 上 | 字节去重不抹掉上传来源 | 已实现 + 测试 |
| ZIP 输入 | raw ZIP 先作为完整 bytes 存储，再扫描/解压 | 保留原始证据包，后续 replay/debug 有源头 | 已实现 + 测试 |
| RawObjectStore URI 越界 | `_resolve_safe_path` 用 commonpath 限制 URI 在 base_dir 内 | 防止读取/删除 base_dir 外文件 | 已实现 |

### 3.2 ZIP 与压缩包安全

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| 普通 ZIP 内含 DICOM | `ScanService` 解包，保留 ZIP 内相对路径 | 每个 entry 变成 ScanItem，进入后续 item 处理 | 已实现 + 测试 |
| ZIP 内混合 DICOM 和非 DICOM | DICOM accepted，非 DICOM `REJECTED_NON_DICOM` | 混合包不因 readme/说明文件整体失败 | 已实现 + 测试 |
| nested ZIP | 支持递归扫描 | 保留组合路径，例如 `outer.zip/inner.dcm` | 已实现 + 测试 |
| 嵌套过深 | 超过 max depth 产生 `NestedZipTooDeep` 或 REJECTED_UNSAFE | 阻止无限递归/递归炸弹 | 已实现 + 测试 |
| zip bomb，总展开大小过大 | `ZipSafetyScanner` 检查 claimed size | 提前拒绝，不完整解压 | 已实现 + 测试 fixture |
| 单 entry 过大 | `max_entry_bytes` 限制 | 阻止超大单文件拖垮 worker | 已实现 |
| entry 数量过多 | `max_entry_count` 限制 | 阻止海量小文件压垮扫描/DB | 已实现 + 测试 |
| 压缩比异常 | compression ratio > 100 且 entry > 1MB 判为可疑 | 针对典型高压缩比 bomb 做提前拦截 | 已实现 + 测试 |
| ZIP path traversal，例如 `../etc/passwd` | `UnsafeArchivePath` | 不解压、不写磁盘、不进入 downstream | 已实现 + 测试 fixture |
| top-level ZIP 安全失败 | `scan_errors` 记录，`rejected_count` 增加 | 报告上可见不是“0 文件成功” | 已实现 + 测试 |
| 对象存储 URI 读取 ZIP/包失败 | `PackageReadFailed` 进入 `scan_errors` | 失败结构化呈现，不抛成未知崩溃 | 已实现 + 测试 |

### 3.3 文件夹、路径、manifest 输入源

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| 文件夹不存在 | `LocalFolderSource.validate` 抛 `FileNotFoundError` | job fatal report 记录 source error | 已实现 |
| 输入不是目录 | 抛 `NotADirectoryError` | 防止把文件当目录遍历 | 已实现 |
| 本地路径不在 allowed_roots 内 | 抛 `ValueError` | 限制 server-side path 能力，只能访问批准根目录 | 已实现 |
| 空文件夹 | pipeline completed，total_items = 0 | 空批次不是崩溃，也不是假失败 | 已实现 + 测试 |
| 遍历中遇到不可读文件 | source errors 写 `SourceFileUnreadable`，继续其他文件 | 单个坏文件不阻断整个文件夹 | 已实现 |
| 文件超过配置大小 | source errors 写 `FileTooLarge` | 文件级拒绝，其他文件继续 | 已实现 |
| 文件数超过配置 | source errors 写 `MaxItemsExceeded` 后停止枚举 | 给 worker/DB 一个明确上限保护 | 已实现 |
| file-list manifest 路径越权 | `ManifestPathOutsideAllowedRoot` | 防止 manifest 指向任意服务器文件 | 已实现 |
| file-list manifest 文件不存在 | `ManifestFileNotFound` | 错误进入 source errors | 已实现 |
| curated manifest JSON 不合法 | `CuratedManifestInvalidJson` | fatal manifest error，report 保留具体 error_code | 已实现 + 测试 |
| curated manifest 缺 data 路径 | `CuratedManifestMissingDataPath` | 不进入误解析 | 已实现 |
| curated manifest data 越权 | `CuratedManifestDataPathOutsideAllowedRoot` | 不泄漏绝对路径到 report | 已实现 + 测试 |
| annotation 路径缺失 | optional annotation 只进 report；required annotation 使 item rejected | 支持“标签缺失可选/必需”两种真实数据情况 | 已实现 + 测试 |
| annotation 文件被误解析为 DICOM | curated manifest 只把 annotation 挂为 ref，不作为 standalone ingest item | 防止 label/mask/json 被拿去走 DICOM parser | 已实现 + 测试 |
| curated sample id 重复 | `DuplicateCuratedSampleId`，重复样本不进入 items | 防止同一个 sample 被隐式覆盖 | 已实现 |

### 3.4 DICOM 识别与解析

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| 非 DICOM 文件 | scan/pipeline 检查 byte 128 处 `DICM` magic，不符合则 `NotDicomFile` | 文件级 rejected，后续 axes 关闭 | 已实现 + 测试 |
| 文件太小 | parser 抛 `DicomParseFailed` 或 scan 判 non-DICOM | 不让小文件进入假解析 | 已实现 + 测试 |
| 空 item bytes | parser 抛 `DicomParseFailed("Empty item bytes")` | 解析失败可区分 | 已实现 + 测试 |
| truncated/corrupt DICOM | pydicom 读取失败转 `ParseError`/`DicomParseFailed` | item rejected，bytes/source path 保留，report 写原因 | 已实现 + 测试 fixture |
| 缺 required tags | Configurable parser 返回 `success=False`，pipeline 置 `MissingRequiredDicomTag` | 文件被 rejected，不作为 accepted instance | 已实现 + 测试 |
| optional/recommended tag 缺失 | TagValidator 可返回 warning/incomplete；路径生成有 fallback 值 | 缺可选字段不阻断导入，但 report 可统计 fallback | 已实现 |
| 大文件 / PixelData 过大 | parser 使用 `stop_before_pixels=True` 和 `defer_size="1KB"` | header-only 解析，避免把像素数据全读进内存 | 已实现 |
| 超过 512MB 文件 | Configurable parser 加 large file warning | 目前是 warning，不是硬拒绝 | 已实现 |
| private tag 解析器异常 | extractor 异常变成 warning，不让整体 parse failed | 私有标签不稳定不阻断标准 DICOM 导入 | 已实现 |
| UID 格式异常 | `TagValidator.validate_uids` 可发现非数字/点格式 | 当前属于 validator 能力，pipeline 中不是主拒绝路径 | 部分实现 |
| pydicom 缺失 | `DicomParseFailed("pydicom library is not available")` | 环境配置错误显式失败 | 已实现 |

### 3.5 存储、路径生成、去重与版本化

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| Local/NAS 未配置 | `StorageManager.store_for_archive` 抛 `StorageManagerError` | pipeline 将 item 标记为 failed，report 写 failed_tasks | 已实现 |
| 磁盘写入失败 / disk full | storage exception 被捕获，item `FAILED`，error `UploadPackageStoreFailed` | job 可完成为部分失败，失败项可后续 retry | 已实现 + 测试 |
| 同路径同内容 | LocalNASStorageBackend 比对 checksum，相同则返回现有位置 | 避免同 bytes 生成多版本 | 已实现 + 测试 |
| 同路径不同内容 | 生成 `_v001`, `_v002` 等版本化路径 | 防止静默覆盖旧文件 | 已实现 |
| 路径组件过长 | PathGenerator 限制组件长度，Storage 负责完整路径长度 | 组件级 + 全路径级双兜底 | 已实现 |
| base_path 过长 | Storage 抛 `StorageError`，提示缩短 base_path 或增大 max_path_length | 不生成不可用路径 | 已实现 |
| 仍然过长 | 回退到 hash structure / `OVERFLOW` | 降低可读性，保住可存储性 | 已实现 |
| 组件含非法字符 / 路径穿越 | PathGenerator sanitize，替换非法字符，去掉 `../` | 防止 tag 值污染存储路径 | 已实现 |
| storage_root_id 非 URI safe | `_validate_storage_root_id` 限制 `[A-Za-z0-9_-]+` | 平台 URI 不含危险字符 | 已实现 |
| report 泄漏内部路径 | report sanitizer 移除 `absolute_path`、`local_path` 等内部 key | 用户报告只显示平台 URI/相对路径 | 已实现 + 测试 |

### 3.6 item/job 状态、报告与用户可解释性

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| 单个文件失败但其他成功 | item 独立 terminal_outcome；job 仍可 completed | report 显示 accepted/rejected/failed 数量 | 已实现 + 测试 |
| rejected item 下游状态一直 pending | `close_pending_axes()` 把 parse/storage/metadata/validation/binding/index 关闭 | UI 不会看到“已拒绝但还在等待解析”的假状态 | 已实现 + 测试 |
| storage failed | terminal_outcome = failed，last_retryable_stage = storage | 明确可重试阶段 | 已实现 + 测试 |
| parse failed | terminal_outcome = rejected 或 failed，last_retryable_stage = parse | 错误原因写入 report | 已实现 |
| job 级 fatal error | `Batch7PipelineScheduler.run` 捕获异常，job.fail，report 中增加 source error | 不丢失已处理 items | 已实现 |
| report 里出现 PHI | Batch7 report 只投影 study/series/sop/modality，不输出 patient_name/patient_id | 减少报告泄漏 PHI 风险 | 已实现 + 测试 |
| source error 带绝对路径 | `sanitize_source_error` 只保留文件名或清理 detail | 不把服务器路径暴露给用户 | 已实现 + 测试 |
| 空批次 | report total_items=0，accepted=0 | 可解释空输入 | 已实现 + 测试 |
| 报告服务重启 | TerminalReportService 可通过 repository 持久化 report，cache 只是加速 | report 不只依赖内存 | 已实现 + 测试 |

### 3.7 重复、冲突与 canonical 安全

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| 同 SOPInstanceUID 再次出现 | DuplicateDetectionService 识别 identity duplicate | 创建 duplicate finding，不覆盖 canonical | 已实现框架 |
| 同内容不同 SOP | 支持 whole_file_sha256 / pixel_digest content duplicate | 区分身份重复和内容重复 | 已实现框架 |
| duplicate 检测服务异常 | 捕获异常并记录日志，不让整条 ingestion 因 duplicate check 崩掉 | duplicate finding 可能缺失，但 ingest 不被阻断 | 已实现 |
| Series 完全重复 | SeriesConflictService 分类 `exact_duplicate` | exact duplicate 不能人为 resolve 成覆盖 | 已实现框架 + 测试 |
| Series 部分重叠 | 分类 `partial_overlap` | 交给用户/操作员判断，不静默合并 | 已实现框架 |
| 同 SOP 不同内容 | 分类 `content_conflict` 优先级最高 | 内容冲突比 overlap 分类更优先 | 已实现框架 + 测试 |
| UID reuse / 低重叠 | 分类 `uid_conflict` | 暴露可能的 UID 复用问题 | 已实现框架 |
| 用户 resolution 重复操作 | resolved 后不能再次 resolve | 防止 canonical 决策反复漂移 | 已实现框架 + 测试 |

注意：重复/冲突层目前更多是服务框架和模型语义，和 Batch7 in-process pipeline 的直接集成程度需要后续继续加强。文档上应该把它视为“已有能力与目标语义”，不是所有上传入口都已端到端触发。

### 3.8 Retry、replay、reindex

| 真实场景 | 当前处理 | 兜底措施 | 覆盖状态 |
|---|---|---|---|
| 用户不想重新上传失败文件 | ReplayService 从 storage URI 读取原始 bytes | retry/replay 不依赖用户重新上传 | 已实现框架 + 测试 |
| item 没有 storage URI | replay 返回 `NotReplayable` | 防止无源重放 | 已实现 + 测试 |
| item 不存在 | replay 返回 `ItemNotFound` | 结构化失败 | 已实现 + 测试 |
| 批量 retry | RetryRequest 支持 job 或 item ids，支持 dry_run | 先预览再执行 | 已实现框架 + 测试 |
| 投影/索引坏了 | ReindexWorkflow 支持 plan/execute/validate/analyze/verify | 不需要重新上传原始数据 | 已实现框架 + 测试 |

---

## 4. 当前 repo 的“兜底思想”总结

### 4.1 文件级失败优先，不轻易 job 级失败

混合文件夹、混合 ZIP、curated manifest 的设计都在避免一个问题：一个坏文件让整个批次不可用。

已有行为：

- 非 DICOM 文件进入 rejected；
- 缺 required tag 的 DICOM 进入 rejected；
- storage 失败进入 failed；
- optional annotation missing 只进入 report，不拒绝 item；
- required annotation missing 才拒绝 item；
- source enumeration errors 被合并进 report。

这适合真实医学数据：用户经常会把说明文件、标注文件、坏片、重复片、半截传输文件混在一个目录里。

### 4.2 安全问题是硬边界

ZIP bomb、路径穿越、allowed_roots 越权、RawObjectStore URI 越界，这些不是普通 warning，而是安全边界。

当前倾向：

- ZIP 安全失败直接拒绝；
- server-side path 必须在 allowed_roots；
- manifest 不能随便引用服务器任意路径；
- report 不泄漏绝对路径。

### 4.3 解析走 header-only，避免像素数据拖垮内存

DICOM 解析默认只读 header：

- `stop_before_pixels=True`；
- `defer_size="1KB"`；
- 大文件只 warning；
- pixel digest 只在 FULL 模式才计算。

这适合 ingestion 的第一阶段：先建立 Study/Series/Instance 身份和报告，不急着读取完整像素。

### 4.4 报告是核心产物，不是日志

当前 Batch7 report 和 TerminalReport 都把 report 设计成机器可读产物：

- summary；
- storage；
- rejections；
- failed_tasks；
- item-level status_axes；
- dicom_identity；
- annotation_summary；
- fallbacks。

这比“日志里有错误”更适合前端和操作员使用。

### 4.5 duplicate 不是一个布尔值

设计上已经区分：

- identity duplicate：同 SOPInstanceUID；
- content duplicate：同 whole file hash 或 pixel digest；
- exact duplicate：Series SOP 集完全一致且内容一致；
- partial overlap：Series 有交集但不完全相同；
- content conflict：同 SOP 但内容 hash 不同；
- UID conflict：低重叠，怀疑 UID reuse。

这点很重要。真实数据里“重复”经常不是“删掉一个”那么简单。

---

## 5. 已有测试覆盖信号

关键测试文件：

| 文件 | 覆盖重点 |
|---|---|
| `backend/tests/services/upload/test_upload_service.py` | 空上传、非法输入、存储失败、ZIP raw store、hash 幂等、missing URI |
| `backend/tests/services/scanner/test_scan_service.py` | 非 DICOM、ZIP 混合内容、nested ZIP、ZIP bomb、path traversal、entry count、URI read failure |
| `backend/tests/services/parser/test_dicom_parser.py` | 空 bytes、太小文件、invalid DICOM、valid CT、truncated fixture |
| `backend/tests/services/parser/test_tag_validator.py` | required/recommended tag、strict mode、UID 格式 |
| `backend/tests/pipeline/test_batch7_pipeline.py` | 混合文件夹、missing required、storage failure、空文件夹、PHI/绝对路径清理、pending axes 关闭、临时文件清理 |
| `backend/tests/pipeline/test_curated_manifest_pipeline.py` | annotation refs、required/optional annotation、manifest fatal error code、绝对路径清理 |
| `backend/tests/services/reporting/test_terminal_report.py` | success/partial/failure/empty report、持久化、failure summary |
| `backend/tests/services/replay/test_replay_service.py` | replay from storage URI、无 URI 不可 replay、dry run、无失败项 |
| `backend/tests/services/reindex/test_reindex_workflow*.py` | projection rebuild/reindex 状态和 scope |
| `backend/tests/security/test_input_validator.py` | 路径穿越、null byte、UID 字符、文件名扩展 |

测试 fixture 已经包含：

- `not_dicom.txt`；
- `truncated.dcm`；
- `missing_required_tag.dcm`；
- `valid_zip_42_files.zip`；
- `zip_bomb.zip`；
- `zip_path_traversal.zip`；
- `zip_nested_3_deep.zip`；
- `mixed_content.zip`；
- identity duplicate pair；
- content duplicate pair；
- private tag fixture；
- RTSTRUCT / SR / SEG / multi-frame CT。

---

## 6. 仍然需要注意的缺口

这些不是否定当前覆盖，而是后续实现和前端/API 对齐时需要继续盯住的点。

### 6.1 Batch7 pipeline 与 duplicate/conflict 的端到端集成还需确认

DuplicateDetectionService 和 SeriesConflictService 已经有模型和服务语义，但当前 in-process Batch7 pipeline 主要证明 folder/source → parser → storage → report。后续要确认：

- accepted item 是否端到端创建 canonical observation；
- duplicate finding 是否进入 Batch7 report；
- Series conflict summary 是否能从同一个 upload job 自动构建；
- 前端是否能看到 Series 级 exact duplicate / partial overlap / content conflict。

### 6.2 API 层上传入口还需要把这些 error_code 保持透传

底层已经有结构化 error_code，但如果 REST/controller 层把它们压成 `500 Internal Server Error` 或普通字符串，前端仍然无法解释。

API 层应保证：

- `EmptyUploadRequest`；
- `UploadTooLarge`；
- `ZipBombDetected`；
- `UnsafeArchivePath`；
- `NotDicomFile`；
- `MissingRequiredDicomTag`；
- `UploadPackageStoreFailed`；
- `CuratedManifest*`；
- `AnnotationPath*`；

这些 code 能稳定出现在 job report 和 API response 中。

### 6.3 多文件/文件夹 Web 上传的 relative path 需要强约束

后端 source abstraction 已经要求 `original_relative_path`，但前端如果用普通 multi-file input，可能只给 `file.name`，目录结构会丢。

前端/API 应明确：

- 文件夹上传必须传 `webkitRelativePath` 或等价 relative path；
- 多文件上传如果没有 relative path，只能作为轻量入口；
- 同名文件必须带路径 disambiguation；
- ZIP 内路径和 folder relative path 进入后端后语义一致。

### 6.4 retry/replay 的真实 worker 幂等还要继续做端到端压测

模型上已有 `last_retryable_stage`、ReplayService、reindex workflow。但生产 worker 化后还要验证：

- worker 重复执行不会重复写 canonical rows；
- storage succeeded 但 metadata failed 时能从 stored URI 恢复；
- retry exhaustion 后 report 能显示最终失败；
- 同一 failed item 多次 retry 的 audit history 足够清楚。

### 6.5 quarantine 语义目前有模型位，但 pipeline 使用较少

`TerminalOutcome` 支持 `QUARANTINED`，TerminalReport 也支持 quarantined count。但当前 Batch7 pipeline 主要使用 accepted/rejected/failed。

后续可以考虑哪些情况应 quarantine 而不是 reject：

- 可疑 PHI；
- tag 值格式异常但人工可修；
- suspicious duplicate；
- required metadata 可由用户补充；
- binding policy 失败但 DICOM 本身有效。

### 6.6 大文件策略目前偏 warning，不是完整 backpressure

parser 对 >512MB 文件会 warning，ZIP safety 有 entry/total 限制，但 API/worker 层还需要统一：

- 单文件上传大小上限；
- folder upload 总大小上限；
- 并发数；
- worker memory budget；
- 解析超时；
- 取消语义。

### 6.7 报告的用户文案还需要产品化

底层 error_code 是机器可读的，但前端需要把它转成用户能懂的提示：

- `NotDicomFile` → “不是 DICOM 文件，已跳过”；
- `MissingRequiredDicomTag` → “缺少 Study/Series/SOP 等必需标签，无法纳入数据集”；
- `ZipBombDetected` → “压缩包展开后超过安全限制，已拒绝”；
- `UnsafeArchivePath` → “压缩包包含不安全路径，已拒绝”；
- `UploadPackageStoreFailed` → “存储失败，可稍后重试”。

---

## 7. 建议给前端/产品的展示方式

上传解析结果页不要只展示“成功/失败”，建议展示四块：

```text
总览
- 总文件数
- accepted
- rejected
- failed
- warnings

问题文件
- relative path
- error code
- 用户友好说明
- 是否可重试

存储结果
- local-nas/object
- stored count
- 平台 URI

重复/冲突
- exact duplicate
- partial overlap
- content conflict
- UID conflict
```

对于用户最关心的“我这批数据到底有没有进去”，应避免含糊状态：

- accepted：进入平台数据集；
- rejected：数据本身或安全策略不允许进入；
- failed：系统处理失败，可 retry；
- quarantined：待人工确认。

---

## 8. 推荐下一步验收清单

如果要验证“考虑是否全面”，建议用下面这组场景跑端到端：

1. 正常 DICOM 单文件。
2. 正常 DICOM 文件夹，含多层 patient/study/series 目录。
3. 混合文件夹：DICOM + txt + missing required tag + truncated DICOM。
4. 空文件夹。
5. ZIP：正常 mixed zip。
6. ZIP：zip bomb。
7. ZIP：path traversal。
8. ZIP：nested 超深。
9. curated manifest：data + optional annotation 缺失。
10. curated manifest：required annotation 缺失。
11. curated manifest：data path 越权。
12. storage failure：模拟 disk full。
13. 同内容重复上传。
14. 同 SOPInstanceUID 不同 bytes。
15. 同 Series 部分 overlap。
16. report 检查：不能出现 patient_name、patient_id、绝对路径。
17. retry failed item：不要求用户重新上传。
18. reindex/report rebuild：不要求用户重新上传。

这 18 个场景覆盖真实数据接入里最常见的坏包、脏文件、重复、越权、存储失败、用户解释性问题。

---

## 9. 总结

当前 repo 的上传解析链路已经有比较系统的异常考虑：

- 上传层有 raw bytes 持久化、hash 幂等、空输入和类型拒绝；
- 扫描层有 DICOM/non-DICOM 分流和 ZIP 安全边界；
- source 层有 folder、manifest、curated manifest 的 allowed root 和 missing annotation 语义；
- parser 层有 header-only、大文件 warning、required tag、private extractor warning；
- storage 层有 checksum 去重、版本化、防覆盖、路径长度 fallback；
- pipeline/report 层有 item outcome、failed_tasks、source_errors、PHI/绝对路径清理；
- duplicate/conflict/replay/reindex 层已经有可扩展框架。

真正需要继续盯的是端到端整合：特别是 API 层 error_code 透传、前端 relative path 保留、duplicate/conflict 进入报告、worker retry 幂等和 quarantine 语义落地。
