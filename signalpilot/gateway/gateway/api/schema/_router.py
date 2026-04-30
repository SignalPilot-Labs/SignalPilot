"""Shared APIRouter instance for all schema endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api")
