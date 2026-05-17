# DICOM Ingestion 源码研究矩阵

## 1. 目的

这份文档只记录**已经从源码中确认过**的事实，用来替代此前过于概括的“项目值得参考”说法。后续设计只能引用这里已经落地的证据，不能再凭项目名做判断。

## 2. 源码证据表

| 项目 | 研究问题 | 源码位置 | 已确认的实现 | 对我们的启发 | 不应照搬 |
| --- | --- | --- | --- | --- | --- |
| Dicoogle | 索引任务是不是一级能力 | `sdk/.../IndexerInterface.java`、`sdk/.../task/Task.java` | `index(file)` 与 `index(files)` 都返回异步 `Task<Report>`；批量 `unindex` 也有异步任务、失败收集、进度回调 | `metadata index` 不应只是“导入后顺手写一下”，应有独立任务边界、报告、失败明细和可重建能力 | 不照搬它的 PACS 产品形态 |
| Dicoogle | 无法仅凭扩展名判断 DICOM 时怎么处理 | `IndexerInterface.handles(URI)` | 默认建议“有疑问就尝试读取，让 indexer 捕获异常”，而不是过度依赖 URI / 扩展名 | 我们的 scanner 应把“快速过滤”和“最终解析判定”分开，不能只看 `.dcm` 后缀 | 不把所有识别逻辑压进文件名规则 |
| XNAT | ingestion 是否应默认只读 header | `libs/dicomtools/.../DicomUtils.java` | 提供 `getMaxStopTagInputHandler()`，明确“读取所有 tag 到 PixelData 之前”为最大有用范围；`read()` 在无 `SOPClassUID` 时直接判为非 DICOM | 我们应把 `header-only parse` 设计成默认模式，并把 `SOPClassUID` 等存在性校验纳入 DICOM 识别 | 不照搬 XNAT 旧版 dcm4che2 API |
| XNAT | DICOM 到业务对象的映射怎么扩展 | `web/.../DicomObjectIdentifier*`、`ArchiveProcessorInstanceApi.java` | 通过可配置 identifier / processor 体系做接收后识别和处理，而不是把映射逻辑硬编码进单一导入函数 | 我们应把“metadata 解析”和“Asset / Sample 归属规则”分层，支持策略化映射 | 不照搬 Project / Subject / Session 业务模型 |
| dcm4che | private tag 如何工程化支持 | `dcm4che-dict-priv/.../PrivateElementDictionary.java.xsl`、`META-INF/services/.../ElementDictionary` | private dictionary 按 private creator 拆分，并通过服务发现机制注册大量厂商字典 | 我们的 private tag 体系至少要分 `raw retention`、`vendor dictionary`、`platform mapping` 三层 | 不要把所有 private tag 规则塞进一个巨型硬编码映射 |
| Kaapana | metadata extraction 是否应任务化 | `data-processing/.../dag_collect_metadata.py` | `GetInput → DcmAnonymizer(single_slice=True) → Dcm2Json → ConcatJson → Minio → Cleaner` 被定义成 DAG，且显式有 retry、concurrency、max_active_runs | 我们的 ingestion 应拆成明确 stage，且每个 stage 都能重试、观测、独立扩展 | 不照搬整套 Airflow/Kubernetes 复杂度 |
| Kaapana | 派生 metadata 怎么和原始链路协同 | `advanced_collect_metadata/.../dag_advanced_collect_metadata.py` | 主链路与 SEG 分支并行，最后通过 merge operator 汇总；说明“原始影像 metadata”和“派生对象 metadata”需要分支处理再合并 | 我们应预留原始 asset 与 derived asset 的不同处理支路，尤其是 SEG / RTSTRUCT / SR | 不在 v1 就复制完整 advanced pipeline |
| OHIF | 下游 viewer 对 ingestion 有什么硬要求 | `platform/app/.../defaultRouteInit.ts`、`extensions/cornerstone/.../SegmentationService.ts` | viewer 通过 `series.metadata()` 拉取 series metadata；SEG 加载时必须能定位 `referencedDisplaySetInstanceUID` 和 referenced instances，否则直接报错 | ingestion 必须保存足够的 series / instance metadata 与引用关系，否则后续 viewer 无法可靠消费 SEG / RTSTRUCT / SR | 不把 viewer 需求延后到最后再补 |
| Posda | 导入后治理里最值得借什么 | `PosdaCuration/.../DuplicateSopResolution.pm`、`queries/sql/*Duplicate*`、`import_files.pl` | 大量围绕重复 SOP、重复 pixel digest、import event、导入后可见性和策展的能力 | 我们应把“成功导入”与“质量合格”分开建模，至少预留 duplicate / QC / curation 状态 | 不把 Posda 的脚本化工具链当成 ingestion 主架构 |

## 3. 第一轮结论

1. **Dicoogle 真正值得借的是“异步、可报告、可批量重建的 index task 模型”**，不是一句“它有索引”。
2. **XNAT 真正值得借的是两层东西**：header-only 读取的底层习惯，以及业务对象映射与导入流程解耦。
3. **dcm4che 真正值得借的是 private tag 的工程分层**，这比“支持 private tag”更有价值。
4. **Kaapana 真正值得借的是 stage 化 workflow**，以及原始影像和派生对象走不同分支再汇总的思想。
5. **OHIF 不是 ingestion 项目，但它证明了哪些 metadata / reference 如果 ingestion 阶段不存，后面一定补课。**
6. **Posda 更像后处理和治理参考，不是主链路参考。**

## 4. 还没完成的源码研究

- Dicoogle 的具体 scanner / storage provider 路径还需继续下钻；
- XNAT 的 DICOM 到 Session / Scan 实际 mapping 链路还需继续追；
- Posda 的 duplicate SOP 处理入口要继续读到具体执行流；
- OHIF 需补 RTSTRUCT / SR 的引用需求证据；
- 还未研究 Orthanc，因为当前阶段优先级已被重新排序到“真正服务我们设计的实现证据”。
