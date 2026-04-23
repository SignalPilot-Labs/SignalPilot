"""API key management endpoints for local mode."""

from fastapi import APIRouter, HTTPException, Response

from ..models import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse
from .deps import StoreD

router = APIRouter(prefix="/api")


@router.get("/keys")
async def list_keys(store: StoreD) -> list[ApiKeyResponse]:
    records = await store.list_api_keys()
    return [
        ApiKeyResponse(**r.model_dump(exclude={"key_hash"}))
        for r in records
    ]


@router.post("/keys")
async def create_key(body: ApiKeyCreate, store: StoreD) -> ApiKeyCreatedResponse:
    record, raw_key = await store.create_api_key(body.name, body.scopes)
    return ApiKeyCreatedResponse(
        **record.model_dump(exclude={"key_hash"}),
        raw_key=raw_key,
    )


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, store: StoreD):
    if not await store.delete_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return Response(status_code=204)
