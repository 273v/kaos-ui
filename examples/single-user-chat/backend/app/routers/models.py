"""GET /v1/models — the model picker catalog.

Static, curated subset of `kaos_llm_client.cost.MODEL_PRICING`. See
`app.services.catalog` for the registry-guard logic.

Auth-gated: requires the same bearer as the kaos-agents-native routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.models import ModelListResponse
from app.services.catalog import build_catalog

router = APIRouter(tags=["models"], dependencies=[Depends(require_auth)])


@router.get("/models", response_model=ModelListResponse)
async def list_models() -> ModelListResponse:
    return ModelListResponse(models=build_catalog())
