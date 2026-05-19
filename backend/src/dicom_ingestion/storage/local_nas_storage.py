"""
Local/NAS Storage Backend

本地/NAS存储后端，支持层级路径，保持人可读。
决策 Gap-1: 路径长度限制处理
"""
import shutil
from pathlib import Path
from typing import BinaryIO, Optional, Dict, Any

from .base import StorageBackend, StorageMode, StorageLocation


class LocalNASStorageBackend(StorageBackend):
    """
    本地/NAS存储后端
    支持层级路径，保持人可读
    """

    def __init__(
        self,
        base_path: str,
        path_generator,  # PathGenerator实例
        create_dirs: bool = True,
        copy_mode: bool = True  # True=复制, False=移动
    ):
        """
        初始化本地/NAS存储后端

        Args:
            base_path: 存储根目录
            path_generator: 路径生成器实例
            create_dirs: 是否自动创建目录
            copy_mode: 是否使用复制模式（False为移动模式）
        """
        self.base_path = Path(base_path)
        self.path_generator = path_generator
        self.copy_mode = copy_mode

        if create_dirs:
            self.base_path.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        source_path: str,
        destination_hint: str,
        metadata: Optional[Dict] = None
    ) -> StorageLocation:
        """
        存储到本地/NAS
        使用层级路径: DICOM_{MODALITY}/{VENDOR}/{DEVICE}/{StudyUID}/{MeasUID}/{SeriesUID}/{SOP}.dcm

        决策 Gap-1: 路径长度限制处理
        """
        source = Path(source_path)

        # 使用path_generator生成层级路径
        relative_path = self.path_generator.generate_path(
            dicom_tags=metadata or {},
            original_filename=source.name
        )

        # 检查路径长度限制 (决策 Gap-1)
        full_path = self._ensure_path_length(self.base_path / relative_path)

        # 确保目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # 检查目标文件是否已存在（避免覆盖）
        if full_path.exists():
            # 计算校验和，检查是否为同一文件
            existing_checksum = self.calculate_checksum(str(full_path))
            new_checksum = self.calculate_checksum(source_path)
            if existing_checksum == new_checksum:
                # 同一文件，直接返回现有位置
                return StorageLocation(
                    mode=StorageMode.LOCAL_NAS,
                    uri=f"file://{full_path.absolute()}",
                    path=str(full_path.relative_to(self.base_path)),
                    bucket=None,
                    metadata={"original_hint": destination_hint, **(metadata or {})},
                    checksum=existing_checksum
                )
            else:
                # 不同文件，添加序号
                full_path = self._get_unique_path(full_path)

        # 复制或移动文件
        if self.copy_mode:
            shutil.copy2(source_path, full_path)
        else:
            shutil.move(source_path, full_path)

        # 计算校验和
        checksum = self.calculate_checksum(str(full_path))

        # 构建URI
        uri = f"file://{full_path.absolute()}"

        return StorageLocation(
            mode=StorageMode.LOCAL_NAS,
            uri=uri,
            path=str(full_path.relative_to(self.base_path)),
            bucket=None,
            metadata={
                "original_hint": destination_hint,
                **(metadata or {})
            },
            checksum=checksum
        )

    def retrieve(self, location: StorageLocation) -> BinaryIO:
        """检索本地文件"""
        full_path = self.base_path / location.path
        if not full_path.exists():
            raise StorageError(f"File not found: {full_path}")
        return open(full_path, 'rb')

    def delete(self, location: StorageLocation) -> bool:
        """删除本地文件"""
        try:
            full_path = self.base_path / location.path
            full_path.unlink()
            return True
        except OSError as e:
            raise StorageError(f"Failed to delete file: {e}")

    def exists(self, location: StorageLocation) -> bool:
        """检查文件是否存在"""
        full_path = self.base_path / location.path
        return full_path.exists()

    def get_metadata(self, location: StorageLocation) -> Dict:
        """获取文件元数据"""
        full_path = self.base_path / location.path
        if not full_path.exists():
            raise StorageError(f"File not found: {full_path}")

        stat = full_path.stat()
        return {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "ctime": stat.st_ctime,
            "mode": stat.st_mode
        }

    def _ensure_path_length(self, path: Path, max_length: int = 4096) -> Path:
        """
        确保路径长度不超过限制
        决策 Gap-1: 路径长度限制处理
        """
        str_path = str(path)
        if len(str_path) <= max_length:
            return path

        # 路径过长，使用哈希缩短
        # 保留基础层级，对最深层使用哈希
        parts = path.parts
        if len(parts) > 4:
            # 对最后几个部分使用哈希
            to_hash = '/'.join(parts[-3:])
            hash_suffix = self._hash_string(to_hash)[:16]
            new_parts = parts[:-3] + (f"HASH_{hash_suffix}",)
            new_path = Path(*new_parts)

            # 递归检查
            if len(str(new_path)) > max_length:
                # 仍然过长，进一步缩短
                return self._ensure_path_length(new_path, max_length)
            return new_path

        # 无法进一步缩短
        return path

    def _get_unique_path(self, path: Path) -> Path:
        """获取唯一路径（添加序号）"""
        if not path.exists():
            return path

        parent = path.parent
        stem = path.stem
        suffix = path.suffix

        counter = 1
        while True:
            new_path = parent / f"{stem}_{counter:03d}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1
            if counter > 999:
                raise StorageError(f"Cannot find unique path for: {path}")

    def _hash_string(self, s: str) -> str:
        """计算字符串哈希"""
        import hashlib
        return hashlib.sha256(s.encode()).hexdigest()


class StorageError(Exception):
    """存储错误"""
    pass
