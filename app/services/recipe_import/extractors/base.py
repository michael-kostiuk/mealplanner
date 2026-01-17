from abc import ABC, abstractmethod
from typing import Any
from ..schemas import RecipeImportDraft

class BaseExtractor(ABC):
    @abstractmethod
    async def extract(self, input_data: Any, **kwargs) -> RecipeImportDraft:
        """
        Extract recipe data from the input source.
        
        Args:
            input_data: The input data (e.g., image bytes, URL, text).
            **kwargs: Additional arguments specific to the extractor.
            
        Returns:
            RecipeImportDraft: The extracted recipe data.
        """
        pass
