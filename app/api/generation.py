from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_settings
from app.db.mongo import GenerationStore, get_generation_store
from app.llm.provider import GeminiProvider, LLMProvider
from app.schemas.generation import GenerationResponse
from app.services.generation import LLMGenerationError, generate_qa_for_selection

router = APIRouter(tags=["generation"])


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model_name=settings.gemini_model,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, LLMGenerationError):
        return HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "attempts": exc.attempts,
                "last_error": exc.last_error,
            },
        )
    raise exc


@router.post(
    "/selections/{selection_id}/generations",
    response_model=GenerationResponse,
    status_code=201,
)
def create_generation(
    selection_id: int,
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    store: GenerationStore = Depends(get_generation_store),
) -> GenerationResponse:
    try:
        payload = generate_qa_for_selection(
            db,
            selection_id=selection_id,
            llm=llm,
            store=store,
        )
    except (LookupError, ValueError, RuntimeError, LLMGenerationError) as exc:
        raise _http_error(exc) from exc
    return GenerationResponse.model_validate(payload)
