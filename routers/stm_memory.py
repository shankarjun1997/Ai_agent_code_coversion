"""Read-only endpoints over the mapping_memory table.

Phase A scope: stats + recent entries for demo/observability. Future phases
will add /search and /retrieve for RAG-driven L3 augmentation.
"""
from __future__ import annotations

from fastapi import APIRouter

from core.stm.persistence import mapping_memory_stats

router = APIRouter(prefix="/api/stm/memory", tags=["stm-memory"])


@router.get("/stats")
async def get_memory_stats() -> dict:
    return await mapping_memory_stats()
