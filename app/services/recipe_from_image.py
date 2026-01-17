from typing import Optional
from app.services.recipe_import.service import recipe_import_service as new_service
from app.services.recipe_import.schemas import RecipeImportJob, RecipeImportStartResponse
from app import schemas

class LegacyRecipeFromImageService:
    async def start_job(self, image_bytes: bytes, mime_type: str) -> schemas.RecipeFromImageStartResponse:
        result = await new_service.start_job("image", image_bytes, mime_type=mime_type)
        return schemas.RecipeFromImageStartResponse(job_id=result.job_id)

    async def get_job(self, job_id: str) -> Optional[schemas.RecipeFromImageJob]:
        job = await new_service.get_job(job_id)
        if not job:
            return None
            
        # Convert RecipeImportJob to schemas.RecipeFromImageJob
        result = None
        if job.result:
            ingredients = []
            for ing in job.result.ingredients:
                ingredients.append(schemas.ParsedIngredientFromImage(
                    raw_name=ing.raw_name,
                    quantity=ing.quantity,
                    unit=ing.unit,
                    preparation=ing.preparation,
                    matched_ingredient_id=ing.matched_ingredient_id,
                    matched_ingredient_name=ing.matched_ingredient_name,
                    match_confidence=ing.match_confidence,
                    match_type=ing.match_type,
                    needs_review=ing.needs_review
                ))
                
            result = schemas.ParsedRecipeFromImage(
                name=job.result.name,
                servings=job.result.servings,
                prep_time=job.result.prep_time,
                cook_time=job.result.cook_time,
                instructions=job.result.instructions,
                category=job.result.category,
                ingredients=ingredients,
                nutrition=job.result.nutrition,
                warnings=job.result.warnings
            )
            
        return schemas.RecipeFromImageJob(
            id=job.id,
            status=job.status,
            current_step=job.current_step,
            step_progress=job.step_progress,
            overall_progress=job.overall_progress,
            result=result,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at
        )

    async def cancel_job(self, job_id: str) -> bool:
        return await new_service.cancel_job(job_id)

recipe_from_image_service = LegacyRecipeFromImageService()
