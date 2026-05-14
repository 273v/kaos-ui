"""GET /v1/models — the model picker catalog.

Static, curated subset of `kaos_llm_client.cost.MODEL_PRICING`. See
`app.services.catalog` for the registry-guard logic.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.models import ModelListResponse
from app.services.catalog import build_catalog

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelListResponse)
async def list_models() -> ModelListResponse:
    return ModelListResponse(models=build_catalog())
