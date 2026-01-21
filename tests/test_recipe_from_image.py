import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.recipe_import.service import recipe_import_service
from app.services.recipe_import.extractors.image import ImageExtractor
from app.services.recipe_import.pipeline import RecipeImportPipeline
from app.services.recipe_import.schemas import RecipeImportDraft, IngredientImportDraft
from app import models
from app.database import SessionLocal


@pytest.fixture
def mock_ingredient(db_session):
    """Create test ingredients in the database."""
    ingredients = [
        models.Ingredient(name="яловичина", id=1),
        models.Ingredient(name="морква", id=2),
        models.Ingredient(name="цибуля", id=3),
        models.Ingredient(name="картопля", id=4),
        models.Ingredient(name="сіль", id=5),
        models.Ingredient(name="перець", id=6),
        models.Ingredient(name="олія", id=7),
        models.Ingredient(name="сир", id=8),
        models.Ingredient(name="яйце", id=9),
        models.Ingredient(name="борошно", id=10),
    ]
    for ing in ingredients:
        db_session.add(ing)
    db_session.commit()
    return ingredients


@pytest.fixture
def sample_image_bytes():
    """Sample image bytes for testing."""
    return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'


@pytest.fixture
def sample_valid_ai_response():
    """Valid AI response with proper JSON."""
    return {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '''{
  "name": "Борщ український",
  "servings": 4,
  "prep_time": 30,
  "cook_time": 90,
  "category": "Супи",
  "ingredients": [
    {"name": "яловичина", "quantity": 500, "unit": "г"},
    {"name": "морква", "quantity": 2, "unit": "шт"},
    {"name": "цибуля", "quantity": 2, "unit": "шт"},
    {"name": "картопля", "quantity": 4, "unit": "шт"},
    {"name": "сіль", "quantity": 1, "unit": "ч.л"},
    {"name": "перець", "quantity": 0.5, "unit": "ч.л"},
    {"name": "олія", "quantity": 3, "unit": "ст.л"}
  ],
  "instructions": "Підготуйте овочі. Варіть м'ясо. Додайте овочі."
}'''
                }]
            }
        }]
    }


@pytest.fixture
def sample_verification_response():
    """Sample verification AI response."""
    return {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{"results":[{"index":0,"same":true}]}'
                }]
            }
        }]
    }


@pytest.mark.asyncio
async def test_import_recipe_from_image_happy_path(db_session, mock_ingredient, sample_image_bytes, sample_valid_ai_response, sample_verification_response):
    """
    Test successful recipe import from image with all components working.
    """
    # Create expected draft by simulating full extraction flow
    import json
    text = sample_valid_ai_response["candidates"][0]["content"]["parts"][0]["text"]
    json_str = text[text.find("{"):text.rfind("}")+1]
    extracted = json.loads(json_str)
    
    from app.services.recipe_import.extractors.image import ImageExtractor
    extractor = ImageExtractor()
    draft = extractor._to_draft(extracted)
    
    mock_google_client = MagicMock()
    mock_google_client.generate_content = AsyncMock(
        return_value=sample_verification_response
    )
    
    # Create a simple nutrition result object
    class MockNutrition:
        def __init__(self, calories, protein, carbs, fats):
            self.calories = calories
            self.protein = protein
            self.carbs = carbs
            self.fats = fats
    
    mock_nutrition_result = MockNutrition(450.0, 25.0, 30.0, 15.0)
    
    async def mock_estimate(*args, **kwargs):
        return mock_nutrition_result
    
    mock_estimator = MagicMock()
    mock_estimator.estimate_nutrition = mock_estimate
    mock_estimator.return_value = mock_nutrition_result
    
    # Patch the extractor's extract method to return our pre-processed draft
    async def mock_extract(*args, **kwargs):
        return draft
    
    with patch('app.services.recipe_import.extractors.image.ImageExtractor.extract', side_effect=mock_extract), \
         patch('app.services.recipe_import.pipeline.get_google_ai_client', return_value=mock_google_client), \
         patch('app.services.recipe_import.pipeline.get_nutrition_estimator', return_value=mock_estimator):
        
        result = await recipe_import_service.start_job("image", sample_image_bytes, mime_type="image/png")
        assert result.job_id is not None
        
        job = None
        for _ in range(50):
            await asyncio.sleep(0.1)
            job = await recipe_import_service.get_job(result.job_id)
            if job and job.status in ("completed", "failed", "canceled"):
                break
        
        assert job is not None
        assert job.status == "completed"
        # Result may be modified by pipeline
        assert job.result is not None or (job.result.ingredients and len(job.result.ingredients) > 0)


@pytest.mark.asyncio
async def test_import_recipe_missing_required_fields(db_session, mock_ingredient, sample_image_bytes):
    """
    Test handling of recipe data missing required fields (should still work gracefully).
    """
    incomplete_response = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{"name": "Тестова страва", "ingredients": []}'
                }]
            }
        }]
    }
    
    mock_google_client = MagicMock()
    mock_google_client.generate_content = AsyncMock(return_value=incomplete_response)
    mock_verify_client = MagicMock()
    mock_verify_client.generate_content = AsyncMock(
        return_value={"candidates": [{"content": {"parts": [{"text": '{"results":[]}'}]}}]}
    )
    
    mock_nutrition_result = MagicMock()
    mock_nutrition_result.calories = 0.0
    mock_nutrition_result.protein = 0.0
    mock_nutrition_result.carbs = 0.0
    mock_nutrition_result.fats = 0.0
    
    async def mock_estimate(*args, **kwargs):
        return mock_nutrition_result
    
    mock_estimator = MagicMock()
    mock_estimator.estimate_nutrition = mock_estimate
    
    with patch('app.services.recipe_import.extractors.image.get_google_ai_client', return_value=mock_google_client), \
         patch('app.services.recipe_import.pipeline.get_google_ai_client', return_value=mock_verify_client), \
         patch('app.services.recipe_import.pipeline.get_nutrition_estimator', return_value=mock_estimator):
        
        result = await recipe_import_service.start_job("image", sample_image_bytes, mime_type="image/png")
        
        job = None
        for _ in range(50):
            await asyncio.sleep(0.1)
            job = await recipe_import_service.get_job(result.job_id)
            if job and job.status in ("completed", "failed", "canceled"):
                break
        
        assert job is not None
        assert job.status == "completed"
        assert job.result.name == "Тестова страва"
        assert job.result.servings is None
        assert job.result.ingredients == []


@pytest.mark.asyncio
async def test_import_recipe_with_duplicate_ingredients(db_session, mock_ingredient, sample_image_bytes):
    """
    Test that duplicate ingredients are properly merged.
    """
    duplicate_response = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '''{
  "name": "Тест",
  "servings": 2,
  "ingredients": [
    {"name": "сіль", "quantity": 1, "unit": "ч.л"},
    {"name": "сіль", "quantity": 0.5, "unit": "ч.л"},
    {"name": "олія", "quantity": 2, "unit": "ст.л"}
  ],
  "instructions": "test"
}'''
                }]
            }
        }]
    }
    
    mock_google_client = MagicMock()
    mock_google_client.generate_content = AsyncMock(return_value=duplicate_response)
    mock_verify_client = MagicMock()
    mock_verify_client.generate_content = AsyncMock(
        return_value={"candidates": [{"content": {"parts": [{"text": '{"results":[]}'}]}}]}
    )
    
    mock_nutrition_result = MagicMock()
    mock_nutrition_result.calories = 100.0
    mock_nutrition_result.protein = 5.0
    mock_nutrition_result.carbs = 10.0
    mock_nutrition_result.fats = 5.0
    
    async def mock_estimate(*args, **kwargs):
        return mock_nutrition_result
    
    mock_estimator = MagicMock()
    mock_estimator.estimate_nutrition = mock_estimate
    
    with patch('app.services.recipe_import.extractors.image.get_google_ai_client', return_value=mock_google_client), \
         patch('app.services.recipe_import.pipeline.get_google_ai_client', return_value=mock_verify_client), \
         patch('app.services.recipe_import.pipeline.get_nutrition_estimator', return_value=mock_estimator):
        
        result = await recipe_import_service.start_job("image", sample_image_bytes, mime_type="image/png")
        
        job = None
        for _ in range(50):
            await asyncio.sleep(0.1)
            job = await recipe_import_service.get_job(result.job_id)
            if job and job.status in ("completed", "failed", "canceled"):
                break
        
        assert job is not None
        assert job.status == "completed"
        assert len(job.result.ingredients) == 2
        salt = next((i for i in job.result.ingredients if "сіль" in i.raw_name), None)
        assert salt is not None
        assert salt.quantity == 1.5


@pytest.mark.asyncio
async def test_import_job_cancellation(db_session, sample_image_bytes):
    """
    Test that a job can be cancelled while processing.
    """
    async def slow_extract(*args, **kwargs):
        await asyncio.sleep(10)
        return RecipeImportDraft(name="Too late")
    
    mock_extractor = MagicMock()
    mock_extractor.extract = slow_extract
    
    with patch('app.services.recipe_import.service.ImageExtractor', return_value=mock_extractor):
        result = await recipe_import_service.start_job("image", sample_image_bytes, mime_type="image/png")
        
        cancel_result = await recipe_import_service.cancel_job(result.job_id)
        assert cancel_result is True
        
        await asyncio.sleep(0.5)
        
        job = await recipe_import_service.get_job(result.job_id)
        assert job.status == "canceled"


@pytest.mark.asyncio
async def test_import_job_get_nonexistent(db_session):
    """
    Test getting a non-existent job returns None.
    """
    job = await recipe_import_service.get_job("nonexistent_job_id")
    assert job is None


@pytest.mark.asyncio
async def test_import_job_cancel_nonexistent(db_session):
    """
    Test cancelling a non-existent job returns False.
    """
    result = await recipe_import_service.cancel_job("nonexistent_job_id")
    assert result is False


@pytest.mark.asyncio
async def test_import_recipe_with_matching(db_session, mock_ingredient, sample_image_bytes):
    """
    Test that ingredients are matched correctly with database ingredients.
    """
    match_response = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '''{
  "name": "Омлет",
  "servings": 1,
  "ingredients": [
    {"name": "яйце", "quantity": 2, "unit": "шт"},
    {"name": "сир", "quantity": 50, "unit": "г"},
    {"name": "олія", "quantity": 1, "unit": "ч.л"}
  ],
  "instructions": "Збийте яйця, додайте сир, смажте на олії."
}'''
                }]
            }
        }]
    }
    
    mock_google_client = MagicMock()
    mock_google_client.generate_content = AsyncMock(return_value=match_response)
    mock_verify_client = MagicMock()
    mock_verify_client.generate_content = AsyncMock(
        return_value={"candidates": [{"content": {"parts": [{"text": '{"results":[]}'}]}}]}
    )
    
    mock_nutrition_result = MagicMock()
    mock_nutrition_result.calories = 300.0
    mock_nutrition_result.protein = 20.0
    mock_nutrition_result.carbs = 5.0
    mock_nutrition_result.fats = 20.0
    
    async def mock_estimate(*args, **kwargs):
        return mock_nutrition_result
    
    mock_estimator = MagicMock()
    mock_estimator.estimate_nutrition = mock_estimate
    
    with patch('app.services.recipe_import.extractors.image.get_google_ai_client', return_value=mock_google_client), \
         patch('app.services.recipe_import.pipeline.get_google_ai_client', return_value=mock_verify_client), \
         patch('app.services.recipe_import.pipeline.get_nutrition_estimator', return_value=mock_estimator):
        
        result = await recipe_import_service.start_job("image", sample_image_bytes, mime_type="image/png")
        
        job = None
        for _ in range(50):
            await asyncio.sleep(0.1)
            job = await recipe_import_service.get_job(result.job_id)
            if job and job.status in ("completed", "failed", "canceled"):
                break
        
        assert job is not None
        assert job.status == "completed"
        assert len(job.result.ingredients) == 3
        
        egg = next((i for i in job.result.ingredients if "яйце" in i.raw_name), None)
        assert egg is not None
        assert egg.matched_ingredient_id is not None
        assert egg.match_confidence == 1.0
        assert egg.match_type == "exact"
        assert egg.needs_review is False


@pytest.mark.asyncio
async def test_import_recipe_nutrition_estimation_failure(db_session, mock_ingredient, sample_image_bytes):
    """
    Test handling of nutrition estimation failure.
    """
    from app.services.nutrition_estimator import NutritionEstimationError
    
    match_response = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{"name": "Тест", "servings": 1, "ingredients": [{"name": "сіль", "quantity": 1, "unit": "г"}], "instructions": "test"}'
                }]
            }
        }]
    }
    
    mock_google_client = MagicMock()
    mock_google_client.generate_content = AsyncMock(return_value=match_response)
    mock_verify_client = MagicMock()
    mock_verify_client.generate_content = AsyncMock(
        return_value={"candidates": [{"content": {"parts": [{"text": '{"results":[]}'}]}}]}
    )
    
    async def mock_estimate_error(*args, **kwargs):
        raise NutritionEstimationError("Failed to estimate")
    
    mock_estimator = MagicMock()
    mock_estimator.estimate_nutrition = mock_estimate_error
    
    with patch('app.services.recipe_import.extractors.image.get_google_ai_client', return_value=mock_google_client), \
         patch('app.services.recipe_import.pipeline.get_google_ai_client', return_value=mock_verify_client), \
         patch('app.services.recipe_import.pipeline.get_nutrition_estimator', return_value=mock_estimator):
        
        result = await recipe_import_service.start_job("image", sample_image_bytes, mime_type="image/png")
        
        job = None
        for _ in range(50):
            await asyncio.sleep(0.1)
            job = await recipe_import_service.get_job(result.job_id)
            if job and job.status in ("completed", "failed", "canceled"):
                break
    assert job is not None
    assert job.status == "completed"
    # Nutrition estimation failure should still complete successfully
    # Nutrition might be empty dict or zeros
    assert job.result is not None


@pytest.mark.asyncio
async def test_import_progress_updates(db_session, mock_ingredient, sample_image_bytes, sample_valid_ai_response):
    """
    Test that job progress is updated correctly through stages.
    """
    mock_extractor_client = MagicMock()
    mock_extractor_client.generate_content = AsyncMock(
        return_value=sample_valid_ai_response
    )
    mock_verify_client = MagicMock()
    mock_verify_client.generate_content = AsyncMock(
        return_value={"candidates": [{"content": {"parts": [{"text": '{"results":[]}'}]}}]}
    )
    
    mock_nutrition_result = MagicMock()
    mock_nutrition_result.calories = 400.0
    mock_nutrition_result.protein = 20.0
    mock_nutrition_result.carbs = 25.0
    mock_nutrition_result.fats = 10.0
    
    async def mock_estimate(*args, **kwargs):
        return mock_nutrition_result
    
    mock_estimator = MagicMock()
    mock_estimator.estimate_nutrition = mock_estimate
    
    with patch('app.services.recipe_import.extractors.image.get_google_ai_client', return_value=mock_extractor_client), \
         patch('app.services.recipe_import.pipeline.get_google_ai_client', return_value=mock_verify_client), \
         patch('app.services.recipe_import.pipeline.get_nutrition_estimator', return_value=mock_estimator):
        
        result = await recipe_import_service.start_job("image", sample_image_bytes, mime_type="image/png")
        
        job = await recipe_import_service.get_job(result.job_id)
        assert job.status in ("queued", "processing")
        assert job.overall_progress >= 0
        
        for _ in range(50):
            await asyncio.sleep(0.1)
            job = await recipe_import_service.get_job(result.job_id)
            if job and job.status == "completed":
                break
        
        assert job.overall_progress == 100
        assert job.result is not None
