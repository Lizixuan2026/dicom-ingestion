# DICOM Ingestion Module Research Brief

## 1. 任务目标

本文档用于指导 AI 阅读和分析开源项目源码，提炼其中与 **DICOM 文件接入、扫描、解析、元数据抽取、索引、存储组织和工程化处理** 相关的实现，最终为我们的医学影像数据管理平台设计一套可落地、可扩展、生产级的 **DICOM ingestion module**。

一句话定义本次任务：

> 通过分析 Dicoogle、XNAT、Kaapana、dcm4che、Posda、OHIF 生态等开源项目的相关实现，借鉴其中可复用的代码与设计，最终形成我们自己的、非 PACS 的 DICOM 数据接入模块方案。

---

## 2. 非目标说明：本模块不是 PACS

本次工作的目标不是建设 PACS，也不是直接部署一个 PACS 系统替代平台的数据接入能力。

我们关注的是数据管理平台中的 DICOM 数据接入模块，重点包括：

- 支持用户上传 DICOM 文件、文件夹、ZIP；
- 递归扫描和识别 DICOM 文件；
- 解析 DICOM header；
- 抽取标准 tag 和 private tag；
- 建立 Study / Series / Instance 元数据关系；
- 根据平台规则存储原始文件；
- 将 metadata 写入平台数据库和搜索索引；
- 将 DICOM 数据映射到 Asset / Dataset Sample / Annotation 等平台对象；
- 支持多人并发上传、异步解析、失败重试和任务状态管理。

因此，即使某些参考项目本身是 PACS 或类 PACS 系统，我们也只借鉴其中与 **DICOM ingestion、metadata parsing、indexing、storage layout、workflow、quality control** 相关的代码和设计，不把 PACS 作为我们的目标形态。

### 2.1 本次研究要避免的误区

- 不要把“谁最像完整影像系统”当作主要比较维度；
- 不要把“部署 Orthanc / dcm4chee / Dicoogle”当作默认答案；
- 不要把 DICOM ingestion 简化成“找一个 parser 读几个 tag”；
- 不要让 PACS 的 Patient / Study / Series 业务模型直接替代平台自己的 Asset / Dataset / Annotation 模型。

---

## 3. 平台背景与目标能力

我们正在建设的是一套面向 AI 数据治理和医学影像管理的数据平台。DICOM 只是平台支持的数据类型之一，但它需要具备完整、生产级的接入能力。

### 3.1 目标链路

```text
用户上传 DICOM 文件 / 文件夹 / ZIP
        ↓
平台接收上传
        ↓
临时持久化
        ↓
解压 / 遍历 / 识别 DICOM
        ↓
读取 DICOM header
        ↓
抽取 metadata
        ↓
建立 Study / Series / Instance 元数据关系
        ↓
按平台规则存储原始文件
        ↓
写入平台数据库 / 搜索索引
        ↓
映射到 Asset / Dataset Sample / Annotation
```

### 3.2 平台必须支持的能力

1. 单个 DICOM 文件上传；
2. 多文件批量上传；
3. 文件夹上传；
4. ZIP 上传；
5. 自动解压、递归遍历、DICOM 识别；
6. DICOM header 解析与 metadata 抽取；
7. Study / Series / Instance 元数据关系构建；
8. 标准 tag 与 private tag 支持；
9. metadata 入库、检索、索引；
10. 原始文件按平台规则存储；
11. Asset / Dataset Sample / Annotation 映射；
12. 多用户并发、异步任务、失败恢复、任务日志；
13. 后续支持 viewer、annotation、AI pipeline、dataset builder、版本管理。

---

## 4. 研究方法：按“可借鉴代码模块”分析项目

本次研究不按“哪个项目最好用”来组织，而按“哪个项目在哪个模块上值得借鉴”来分析。

### 4.1 重点研究模块

```text
文件扫描
DICOM 文件识别
metadata 抽取
tag 解析
private tag 处理
Study / Series / Instance 聚合
索引构建
批量导入
错误处理
异步任务
存储布局
业务对象映射
去标识与质控
前端 metadata 消费
```

### 4.2 对每个项目都要回答的问题

```text
项目名称：
它在什么问题上最值得研究：
哪些代码或机制可直接借鉴：
哪些设计只能参考，不能照搬：
哪些能力不适合我们的平台：
它启发我们自研哪些模块：
推荐优先级：
```

---

## 5. 候选开源项目与研究重点

### 5.1 Dicoogle

**研究定位：** metadata indexing 与 tag 处理参考。

**重点看什么：**

- 文件夹扫描；
- DICOM 文件识别；
- header / tag 解析；
- private tag 处理；
- indexer 插件机制；
- Study / Series / Instance 聚合；
- 批量导入、后台索引、错误处理。

**我们关心的不是：** 把 Dicoogle 当 PACS 部署。

**我们真正想借鉴的是：**

- 全量 metadata 抽取；
- 长尾 tag 与 private tag 的处理；
- 索引器扩展机制；
- metadata-first 的检索思路。

### 5.2 XNAT

**研究定位：** DICOM 到平台业务对象的映射参考。

**重点看什么：**

- 上传与导入流程；
- DICOM metadata 到 Project / Subject / Session / Scan 的映射；
- 自定义 DICOM 字段映射；
- DICOMSessionBuilder；
- archive / prearchive 流程；
- 导入后的业务对象组织。

**我们真正想借鉴的是：**

- 如何把 DICOM metadata 转换成平台业务模型；
- 如何让导入流程和业务对象生成解耦；
- 如何保留自定义字段扩展能力。

### 5.3 Kaapana

**研究定位：** 任务化 ingestion workflow 与平台级编排参考。

**重点看什么：**

- metadata extraction；
- ingestion workflow；
- OpenSearch 索引；
- Airflow pipeline；
- 与 AI workflow、dataset curation 的衔接。

**我们真正想借鉴的是：**

- ingestion 不应是同步脚本，而应是平台任务流；
- metadata search、处理 pipeline、原始数据管理应解耦。

### 5.4 dcm4che / dcm4chee

**研究定位：** 底层 DICOM 解析、UID 处理与标准实现参考。

**重点看什么：**

- header 解析；
- tag 结构；
- UID 管理；
- Study / Series / Instance 层级；
- DICOMweb；
- 批量接收与归档中的一致性处理。

**我们真正想借鉴的是：**

- 标准级 DICOM 处理能力；
- UID 唯一性和实例管理经验；
- 不重写底层标准轮子的原则。

### 5.5 Posda / NBIA

**研究定位：** 质量控制、去标识、UID / reference 一致性检查参考。

**重点看什么：**

- DICOM 导入后的校验；
- 去标识；
- UID 冲突；
- 引用关系一致性；
- 数据策展与发布前检查。

**我们真正想借鉴的是：**

- ingestion 之后还需要质量控制链路；
- 原始数据、派生数据、标注数据之间要保留可验证关系。

### 5.6 OHIF / Cornerstone / dcmjs

**研究定位：** 前端 metadata 消费与 viewer 需求反推参考。

**重点看什么：**

- 浏览器侧如何读取 metadata；
- DICOMweb 消费方式；
- DICOM-SEG / RTSTRUCT / SR 展示要求；
- viewer 需要 ingestion 阶段提前准备哪些 metadata 和引用关系。

**我们真正想借鉴的是：**

- ingestion 不是终点，后续 viewer 和 annotation 能力会倒逼 metadata 设计。

---

## 6. 需要回答的核心研究问题

### 6.1 接入与文件处理

1. 如何支持文件、文件夹、ZIP 三类入口；
2. 如何递归扫描目录；
3. 如何识别 DICOM 与非 DICOM；
4. 如何处理 ZIP 解压失败、ZIP bomb、重复文件；
5. 如何保留原始上传包与失败文件。

### 6.2 解析与 metadata

1. 如何只读 header，避免不必要的 pixel data 读取；
2. 如何抽取标准 tag；
3. 如何保存 private tag；
4. 如何做 private tag 白名单与映射；
5. 如何保留原始 tag map；
6. 如何支持后续重解析与重建索引。

### 6.3 层级与业务映射

1. 如何建立 Study / Series / Instance；
2. 如何按 UID 去重；
3. 如何处理增量导入和不完整 Series；
4. 如何保存 DICOM-SEG / RTSTRUCT / SR 引用关系；
5. 如何将 DICOM 层级映射到 Asset / Dataset Sample / Annotation。

### 6.4 存储与索引

1. 文件系统与对象存储如何统一抽象；
2. 原始文件路径如何设计；
3. metadata 与物理位置如何解耦；
4. 哪些字段进 PostgreSQL 正规列；
5. 哪些字段进搜索索引；
6. 长尾 tag 如何保存。

### 6.5 并发与工程化

1. 如何做 ingestion job；
2. 如何设计任务状态；
3. 如何支持批量解析、批量写库、批量索引；
4. 如何失败重试与 partial failed；
5. 如何做多用户并发、资源限制、任务日志、可观测性。

---

## 7. 推荐输出格式

最终输出至少应包含：

### 7.1 项目对比表

| 项目 | 最值得借鉴的代码模块 | 不能照搬的部分 | 对我们最有价值的启发 |
| --- | --- | --- | --- |
| Dicoogle | tag 解析、private tag、indexer | PACS 形态 | metadata-first 索引 |
| XNAT | 业务对象映射、导入流程 | XNAT 专属模型 | DICOM 到平台对象转换 |
| Kaapana | workflow、metadata search | 整体平台复杂度 | ingestion 任务化 |
| dcm4che | header 解析、UID 处理 | Java 生态与归档形态 | 复用成熟标准能力 |
| Posda | 去标识、质控、一致性检查 | 偏策展场景 | 把 QC 纳入链路 |
| OHIF 生态 | metadata 消费、SEG/RTSTRUCT/SR | 不是 ingestion 系统 | 反推字段与引用关系 |

### 7.2 模块级借鉴结论

| 模块 | 推荐参考项目 | 说明 |
| --- | --- | --- |
| 文件扫描 | Dicoogle | 递归扫描、DICOM 识别 |
| ZIP / 上传流程 | XNAT + 自研 | 平台任务化处理 |
| metadata 解析 | Dicoogle / dcm4che | header、tag、private tag |
| 业务映射 | XNAT | DICOM 到平台对象 |
| workflow | Kaapana | 异步任务与 pipeline |
| QC | Posda / NBIA | 去标识与一致性 |
| viewer 对接 | OHIF 生态 | metadata 消费要求 |

### 7.3 我们平台的推荐方案

```text
上传服务
  ↓
临时持久化存储
  ↓
Ingestion Job
  ↓
解压 / 扫描 / DICOM 识别
  ↓
Header Parser
  ↓
Metadata Normalizer
  ↓
Study / Series / Instance Builder
  ↓
平台数据库 + 搜索索引
  ↓
对象存储 / 共享盘
  ↓
Asset / Dataset Sample / Annotation
```

### 7.4 直接复用 / 借鉴 / 自研判断

必须明确回答：

- 哪些底层能力可直接复用；
- 哪些工程设计适合借鉴；
- 哪些平台能力必须自研；
- 哪些项目虽有价值，但不应进入目标架构。

---

## 8. 最终判断标准

最终报告不应回答：

> 哪个 PACS 最适合我们？

而应回答：

1. 哪些开源项目在 ingestion 链路的哪些环节上最值得借鉴；
2. 哪些代码实现可以直接复用；
3. 哪些设计只能参考不能照搬；
4. 我们的平台最终应该如何实现自己的 DICOM ingestion module；
5. 如何保证该模块服务于 Asset / Dataset / Annotation，而不是反过来被 PACS 模型牵着走。
