import asyncio
import logging
import os
import time
from typing import Optional, Any

from app.database import SessionLocal
from .schemas import RecipeImportJob, RecipeImportStartResponse
from .job_store import JobStore
from .pipeline import RecipeImportPipeline
from .extractors.image import ImageExtractor

logger = logging.getLogger(__name__)

class RecipeImportService:
    def __init__(self) -> None:
        self._jobs = JobStore()

    async def start_job(self, source_type: str, input_data: Any, **kwargs) -> RecipeImportStartResponse:
        job_id = f"rfi_{int(time.time())}_{os.urandom(6).hex()}"
        await self._jobs.create(job_id)
        
        asyncio.create_task(self._run_job(job_id, source_type, input_data, **kwargs))
        return RecipeImportStartResponse(job_id=job_id)

    async def get_job(self, job_id: str) -> Optional[RecipeImportJob]:
        return await self._jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        return await self._jobs.cancel(job_id)

    async def _run_job(self, job_id: str, source_type: str, input_data: Any, **kwargs) -> None:
        await self._jobs.update(job_id, status="processing", current_step="extracting", step_progress=0, overall_progress=0)
        
        try:
            if await self._jobs.is_canceled(job_id):
                return

            # 1. Extraction
            if source_type == "image":
                extractor = ImageExtractor()
                draft = await extractor.extract(input_data, **kwargs)
            else:
                raise ValueError(f"Unsupported source type: {source_type}")
                
            await self._jobs.update(job_id, current_step="extracting", step_progress=100, overall_progress=40)
            
            if await self._jobs.is_canceled(job_id):
                return

            # 2. Pipeline
            db = SessionLocal()
            try:
                pipeline = RecipeImportPipeline(db)
                
                async def progress_callback(step: str, progress: int):
                    if await self._jobs.is_canceled(job_id):
                        raise asyncio.CancelledError()
                    
                    # Map pipeline steps to overall progress
                    overall_map = {
                        "merging": 45,
                        "matching": 50, # Starts at 50, goes up
                        "verifying": 80,
                        "nutrition": 86,
                        "finalizing": 100
                    }
                    
                    base_progress = overall_map.get(step, 0)
                    overall = base_progress
                    
                    if step == "matching":
                         overall = 50 + int(progress * 0.3) # 50 to 80
                    elif step == "verifying":
                         overall = 80 + int(progress * 0.05) # 80 to 85
                    
                    await self._jobs.update(job_id, current_step=step, step_progress=progress, overall_progress=overall)

                draft = await pipeline.run(draft, progress_callback)
            finally:
                db.close()

            if await self._jobs.is_canceled(job_id):
                return
            
            await self._jobs.update(job_id, current_step="finalizing", step_progress=100, overall_progress=100)
            await self._jobs.update(job_id, status="completed", result=draft)
            
        except asyncio.CancelledError:
             # Already handled cancellation update
             pass
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            await self._jobs.update(job_id, status="failed", error=str(e))

recipe_import_service = RecipeImportService()
