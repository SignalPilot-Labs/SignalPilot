from __future__ import annotations

_BUILD_URL_FIELD_LIMITS: dict[str, int] = {
    "host": 255,
    "database": 128,
    "username": 128,
    "password": 1024,
}
