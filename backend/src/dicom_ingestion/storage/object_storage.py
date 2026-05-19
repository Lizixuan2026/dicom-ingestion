"""
Object Storage Backend

MinIO/S3对象存储后端，使用哈希路径避免文件系统限制。
"""
import hashlib
import io
from pathlib import Path
from typing import BinaryIO, Optional, Dict

from .base import StorageBackend, StorageMode, StorageLocation


class ObjectStorageBackend(StorageBackend):
    """
    MinIO/S3对象存储后端
    使用哈希路径避免文件系统限制
    """

    def __init__(
        self,
        minio_client,
        bucket_name: str,
        prefix: str = "dicom",
        secure: bool = True
    ):
        """
        初始化对象存储后端

        Args:
            minio_client: minio.Minio 客户端实例
            bucket_name: 存储桶名称
            prefix: 对象键前缀
            secure: 是否使用HTTPS
        """
        self.client = minio_client
        self.bucket = bucket_name
        self.prefix = prefix
        self.secure = secure

        # 确保bucket存在
        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
        except Exception as e:
            raise StorageError(f"Failed to initialize bucket: {e}")

    def store(
        self,
        source_path: str,
        destination_hint: str,
        metadata: Optional[Dict] = None
    ) -> StorageLocation:
        """
        存储到对象存储
        路径格式: {prefix}/{hash_prefix}/{hash_suffix}/{filename}.dcm
        """
        # 计算文件哈希
        file_hash = self.calculate_checksum(source_path)

        # 生成哈希路径 (前2位作为前缀，避免单个目录过大)
        hash_prefix = file_hash[:2]
        hash_suffix = file_hash[2:]

        # 从hint提取文件名
        filename = Path(destination_hint).name
        if not filename.endswith('.dcm'):
            filename += '.dcm'

        object_key = f"{self.prefix}/{hash_prefix}/{hash_suffix}/{filename}"
        object_key = object_key.strip('/')

        # 准备元数据
        tags = {}
        if metadata:
            # MinIO/S3标签值限制，进行清理
            for key, value in metadata.items():
                if isinstance(value, (str, int, float, bool)):
                    tags[f"x-amz-meta-{key}"] = str(value)[:1024]

        tags['x-amz-meta-content-hash'] = file_hash
        tags['x-amz-meta-original-hint'] = destination_hint[:1024]

        # 上传
        try:
            self.client.fput_object(
                self.bucket,
                object_key,
                source_path,
                metadata=tags
            )
        except Exception as e:
            raise StorageError(f"Failed to store object: {e}")

        # 构建URI
        uri = f"s3://{self.bucket}/{object_key}"

        return StorageLocation(
            mode=StorageMode.OBJECT,
            uri=uri,
            path=object_key,
            bucket=self.bucket,
            metadata=tags,
            checksum=file_hash
        )

    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """从对象存储检索"""
        try:
            response = self.client.get_object(
                location.bucket or self.bucket,
                location.path
            )
            return io.BytesIO(response.read())
        except Exception as e:
            raise StorageError(f"Failed to retrieve object: {e}")

    def delete(self, location: StorageLocation) -> bool:
        """从对象存储删除"""
        try:
            self.client.remove_object(
                location.bucket or self.bucket,
                location.path
            )
            return True
        except Exception as e:
            raise StorageError(f"Failed to delete object: {e}")

    def exists(self, location: StorageLocation) -> bool:
        """检查对象是否存在"""
        try:
            self.client.stat_object(
                location.bucket or self.bucket,
                location.path
            )
            return True
        except Exception:
            return False

    def get_metadata(self, location: StorageLocation) -> Dict:
        """获取对象元数据"""
        try:
            stat = self.client.stat_object(
                location.bucket or self.bucket,
                location.path
            )
            return {
                "size": stat.size,
                "etag": stat.etag,
                "last_modified": stat.last_modified.isoformat() if stat.last_modified else None,
                "metadata": stat.metadata
            }
        except Exception as e:
            raise StorageError(f"Failed to get metadata: {e}")


class StorageError(Exception):
    """存储错误"""
    pass
