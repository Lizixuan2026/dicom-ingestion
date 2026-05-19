"""
Storage Module

双存储模式实现：对象存储（MinIO/S3）+ 本地/NAS存储

决策实施:
- Gap-1: 路径长度限制处理
- 对象存储：哈希路径
- 本地/NAS：层级人可读路径
"""
from .base import StorageBackend, StorageMode, StorageLocation
from .object_storage import ObjectStorageBackend
from .local_nas_storage import LocalNASStorageBackend
from .manager import StorageManager

__all__ = [
    "StorageBackend",
    "StorageMode",
    "StorageLocation",
    "ObjectStorageBackend",
    "LocalNASStorageBackend",
    "StorageManager",
]
