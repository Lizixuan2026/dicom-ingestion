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

    P1-1: 可配置路径长度阈值，默认保守设置 (240-255)
    """

    # P1-1: 默认保守路径长度限制（Windows/NAS 兼容）
    DEFAULT_MAX_PATH_LENGTH = 240

    def __init__(
        self,
        base_path: str,
        path_generator,  # PathGenerator实例
        create_dirs: bool = True,
        copy_mode: bool = True,  # True=复制, False=移动
        max_path_length: Optional[int] = None
    ):
        """
        初始化本地/NAS存储后端

        Args:
            base_path: 存储根目录
            path_generator: 路径生成器实例
            create_dirs: 是否自动创建目录
            copy_mode: 是否使用复制模式（False为移动模式）
            max_path_length: 路径长度限制（默认240，建议240-255）
        """
        self.base_path = Path(base_path)
        self.path_generator = path_generator
        self.copy_mode = copy_mode
        # P1-1: 可配置阈值
        self.max_path_length = max_path_length or self.DEFAULT_MAX_PATH_LENGTH

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

        P1-1: 路径长度控制 - Generator 负责组件级，Storage 负责完整路径级
        """
        source = Path(source_path)

        # Step 1: Generator 生成层级路径（组件级长度控制）
        relative_path = self.path_generator.generate_path(
            dicom_tags=metadata or {},
            original_filename=source.name
        )

        # Step 2: Storage 确保完整路径长度（完整路径级控制）
        # P1-1: 可配置阈值，默认240字符（Windows/NAS 兼容）
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

    def _ensure_path_length(self, path: Path) -> Path:
        """
        确保路径长度不超过限制

        P1-1: 迭代式路径缩短策略（替代递归，更稳定可控）
        策略优先级：
        1. 缩短 UID 组件（保留前8+后8字符）
        2. 缩短设备名（使用哈希后缀）
        3. 缩短 vendor（使用缩写）
        4. 最终回退：完整哈希目录
        """
        str_path = str(path)
        if len(str_path) <= self.max_path_length:
            return path

        # P1-1: 分离 base 和相对路径，只缩短相对部分
        try:
            relative = path.relative_to(self.base_path)
            base_parts = []
            relative_parts = list(relative.parts)
        except ValueError:
            # path 不在 base_path 下，整体缩短
            base_parts = []
            relative_parts = list(path.parts)

        original_len = len(str_path)

        # P1-1: 迭代式缩短 - 按优先级逐步缩短（只对相对部分）
        shortening_steps = [
            self._shorten_uids_in_parts,
            self._shorten_device_in_parts,
            self._shorten_vendor_in_parts,
            self._fallback_to_hash_structure,
        ]

        for step_func in shortening_steps:
            relative_parts = step_func(relative_parts)
            new_relative = Path(*relative_parts)
            new_path = self.base_path / new_relative
            if len(str(new_path)) <= self.max_path_length:
                return new_path

        # 如果仍然过长，最终回退（保持相对路径结构）
        return self.base_path / self._ultimate_fallback(relative_parts, original_len)

    def _shorten_uids_in_parts(self, parts: list) -> list:
        """缩短 UID 组件：保留前缀和后缀，中间用哈希替代"""
        if len(parts) < 4:
            return parts

        # P1-1: 检查所有部分（跳过第一层的 DICOM_{modality}）
        for i in range(1, len(parts)):
            part = parts[i]
            # 检测 UID 模式（包含点的长字符串，且部分数量>=4）
            if '.' in part and len(part) > 20:
                uid_parts = part.split('.')
                if len(uid_parts) >= 4:
                    # 保留前2段和后2段，中间用短哈希（使用 _H_ 避免 .. 被误解为路径遍历）
                    middle_hash = self._hash_string(part)[:8]
                    shortened = f"{'.'.join(uid_parts[:2])}_H_{middle_hash}_H_{'.'.join(uid_parts[-2:])}"
                    parts[i] = shortened[:48]  # 限制长度

        return parts

    def _shorten_device_in_parts(self, parts: list) -> list:
        """缩短设备名组件"""
        if len(parts) < 3:
            return parts

        # 设备名通常在 vendor 后面
        for i, part in enumerate(parts):
            if len(part) > 32 and i > 0 and i < len(parts) - 2:
                # 对长设备名使用哈希后缀
                hash_suffix = self._hash_string(part)[:8]
                parts[i] = f"DEV_{hash_suffix}"
                break

        return parts

    def _shorten_vendor_in_parts(self, parts: list) -> list:
        """缩短 vendor 名称（使用标准缩写）"""
        VENDOR_ABBREV = {
            'SIEMENS': 'SIEM',
            'GE': 'GE',
            'PHILIPS': 'PHIL',
            'UIH': 'UIH',
            'CANON': 'CAN',
            'HITACHI': 'HIT',
            'AGFA': 'AGF',
            'CARESTREAM': 'CS',
            'FUJIFILM': 'FUJI',
            'GENERIC': 'GEN',
        }

        for i, part in enumerate(parts):
            upper_part = part.upper()
            for full, abbrev in VENDOR_ABBREV.items():
                if full in upper_part:
                    parts[i] = abbrev
                    break

        return parts

    def _fallback_to_hash_structure(self, parts: list) -> list:
        """回退到哈希结构：保留顶层，下层用哈希"""
        if len(parts) < 4:
            return parts

        # 保留前2层，其余用哈希表示
        to_hash = '/'.join(parts[2:])
        hash_value = self._hash_string(to_hash)[:16]

        return parts[:2] + [f"CONT_{hash_value}"]

    def _ultimate_fallback(self, parts: list, original_len: int) -> Path:
        """最终回退：完整路径哈希（可读性最低但保证有效）"""
        full_hash = self._hash_string('/'.join(parts))[:24]
        # P1-1: 版本化命名 - 包含原始长度信息
        # 保持层级结构：将所有内容放入一个哈希目录
        return Path("OVERFLOW") / f"{original_len}_{full_hash}"

    def _get_unique_path(self, path: Path) -> Path:
        """
        获取唯一路径（版本化命名规则）

        P1-1: 版本化命名格式: {stem}_v{counter}{suffix}
        与原文件区分：同名但不同内容的文件使用 v1, v2, v3... 后缀
        """
        if not path.exists():
            return path

        parent = path.parent
        stem = path.stem
        suffix = path.suffix

        # P1-1: 版本化命名 - v1, v2, v3...
        for version in range(1, 10000):
            # 格式: filename_v001.dcm
            new_path = parent / f"{stem}_v{version:03d}{suffix}"
            if not new_path.exists():
                return new_path

        raise StorageError(f"Cannot find unique path for: {path} (exhausted v1-9999)")

    def get_versioned_path(self, location: StorageLocation, version: int) -> Path:
        """
        获取指定版本的路径（用于访问历史版本）

        P1-1: 支持版本化文件访问
        """
        base_path = self.base_path / location.path
        if version == 0:
            return base_path

        stem = base_path.stem
        suffix = base_path.suffix
        return base_path.parent / f"{stem}_v{version:03d}{suffix}"

    def _hash_string(self, s: str) -> str:
        """计算字符串哈希"""
        import hashlib
        return hashlib.sha256(s.encode()).hexdigest()


class StorageError(Exception):
    """存储错误"""
    pass
