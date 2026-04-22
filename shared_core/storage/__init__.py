"""
분산 데이터 저장소(Storage) 모듈 초기화
"""

from .interfaces import BaseStorageManager
from .sqlite_manager import SqliteStorageManager

__all__ = ["BaseStorageManager", "SqliteStorageManager"]
