import json
import sqlite3
import uuid
from typing import Any
from .interfaces import BaseStorageManager

class SqliteStorageManager(BaseStorageManager):
    """
    SQLite를 백엔드로 사용하는 분산 로컬 저장소.
    주로 에이전트 내부에 방대한 LLM 컨텍스트나 검색 결과를 캐싱하기 위해 사용합니다.
    """

    def __init__(self, db_path: str = "agent_local_storage.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute('''
                CREATE TABLE IF NOT EXISTS storage (
                    reference_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()

    async def save_data(self, data: Any, metadata: dict[str, Any] | None = None) -> str:
        reference_id = f"ref_{uuid.uuid4().hex}"
        
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data, ensure_ascii=False)
        else:
            data_str = str(data)

        meta_str = json.dumps(metadata, ensure_ascii=False) if metadata else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO storage (reference_id, data, metadata) VALUES (?, ?, ?)",
                (reference_id, data_str, meta_str)
            )
            conn.commit()
            
        return reference_id

    async def get_data(self, reference_id: str) -> Any | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT data FROM storage WHERE reference_id = ?", (reference_id,))
            row = cursor.fetchone()
            
            if row:
                data_str = row[0]
                try:
                    return json.loads(data_str)
                except json.JSONDecodeError:
                    return data_str
            return None

    async def delete_data(self, reference_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM storage WHERE reference_id = ?", (reference_id,))
            conn.commit()
            return cursor.rowcount > 0
