"""API key management endpoints for local mode."""

from fastapi import APIRouter, HTTPException, Response

from ..models import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse
from ..store import create_api_key, delete_api_key, list_api_keys

router = APIRouter(prefix="/api")


@router.get("/keys")
async def list_keys() -> list[ApiKeyResponse]:
    records = list_api_keys()
    return [
        ApiKeyResponse(**r.model_dump(exclude={"key_hash"}))
        for r in records
    ]


@router.post("/keys")
async def create_key(body: ApiKeyCreate) -> ApiKeyCreatedResponse:
    record, raw_key = create_api_key(body.name, body.scopes)
    return ApiKeyCreatedResponse(
        **record.model_dump(exclude={"key_hash"}),
        raw_key=raw_key,
    )


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str):
    if not delete_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return Response(status_code=204)
