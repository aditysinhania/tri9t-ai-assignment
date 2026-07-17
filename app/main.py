from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.browse import router as browse_router
from app.api.generation import router as generation_router
from app.api.selections import router as selections_router
from app.core.config import get_settings
from app.core.database import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(browse_router)
app.include_router(selections_router)
app.include_router(generation_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
