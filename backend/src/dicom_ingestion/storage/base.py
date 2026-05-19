"""
Storage Backend Base

存储后端抽象基类，定义统一接口。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Optional, Dict
from enum import Enum


class StorageMode(Enum):
    """存储模式"""
    OBJECT = "object"      # MinIO/S3
    LOCAL_NAS = "local_nas"  # 本地/NAS


@dataclass
class StorageLocation:
    """存储位置信息"""
    mode: StorageMode
    uri: str                    # 存储URI
    path: str                   # 实际路径/对象键
    bucket: Optional[str]     # 对象存储bucket
    metadata: Dict              # 存储元数据
    checksum: str               # 校验和


class StorageBackend(ABC):
    """存储后端抽象基类"""

    @abstractmethod
    def store(
        self,
        source_path: str,
        destination_hint: str,
        metadata: Optional[Dict] = None
    ) -> StorageLocation:
        """
        存储文件

        Args:
            source_path: 源文件本地路径
            destination_hint: 目标路径提示（可能包含命名建议）
            metadata: 附加元数据

        Returns:
            StorageLocation对象
        """
        pass

    @abstractmethod
    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """检索文件为流"""
        pass

    @abstractmethod
    def delete(self, location: StorageLocation) -> bool:
        """删除文件"""
        pass

    @abstractmethod
    def exists(self, location: StorageLocation) -> bool:
        """检查文件是否存在"""
        pass

    @abstractmethod
    def get_metadata(self, location: StorageLocation) -> Dict:
        """获取存储元数据"""
        pass

    def calculate_checksum(self, file_path: str) -> str:
        """计算文件SHA256校验和"""
        import hashlib

        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
