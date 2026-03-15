from __future__ import annotations

from app.services.database import SQLiteStore


class JobStore(SQLiteStore):
    """Backward-compatible alias for legacy imports."""
