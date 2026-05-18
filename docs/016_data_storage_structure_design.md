# 数据存储结构设计

## 核心诉求：支持两种存储模式

本存储结构设计需要同时支持两种存储后端，根据部署环境灵活选择：

### 模式一：对象存储（Object Storage）
**适用场景**：云端部署、分布式存储、高可用需求

**实现方式**：
- 使用 MinIO（兼容 S3 API 的私有对象存储）
- 文件路径格式：`s3://bucket/{content_hash}` 或类似扁平化结构
- 利用对象存储的原子性和高可用特性
- 适合大规模、高并发的医学影像存储

### 模式二：本地存储 / 公盘存储（Local/NAS Storage）
**适用场景**：本地数据中心、内网环境、成本敏感、需要文件系统直接访问

**实现方式**：
- 使用本地文件系统或网络文件系统（NFS、SMB 等）
- **必须严格按照本文档定义的层级目录结构存储文件**
- 目录结构需包含：设备厂商、StudyUID、SeriesUID 等层级，便于人工浏览和管理
- 文件命名使用 SOPInstanceUID，保证可读性和唯一性
- 支持直接通过文件浏览器查看和定位数据

**两种模式的选择依据**：
| 维度 | 对象存储 | 本地/公盘存储 |
|------|----------|---------------|
| 部署环境 | 公有云/混合云 | 私有云/本地机房 |
| 访问方式 | API/SDK | 文件系统直接访问 |
| 目录结构 | 扁平化（哈希值） | 层级化（本文档结构） |
| 可浏览性 | 需通过界面/工具 | 可直接浏览目录 |
| 扩展性 | 自动扩展 | 需手动扩容 |

---

## 本地/公盘存储的目录结构规范

当使用本地存储或公盘存储时，文件必须按照以下层级结构组织：

—— DICOM_CT/ # DICOM
—— DICOM_MR/
    ├── UIH/
    |    └── 设备名/
    |        └── StudyUID/
    |            └── MeasUID/    # Private tag, 对应一次扫描
    |                    └── SeriesUID/
    |                            └── SOPInstance.dcm      
    └── 友商/
         └── 设备名/
              └── StudyUID/
                    └── SeriesUID/
                          └── SOPInstance.dcm
                                       
—— RAWDATA_CT/ # CT RawData
—— RAWDATA_MR/ # MR RawData
     └── /二级协议/
        └── /MeasUID/
           └── /Version/ 
              └── /Rawdata/
                 └── files

── IMAGE # 图片
    ├── 6dd80768-edb4-4536-a412-de9b9cb4a60a  # 由系统为本次上传生成唯一ID
             └──chunk_0001.parquet  
 
── TEXT  # 文本    
    ├── ac0ac4ba-3ef4-44bc-a88b-e48a0f55d032  
             └──chunk_0001.parquet  
    
── DOCUMENT # 文档
    ├── bf0c1b95-7c3d-4667-b4d2-c07bfe3611d7
    |        └──chunk_0001.pdf
    ├── 32c68d27-89f2-4424-abfc-0a1609451130
    |         ├── data_sample_0/
    |         |        └──*.pdf;   
    |         └── data_sample_1/
    |                  └──*.pdf;   
    ├── 3be4f77d-9d7a-47c8-b511-278848d1fef2
             ├── data_sample_0/
                       └──*.pdf;   

                  
── AUDIO # 音频
    ├── 2d032bd8-8c74-455f-8281-e9e2e67de523
    |         └──*.wav
    ├── 32c68d27-89f2-4424-abfc-0a1609451130
    |         ├── data_sample_0/
    |         |       └──*.wav;   # 对于单模态数据来说，一个文件即是一个data_sample
    |         └── data_sample_1/
    |                 └──*.wav;   # 对于单模态数据来说，一个文件即是一个data_sample
    └── 32c68d27-89f2-4424-abfc-0a1609451130
             └── data_sample_0/
                      └──*.wav;   # 对于单模态数据来说，一个文件即是一个data_sample
                  
── VIDEO # 视频
      └── 15f5069d-0492-4b4a-9e83-aa3b84e0668a
            └──*.mp4
            
── STRUCTURED
      └── e120a59a-fc4d-4d33-821b-872fc6204355
            └──*.csv

# 在多模态情况下
# 不单独建立文件夹，文件夹下的内容分到不同的单模态中

    ├──32c68d27-89f2-4424-abfc-0a1609451130   #  32c68d27-89f2-4424-abfc-0a1609451130：由系统为本次upload生成唯一ID
    |       ├── data_sample_0/
    |       |         ├── DICOM_MR/ # 数据流动到DICOM_MR/ 下
    |       |         └──*.pdf;*.wav;  # *.pdf回流到 DOCUMENT/ 下；*.wav 回流到 AUDIO/ 下
    |       └── data_sample_1/
    |                 ├── DICOM_MR/ # 数据流动到DICOM_MR/ 下
    |                 └──*.pdf;*.wav;  # *.pdf回流到 DOCUMENT/ 下；*.wav 回流到 AUDIO/ 下
    |
    └──3be4f77d-9d7a-47c8-b511-278848d1fef2 # 3be4f77d-9d7a-47c8-b511-278848d1fef2：由系统为本次upload生成唯一ID
           └── data_sample_0/
                    ├── DICOM_CT/  # 数据流动到DICOM_CT/ 下
                    └──*.pdf;*.wav; # *.pdf回流到 DOCUMENT/ 下；*.wav 回流到 AUDIO/ 下


── Annotation/
    ├──DICOM_CT/
    ├──DICOM_MR/
    |    ├── UIH/
    |    |    └── 设备名/
    |    |        └── StudyUID/
    |    |           └── MeasUID/
    |    |                  └── SeriesUID/
    |    |                        ├── 7e44e31b-882d-4955-a187-37d022239ecc/
    |    |                        |         └─ label1/
    |    |                        |              └── *.files
    |    |                        |         └─ label2/
    |    |                        |              └── *.files
    |    |                        └── 808d0724-a772-471a-b15a-a7d364bc3ea8/
    |    |                                 └─ label1/
    |    |                                      └── *.files
    |    └── 友商/
    |        └── 设备名/
    |            └── StudyUID/
    |                   └── SeriesUID/
    |                           ├── 27745e6c-e209-4686-b22a-d03928d5dd0b/
    |                           |         └─ label1/
    |                           |              └── *.files
    |                           |         └─ label2/
    |                           |              └── *.files
    |                           └── fc6a4332-3417-4b11-9d66-9c075e2feda8/
    |                                     └─ label1/
    |                                          └── *.files
    ├──TEXT/
    |     └──e694f72e-fabe-42f1-9256-d064ca527310/   
    |             ├─ label1/
    |             |     └── data_sample_0
    |             |           └── *.files
    |             └─ label2/
    |                   └── data_sample_0
    |                         └── *.files
    ├──DOCUMENT/
    |     └──39a331b7-b978-4f42-9abb-34f4391106ee/
    |             ├─ label1/
    |             |     └── data_sample_0
    |             |           └── *.files
    |             └─ label2/
    |                   └── data_sample_0
    |                         └── *.files
    ├──AUDIO/
    |     └──50d9ac10-2db8-411b-9326-4b0d320f8b4f/
    |             ├─ label1/
    |             |     └── data_sample_0
    |             |           └── *.files
    |             └─ label2/
    |                   └── data_sample_0
    |                         └── *.files
    ├──SIGNAL/
    |     └──9b290e9c-2c10-409a-947f-f1c2a7a45ec6/
    |             ├─ label1/
    |             |     └── data_sample_0
    |             |           └── *.files
    |             └─ label2/
    |                   └── data_sample_0
    |                         └── *.files
    ├──VEDIO/
    |     └──c5f2a2e2-3cc0-44bb-8c24-a6c235516128/
    |             ├─ label1/
    |             |     └── data_sample_0
    |             |           └── *.files
    |             └─ label2/
    |                   └── data_sample_0
    |                         └── *.files
    └──MULTIMODAL/
         └──32c68d27-89f2-4424-abfc-0a1609451130/
                 ├─ label1/
                 |     └── data_sample_0
                 |           └── *.files
                 └─ label2/
                       └── data_sample_0
                             └── *.files
