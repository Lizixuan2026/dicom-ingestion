"""
Storage Manager

统一存储管理器，协调双存储模式。
"""
from typing import Dict, Optional
import logging

from .base import StorageBackend, StorageLocation, StorageMode

logger = logging.getLogger(__name__)


class StorageManager:
    """
    统一存储管理器
    协调双存储模式
    """

    def __init__(
        self,
        object_backend: Optional[StorageBackend] = None,
        local_backend: Optional[StorageBackend] = None,
        dual_write: bool = False  # 是否双写
    ):
        """
        初始化存储管理器

        Args:
            object_backend: 对象存储后端
            local_backend: 本地/NAS存储后端
            dual_write: 是否同时写入两种存储
        """
        self.object_backend = object_backend
        self.local_backend = local_backend
        self.dual_write = dual_write

    def store_for_processing(
        self,
        file_path: str,
        metadata: Dict
    ) -> StorageLocation:
        """
        存储到处理存储（对象存储）
        系统内部使用，优化处理速度
        """
        if not self.object_backend:
            raise StorageManagerError("Object storage not configured")

        return self.object_backend.store(
            file_path,
            metadata.get('suggested_path', ''),
            metadata
        )

    def store_for_archive(
        self,
        file_path: str,
        metadata: Dict
    ) -> StorageLocation:
        """
        存储到归档存储（本地/NAS）
        人可读路径，便于直接访问
        """
        if not self.local_backend:
            raise StorageManagerError("Local/NAS storage not configured")

        return self.local_backend.store(
            file_path,
            metadata.get('suggested_path', ''),
            metadata
        )

    def dual_store(
        self,
        file_path: str,
        metadata: Dict
    ) -> Dict[str, StorageLocation]:
        """
        双模式存储
        同时存储到对象存储和本地/NAS
        返回两个Location
        """
        results = {}

        if self.object_backend:
            try:
                results['object'] = self.store_for_processing(file_path, metadata)
                logger.info(f"Stored to object storage: {results['object'].uri}")
            except Exception as e:
                logger.error(f"Object storage failed: {e}")
                raise

        if self.local_backend:
            try:
                results['local'] = self.store_for_archive(file_path, metadata)
                logger.info(f"Stored to local/NAS: {results['local'].uri}")
            except Exception as e:
                logger.error(f"Local/NAS storage failed: {e}")
                # 如果对象存储成功，尝试回滚
                if 'object' in results:
                    try:
                        self.object_backend.delete(results['object'])
                        logger.info("Rolled back object storage")
                    except Exception as rollback_error:
                        logger.error(f"Rollback failed: {rollback_error}")
                raise

        return results

    def retrieve(self, location: StorageLocation) -> any:
        """根据Location类型自动选择后端检索"""
        if location.mode == StorageMode.OBJECT and self.object_backend:
            return self.object_backend.retrieve(location)
        elif location.mode == StorageMode.LOCAL_NAS and self.local_backend:
            return self.local_backend.retrieve(location)
        else:
            raise StorageManagerError(f"Unsupported storage mode: {location.mode}")

    def delete(self, location: StorageLocation) -> bool:
        """根据Location类型删除"""
        if location.mode == StorageMode.OBJECT and self.object_backend:
            return self.object_backend.delete(location)
        elif location.mode == StorageMode.LOCAL_NAS and self.local_backend:
            return self.local_backend.delete(location)
        return False

    def exists(self, location: StorageLocation) -> bool:
        """检查文件是否存在"""
        if location.mode == StorageMode.OBJECT and self.object_backend:
            return self.object_backend.exists(location)
        elif location.mode == StorageMode.LOCAL_NAS and self.local_backend:
            return self.local_backend.exists(location)
        return False

    def get_storage_stats(self) -> Dict:
        """获取存储统计"""
        stats = {
            "object_storage": self.object_backend is not None,
            "local_nas_storage": self.local_backend is not None,
            "dual_write": self.dual_write
        }
        return stats


class StorageManagerError(Exception):
    """存储管理器错误"""
    pass
