import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from .schemas import RecipeImportJob, RecipeImportDraft

logger = logging.getLogger(__name__)

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

class JobStore:
    def __init__(self) -> None:
        self._jobs: Dict[str, RecipeImportJob] = {}
        self._cancel: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval_s = 300

    def _ensure_cleanup_task(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval_s)
                async with self._lock:
                    self._cleanup_locked()
        except asyncio.CancelledError:
            return

    async def create(self, job_id: str) -> RecipeImportJob:
        self._ensure_cleanup_task()
        async with self._lock:
            now = _utcnow()
            job = RecipeImportJob(
                id=job_id,
                status="queued",
                current_step="",
                step_progress=0,
                overall_progress=0,
                result=None,
                error=None,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = job
            self._cancel[job_id] = asyncio.Event()
            return job

    async def get(self, job_id: str) -> Optional[RecipeImportJob]:
        self._ensure_cleanup_task()
        async with self._lock:
            return self._jobs.get(job_id)

    async def update(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        current_step: Optional[str] = None,
        step_progress: Optional[int] = None,
        overall_progress: Optional[int] = None,
        result: Optional[RecipeImportDraft] = None,
        error: Optional[str] = None,
    ) -> None:
        self._ensure_cleanup_task()
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            data = job.model_dump()
            if status is not None:
                data["status"] = status
            if current_step is not None:
                data["current_step"] = current_step
            if step_progress is not None:
                data["step_progress"] = max(0, min(100, int(step_progress)))
            if overall_progress is not None:
                data["overall_progress"] = max(0, min(100, int(overall_progress)))
            if result is not None:
                data["result"] = result
            if error is not None:
                data["error"] = error
            data["updated_at"] = _utcnow()
            self._jobs[job_id] = RecipeImportJob(**data)

    async def cancel(self, job_id: str) -> bool:
        self._ensure_cleanup_task()
        async with self._lock:
            evt = self._cancel.get(job_id)
            if not evt:
                return False
            evt.set()
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in ("completed", "failed", "canceled"):
                return True
            data = job.model_dump()
            data["status"] = "canceled"
            data["updated_at"] = _utcnow()
            self._jobs[job_id] = RecipeImportJob(**data)
            return True

    async def is_canceled(self, job_id: str) -> bool:
        self._ensure_cleanup_task()
        async with self._lock:
            evt = self._cancel.get(job_id)
            return bool(evt and evt.is_set())

    def _cleanup_locked(self) -> None:
        cutoff = _utcnow().timestamp() - 3600
        to_delete = [jid for jid, job in self._jobs.items() if job.created_at.timestamp() < cutoff]
        for jid in to_delete:
            self._jobs.pop(jid, None)
            self._cancel.pop(jid, None)
