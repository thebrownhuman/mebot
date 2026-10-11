from fastapi import APIRouter, Depends

from mebot.config import Settings
from mebot.deps import get_settings
from mebot.llm import ollama

router = APIRouter(prefix="/api")


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)):
    return await ollama.health(settings.ollama_host, settings.ollama_model)
