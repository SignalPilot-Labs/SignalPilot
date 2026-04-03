"""Multi-key pool with rotation, cooldown tracking, and auto-wait.

Manages encrypted API keys across providers (claude_code, codex) with
automatic rotation on rate limit, priority-based selection, and
configurable auto-wait for rate limit recovery.
"""

import asyncio
import os
import time
import uuid
from dataclasses import dataclass

# Import paths for this project
from agent import db


MASTER_KEY_PATH = os.environ.get("MASTER_KEY_PATH", "/data/master.key")

# Default config values seeded on first boot
DEFAULT_CONFIG = {
    "codex_fallback_enabled": "false",
    "auto_wait_enabled": "true",
    "max_wait_minutes": "60",
    "rotation_strategy": "priority_then_cooldown",
    "prefer_model_downgrade_over_codex": "true",
}

VALID_PROVIDERS = ("claude_code", "codex")
VALID_STRATEGIES = ("priority_then_cooldown",)


@dataclass
class ApiKey:
    id: str
    provider: str
    label: str
    encrypted_key: str
    priority: int
    is_enabled: bool
    rate_limit_resets_at: int | None
    rate_limit_utilization: float | None
    last_used_at: str | None
    total_requests: int
    created_at: str
    updated_at: str

    @property
    def decrypted_value(self) -> str:
        from monitor.crypto import decrypt
        return decrypt(self.encrypted_key, MASTER_KEY_PATH)

    @property
    def is_rate_limited(self) -> bool:
        if self.rate_limit_resets_at is None:
            return False
        return self.rate_limit_resets_at > time.time()

    @property
    def masked_value(self) -> str:
        from monitor.crypto import mask
        return mask(self.decrypted_value, prefix_len=4)


class KeyPool:
    """Manages a pool of API keys with rotation, cooldown tracking, and auto-wait."""

    def __init__(self, run_id: str | None = None):
        self._run_id = run_id
        self._active_key: ApiKey | None = None
        self._previous_key_id: str | None = None

    @property
    def active_key_id(self) -> str | None:
        return self._active_key.id if self._active_key else None

    @property
    def previous_key_id(self) -> str | None:
        return self._previous_key_id

    # ── Key CRUD ──────────────────────────────────────────────────────

    async def add_key(self, provider: str, raw_key: str, label: str = "", priority: int = 0) -> ApiKey:
        """Add a new API key to the pool. Encrypts before storing."""
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Invalid provider '{provider}'. Must be one of: {VALID_PROVIDERS}")
        from monitor.crypto import encrypt
        encrypted = encrypt(raw_key, MASTER_KEY_PATH)
        key_id = str(uuid.uuid4())
        conn = db.get_db()
        await conn.execute(
            """INSERT INTO api_keys (id, provider, label, encrypted_key, priority)
            VALUES (?, ?, ?, ?, ?)""",
            (key_id, provider, label, encrypted, priority),
        )
        await conn.commit()
        return await self._get_key_by_id(key_id)

    async def list_keys(self, provider: str | None = None) -> list[dict]:
        """List all keys with masked values. Never returns raw keys."""
        conn = db.get_db()
        if provider:
            cursor = await conn.execute(
                "SELECT * FROM api_keys WHERE provider = ? ORDER BY priority, created_at",
                (provider,),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM api_keys ORDER BY provider, priority, created_at"
            )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            # Mask the key value
            try:
                from monitor.crypto import decrypt, mask
                plain = decrypt(d["encrypted_key"], MASTER_KEY_PATH)
                d["masked_key"] = mask(plain, prefix_len=4)
            except Exception:
                d["masked_key"] = "****"
            del d["encrypted_key"]
            d["is_enabled"] = bool(d["is_enabled"])
            result.append(d)
        return result

    async def update_key(self, key_id: str, label: str | None = None, priority: int | None = None, is_enabled: bool | None = None) -> ApiKey:
        """Update key metadata."""
        conn = db.get_db()
        updates = []
        params = []
        if label is not None:
            updates.append("label = ?")
            params.append(label)
        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)
        if is_enabled is not None:
            updates.append("is_enabled = ?")
            params.append(1 if is_enabled else 0)
        if not updates:
            return await self._get_key_by_id(key_id)
        updates.append("updated_at = datetime('now')")
        params.append(key_id)
        await conn.execute(
            f"UPDATE api_keys SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await conn.commit()
        return await self._get_key_by_id(key_id)

    async def delete_key(self, key_id: str) -> None:
        """Delete a key. Raises if it's the last enabled key for its provider."""
        conn = db.get_db()
        # Check it's not the last enabled key
        cursor = await conn.execute(
            "SELECT provider FROM api_keys WHERE id = ?", (key_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Key {key_id} not found")
        provider = row["provider"]
        cursor = await conn.execute(
            "SELECT count(*) FROM api_keys WHERE provider = ? AND is_enabled = 1 AND id != ?",
            (provider, key_id),
        )
        count_row = await cursor.fetchone()
        # Check if this key is enabled
        cursor2 = await conn.execute(
            "SELECT is_enabled FROM api_keys WHERE id = ?", (key_id,)
        )
        key_row = await cursor2.fetchone()
        if key_row and key_row["is_enabled"] and count_row[0] == 0:
            raise ValueError(f"Cannot delete the last enabled {provider} key")
        await conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        await conn.commit()

    # ── Key Selection ─────────────────────────────────────────────────

    async def get_next_key(self, provider: str = "claude_code") -> ApiKey | None:
        """Select the best available key for the given provider.

        Selection order:
        1. Keys NOT rate-limited (resets_at IS NULL or in the past)
        2. Among those, by priority ASC
        3. Among same priority, by last_used_at ASC (LRU)
        """
        conn = db.get_db()
        now_ts = int(time.time())
        cursor = await conn.execute(
            """SELECT * FROM api_keys
            WHERE provider = ? AND is_enabled = 1
            AND (rate_limit_resets_at IS NULL OR rate_limit_resets_at <= ?)
            ORDER BY priority ASC, last_used_at ASC NULLS FIRST
            LIMIT 1""",
            (provider, now_ts),
        )
        row = await cursor.fetchone()
        if row:
            key = self._row_to_key(row)
            await self._touch_key(key.id)
            self._active_key = key
            return key
        return None

    async def handle_rate_limit(self, resets_at: float | None = None, utilization: float | None = None) -> ApiKey | None:
        """Handle a rate limit event: mark current key, try to rotate.

        Returns the next available key, or None if all exhausted.
        The caller is responsible for auto-wait if None is returned.
        """
        if self._active_key:
            self._previous_key_id = self._active_key.id
            await self.mark_rate_limited(resets_at=resets_at, utilization=utilization)

        # Try next claude_code key
        next_key = await self.get_next_key(provider="claude_code")
        if next_key:
            if self._run_id:
                await db.log_audit(self._run_id, "key_rotated", {
                    "from_key_id": self._previous_key_id,
                    "to_key_id": next_key.id,
                    "reason": "rate_limit",
                    "provider": "claude_code",
                })
            return next_key

        # Check config for codex fallback
        config = await self.get_config()
        if config.get("codex_fallback_enabled") == "true":
            codex_key = await self.get_next_key(provider="codex")
            if codex_key:
                if self._run_id:
                    await db.log_audit(self._run_id, "codex_fallback", {
                        "key_id": codex_key.id,
                        "reason": "all_claude_keys_rate_limited",
                    })
                return codex_key

        return None

    async def mark_rate_limited(self, resets_at: float | None = None, utilization: float | None = None) -> None:
        """Mark the active key as rate-limited."""
        if not self._active_key:
            return
        conn = db.get_db()
        await conn.execute(
            """UPDATE api_keys SET
                rate_limit_resets_at = ?,
                rate_limit_utilization = ?,
                total_requests = total_requests + 1,
                updated_at = datetime('now')
            WHERE id = ?""",
            (int(resets_at) if resets_at else None, utilization, self._active_key.id),
        )
        await conn.commit()
        if self._run_id:
            await db.log_audit(self._run_id, "key_rate_limited", {
                "key_id": self._active_key.id,
                "resets_at": int(resets_at) if resets_at else None,
                "utilization": utilization,
            })

    async def clear_rate_limit(self, key_id: str) -> None:
        """Clear the rate limit on a key (it's available again)."""
        conn = db.get_db()
        await conn.execute(
            """UPDATE api_keys SET
                rate_limit_resets_at = NULL,
                rate_limit_utilization = NULL,
                updated_at = datetime('now')
            WHERE id = ?""",
            (key_id,),
        )
        await conn.commit()

    # ── Auto-Wait ─────────────────────────────────────────────────────

    async def wait_for_next_available_key(self, should_stop_fn=None) -> ApiKey | None:
        """Block until a key becomes available or max_wait exceeded.

        Args:
            should_stop_fn: Optional callable that returns True if we should abort.

        Returns the key, or None if max_wait exceeded or stop requested.
        """
        config = await self.get_config()
        if config.get("auto_wait_enabled") != "true":
            return None

        max_wait = int(config.get("max_wait_minutes", "60")) * 60

        earliest = await self._get_earliest_resetting_key()
        if earliest is None:
            return None

        wait_seconds = max(0, (earliest.rate_limit_resets_at or 0) - time.time())

        if wait_seconds <= 0:
            await self.clear_rate_limit(earliest.id)
            await self._touch_key(earliest.id)
            self._active_key = earliest
            return earliest

        if wait_seconds > max_wait:
            return None

        # Log and wait
        if self._run_id:
            await db.log_audit(self._run_id, "key_pool_waiting", {
                "key_id": earliest.id,
                "wait_seconds": int(wait_seconds),
                "resets_at": earliest.rate_limit_resets_at,
            })

        # Update run status
        if self._run_id:
            await db.update_run_status(self._run_id, "waiting_for_key")

        # Sleep in 30-second chunks so we can be interrupted
        remaining = wait_seconds + 5  # 5s safety buffer
        while remaining > 0:
            chunk = min(remaining, 30)
            await asyncio.sleep(chunk)
            remaining -= chunk
            if should_stop_fn and should_stop_fn():
                return None

        await self.clear_rate_limit(earliest.id)
        await self._touch_key(earliest.id)
        self._active_key = earliest

        if self._run_id:
            await db.log_audit(self._run_id, "key_pool_resumed", {
                "key_id": earliest.id,
                "waited_seconds": int(wait_seconds + 5),
            })
            await db.update_run_status(self._run_id, "running")

        return earliest

    # ── Config ────────────────────────────────────────────────────────

    async def get_config(self) -> dict[str, str]:
        """Load rotation config, seeding defaults if needed."""
        conn = db.get_db()
        await self._seed_defaults(conn)
        cursor = await conn.execute("SELECT key, value FROM key_rotation_config")
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def update_config(self, updates: dict[str, str]) -> dict[str, str]:
        """Update rotation config values."""
        conn = db.get_db()
        for key, value in updates.items():
            if key == "rotation_strategy" and value not in VALID_STRATEGIES:
                raise ValueError(f"Invalid rotation strategy: {value}")
            await conn.execute(
                """INSERT INTO key_rotation_config (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value, updated_at = excluded.updated_at""",
                (key, value),
            )
        await conn.commit()
        return await self.get_config()

    # ── Pool Status ───────────────────────────────────────────────────

    async def get_pool_status(self) -> dict:
        """Current pool status: active key, rate limit states, next reset ETA."""
        keys = await self.list_keys()
        now = int(time.time())
        available = [k for k in keys if k.get("rate_limit_resets_at") is None or k["rate_limit_resets_at"] <= now]
        rate_limited = [k for k in keys if k.get("rate_limit_resets_at") and k["rate_limit_resets_at"] > now]
        earliest_reset = min((k["rate_limit_resets_at"] for k in rate_limited), default=None)
        return {
            "active_key_id": self.active_key_id,
            "total_keys": len(keys),
            "available_keys": len(available),
            "rate_limited_keys": len(rate_limited),
            "earliest_reset_at": earliest_reset,
            "seconds_until_reset": max(0, earliest_reset - now) if earliest_reset else None,
            "keys": keys,
        }

    # ── Migration ─────────────────────────────────────────────────────

    @staticmethod
    async def migrate_single_token_to_pool() -> bool:
        """One-time migration: move settings.claude_token into api_keys pool.

        Returns True if migration happened, False if skipped (already done or no token).
        """
        conn = db.get_db()
        cursor = await conn.execute("SELECT count(*) FROM api_keys")
        if (await cursor.fetchone())[0] > 0:
            return False  # Already migrated

        cursor = await conn.execute(
            "SELECT value, encrypted FROM settings WHERE key = 'claude_token'"
        )
        row = await cursor.fetchone()
        if not row:
            return False

        # The value is already encrypted if encrypted=1
        encrypted_key = row["value"]
        if not row["encrypted"]:
            from monitor.crypto import encrypt
            encrypted_key = encrypt(row["value"], MASTER_KEY_PATH)

        await conn.execute(
            """INSERT INTO api_keys (id, provider, label, encrypted_key, priority)
            VALUES (?, 'claude_code', 'Primary (migrated)', ?, 0)""",
            (str(uuid.uuid4()), encrypted_key),
        )
        await conn.commit()
        return True

    # ── Internal ──────────────────────────────────────────────────────

    async def _get_key_by_id(self, key_id: str) -> ApiKey:
        conn = db.get_db()
        cursor = await conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,))
        row = await cursor.fetchone()
        if not row:
            raise ValueError(f"Key {key_id} not found")
        return self._row_to_key(row)

    async def _get_earliest_resetting_key(self) -> ApiKey | None:
        """Find the key with the earliest rate_limit_resets_at."""
        conn = db.get_db()
        cursor = await conn.execute(
            """SELECT * FROM api_keys
            WHERE provider = 'claude_code' AND is_enabled = 1
            AND rate_limit_resets_at IS NOT NULL
            ORDER BY rate_limit_resets_at ASC
            LIMIT 1"""
        )
        row = await cursor.fetchone()
        return self._row_to_key(row) if row else None

    async def _touch_key(self, key_id: str) -> None:
        """Update last_used_at timestamp."""
        conn = db.get_db()
        await conn.execute(
            "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?",
            (key_id,),
        )
        await conn.commit()

    async def _seed_defaults(self, conn) -> None:
        """Seed default config values if they don't exist."""
        for key, value in DEFAULT_CONFIG.items():
            await conn.execute(
                """INSERT OR IGNORE INTO key_rotation_config (key, value)
                VALUES (?, ?)""",
                (key, value),
            )
        await conn.commit()

    @staticmethod
    def _row_to_key(row) -> ApiKey:
        return ApiKey(
            id=row["id"],
            provider=row["provider"],
            label=row["label"],
            encrypted_key=row["encrypted_key"],
            priority=row["priority"],
            is_enabled=bool(row["is_enabled"]),
            rate_limit_resets_at=row["rate_limit_resets_at"],
            rate_limit_utilization=row["rate_limit_utilization"],
            last_used_at=row["last_used_at"],
            total_requests=row["total_requests"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
