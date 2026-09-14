"""Connection CRUD, credential encryption and connection-string resolution."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from sqlalchemy import and_, delete, literal, select
from sqlalchemy.exc import IntegrityError

import gateway.store.byok_state as byok_state
import gateway.store.paths as paths
from gateway.byok import decrypt_envelope, encrypt_fields_envelope
from gateway.common.credential_identity import CREDENTIAL_IDENTITY_KEY
from gateway.db.models import (
    GatewayConnection,
    GatewayCredential,
    strip_ssl_secrets,
)
from gateway.models import (
    ConnectionCreate,
    ConnectionInfo,
    ConnectionUpdate,
    DBType,
    SSHTunnelConfig,
    SSLConfig,
)
from gateway.store._constants import CURRENT_KEY_VERSION
from gateway.store.connection_strings import _build_connection_string, _extract_credential_extras
from gateway.store.crypto import (
    CredentialEncryptionError,
    _decrypt_with_migration,
    _encrypt,
)

logger = logging.getLogger(__name__)


class ConnectionsStoreMixin:
    """Connection CRUD, credential encryption and connection-string resolution."""

    # Connections.

    def _conn_filter(self):
        if self.org_id is not None:
            predicate = GatewayConnection.org_id == self.org_id
            if self.allowed_connection_name:
                predicate = and_(
                    predicate,
                    GatewayConnection.name == self.allowed_connection_name,
                )
            return predicate
        if self._allow_unscoped:
            return literal(True)
        raise ValueError(
            "Store requires org_id for connection queries. "
            "Use allow_unscoped=True for background tasks that need cross-org access."
        )

    def _require_allowed_connection(self, name: str) -> None:
        if self.allowed_connection_name and name != self.allowed_connection_name:
            raise ValueError("Connection is outside this execution's allowed scope")

    async def list_connections(self) -> list[ConnectionInfo]:
        conditions = [self._conn_filter()]
        if self.eval_connection:
            conditions.append(GatewayConnection.name == self.eval_connection)
        result = await self.session.execute(select(GatewayConnection).where(*conditions))
        return [ConnectionInfo(**row.to_info_dict()) for row in result.scalars()]

    async def get_connection(self, name: str) -> ConnectionInfo | None:
        if self.eval_connection and name != self.eval_connection:
            return None
        self._require_allowed_connection(name)
        result = await self.session.execute(
            select(GatewayConnection).where(self._conn_filter(), GatewayConnection.name == name)
        )
        row = result.scalar_one_or_none()
        return ConnectionInfo(**row.to_info_dict()) if row else None

    async def create_connection(self, conn: ConnectionCreate) -> ConnectionInfo:
        oid = self._require_org_id()
        uid = self.user_id
        # Check uniqueness
        existing = await self.get_connection(conn.name)
        if existing:
            raise ValueError(f"Connection '{conn.name}' already exists")

        # When connection_string is provided without individual fields, parse
        # host/port/database/username from the URL so they're stored as metadata
        # for display and editing.
        if conn.connection_string and not conn.host:
            from gateway.network import parse_connection_url

            try:
                db_type_str = conn.db_type.value if hasattr(conn.db_type, "value") else conn.db_type
                parsed = parse_connection_url(conn.connection_string, db_type=db_type_str)
                conn = conn.model_copy(
                    update={
                        k: v
                        for k, v in parsed.items()
                        if k
                        in (
                            "host",
                            "port",
                            "database",
                            "username",
                            "ssl",
                            "account",
                            "warehouse",
                            "schema_name",
                            "role",
                            "catalog",
                            "http_path",
                        )
                        and v  # only backfill non-empty values
                    }
                )
            except Exception:
                pass  # URL parsing failed: keep original fields

        # Strip sensitive fields from SSH/SSL for metadata storage
        ssh_tunnel_safe = None
        if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
            ssh_tunnel_safe = conn.ssh_tunnel.model_copy(
                update={
                    "password": None,
                    "private_key": None,
                    "private_key_passphrase": None,
                }
            ).model_dump()

        ssl_config_safe = None
        if conn.ssl_config and conn.ssl_config.enabled:
            ssl_config_safe = strip_ssl_secrets(conn.ssl_config.model_dump())

        conn_id = str(uuid.uuid4())
        db_conn = GatewayConnection(
            id=conn_id,
            org_id=oid,
            user_id=uid,
            name=conn.name,
            db_type=conn.db_type.value if hasattr(conn.db_type, "value") else conn.db_type,
            host=conn.host,
            port=conn.port,
            database=conn.database,
            username=conn.username,
            ssl=conn.ssl or False,
            ssl_config=ssl_config_safe,
            ssh_tunnel=ssh_tunnel_safe,
            account=conn.account,
            warehouse=conn.warehouse,
            schema_name=conn.schema_name,
            role=conn.role,
            project=conn.project,
            dataset=conn.dataset,
            location=getattr(conn, "location", None),
            http_path=conn.http_path,
            catalog=conn.catalog,
            description=conn.description,
            tags=conn.tags,
            schema_filter_include=conn.schema_filter_include,
            schema_filter_exclude=conn.schema_filter_exclude,
            schema_refresh_interval=conn.schema_refresh_interval,
            connection_timeout=conn.connection_timeout,
            query_timeout=conn.query_timeout,
            keepalive_interval=conn.keepalive_interval,
            created_at=time.time(),
            byok_key_alias=conn.byok_key_alias,
        )
        self.session.add(db_conn)

        # Store encrypted credentials
        raw_cred = conn.connection_string or _build_connection_string(conn)
        # Validate DuckDB/SQLite paths: but only for non-sandboxed modes.
        # Local file paths (host paths like C:\Users\...) are executed via the
        # gVisor sandbox which provides its own isolation. Only in-DATA_DIR
        # paths (direct connector) need the traversal check.
        if conn.db_type in (DBType.duckdb, DBType.sqlite):
            is_sandboxed = raw_cred not in (":memory:",) and not raw_cred.startswith("md:")
            if not is_sandboxed:
                paths._validate_local_db_path(raw_cred)
        extras = _extract_credential_extras(conn)

        # BYOK encrypt path: use envelope encryption when org has BYOK configured
        byok_key = None
        if oid and byok_state._byok_provider is not None:
            byok_key = await byok_state._resolve_byok_key(self.session, oid, conn.byok_key_alias)

        if byok_key is not None and byok_state._byok_provider is not None:
            ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                byok_state.provider_for_key(byok_key),
                oid,
                byok_key.key_alias,
                [raw_cred, json.dumps(extras)],
            )
            db_conn.byok_key_alias = byok_key.key_alias
            cred = GatewayCredential(
                org_id=oid,
                user_id=uid,
                connection_name=conn.name,
                connection_string_enc=ciphertexts[0],
                extras_enc=ciphertexts[1],
                key_version=CURRENT_KEY_VERSION,
                encryption_mode="byok",
                wrapped_dek=wrapped_dek,
                byok_key_id=byok_key.id,
            )
        else:
            cred = GatewayCredential(
                org_id=oid,
                user_id=uid,
                connection_name=conn.name,
                connection_string_enc=_encrypt(raw_cred),
                extras_enc=_encrypt(json.dumps(extras)),
                key_version=CURRENT_KEY_VERSION,
            )
        self.session.add(cred)
        try:
            await self.session.commit()
        except IntegrityError as e:
            await self.session.rollback()
            orig = str(e.orig) if e.orig is not None else str(e)
            if "uq_gw_conn_org_name" in orig or "uq_gw_cred_org_conn" in orig:
                raise ValueError(f"Connection '{conn.name}' already exists") from e
            raise
        await self.session.refresh(db_conn)
        return ConnectionInfo(**db_conn.to_info_dict())

    async def delete_connection(self, name: str) -> bool:
        self._require_allowed_connection(name)
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayConnection).where(GatewayConnection.org_id == oid, GatewayConnection.name == name)
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        await self.session.delete(row)
        await self.session.execute(
            delete(GatewayCredential).where(
                GatewayCredential.org_id == oid,
                GatewayCredential.connection_name == name,
            )
        )
        await self.session.commit()
        return True

    async def update_connection(self, name: str, update_data: ConnectionUpdate) -> ConnectionInfo | None:
        self._require_allowed_connection(name)
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayConnection).where(GatewayConnection.org_id == oid, GatewayConnection.name == name)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        update_fields = update_data.model_dump(exclude_none=True)
        credential_fields = {
            "password",
            "connection_string",
            "credentials_json",
            "access_token",
            "private_key",
            "private_key_passphrase",
            "motherduck_token",
        }

        # Update metadata fields
        for key, value in update_fields.items():
            if key in credential_fields:
                continue
            if key == "ssh_tunnel" and value:
                ssh_config = SSHTunnelConfig(**value) if isinstance(value, dict) else value
                value = ssh_config.model_copy(
                    update={
                        "password": None,
                        "private_key": None,
                        "private_key_passphrase": None,
                    }
                ).model_dump()
            if key == "ssl_config" and value:
                if isinstance(value, dict):
                    value = SSLConfig(**value).model_dump()
                elif isinstance(value, SSLConfig):
                    value = value.model_dump()
                value = strip_ssl_secrets(value)
            if hasattr(row, key):
                setattr(row, key, value)

        # Rebuild credentials if needed
        needs_cred_rebuild = any(
            k in update_fields
            for k in (
                "host",
                "port",
                "database",
                "username",
                "password",
                "connection_string",
                "account",
                "warehouse",
                "schema_name",
                "role",
                "project",
                "credentials_json",
                "http_path",
                "access_token",
                "catalog",
                "ssl",
                "ssl_config",
                # Xata-specific fields stored only in encrypted extras
                "branch",
                "xata_api_url",
                "xata_org",
                # Extras-only credential fields: PATCH-only changes must still rewrite extras_enc
                "private_key",
                "private_key_passphrase",
                "motherduck_token",
                "connection_timeout",
                "query_timeout",
                "keepalive_interval",
                "dataset",
                "location",
                "maximum_bytes_billed",
            )
        )
        if needs_cred_rebuild:
            existing_extras = await self.get_credential_extras(name)
            # Back-translate stored extras keys into ConnectionCreate kwarg names.
            # Two Xata fields are stored prefixed; the rest are stored identically.
            _extras_key_map = {
                "xata_database": "database",
                "xata_branch": "branch",
            }
            from_extras: dict = {}
            for stored_key, val in existing_extras.items():
                if stored_key.startswith("_"):
                    continue  # internal, non-persisted markers (see CREDENTIAL_IDENTITY_KEY)
                kwarg_name = _extras_key_map.get(stored_key, stored_key)
                from_extras[kwarg_name] = val
            # Precedence: existing extras (lowest) < column snapshot < user patch (highest)
            column_snapshot = row.to_info_dict()
            # ssl_config/ssh_tunnel are redacted in the column snapshot, so letting it
            # win over from_extras would drop the stored certs/keys on any PATCH that
            # does not itself carry them.
            for redacted_key in ("ssl_config", "ssh_tunnel"):
                if from_extras.get(redacted_key) and redacted_key not in update_fields:
                    column_snapshot.pop(redacted_key, None)
            merged = {**from_extras, **column_snapshot, **update_fields, "name": name}
            for rm_key in (
                "id",
                "created_at",
                "last_used",
                "status",
                "last_schema_refresh",
                "endorsements",
                # NOTE: do NOT add 'location' here: it IS a valid ConnectionCreate kwarg;
                # popping it wiped BQ location on every cred-rebuild PATCH after round-3
                # from_extras backfill (round 4).
            ):
                merged.pop(rm_key, None)
            try:
                create_obj = ConnectionCreate(**merged)
                raw_cred = create_obj.connection_string or _build_connection_string(create_obj)
                if create_obj.db_type in ("duckdb", "sqlite"):
                    is_sandboxed = raw_cred not in (":memory:",) and not raw_cred.startswith("md:")
                    if not is_sandboxed:
                        paths._validate_local_db_path(raw_cred)
                extras = _extract_credential_extras(create_obj)
                # Update credential row
                cred_result = await self.session.execute(
                    select(GatewayCredential).where(
                        GatewayCredential.org_id == oid,
                        GatewayCredential.connection_name == name,
                    )
                )
                cred_row = cred_result.scalar_one_or_none()
                if cred_row:
                    # BYOK encrypt path: use envelope encryption if org has BYOK configured
                    org_id = row.org_id
                    key_alias = row.byok_key_alias
                    byok_key = None
                    if org_id and byok_state._byok_provider is not None:
                        byok_key = await byok_state._resolve_byok_key(self.session, org_id, key_alias)

                    if byok_key is not None and byok_state._byok_provider is not None:
                        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                            byok_state.provider_for_key(byok_key),
                            org_id,  # type: ignore[arg-type]
                            byok_key.key_alias,
                            [raw_cred, json.dumps(extras)],
                        )
                        cred_row.connection_string_enc = ciphertexts[0]
                        cred_row.extras_enc = ciphertexts[1]
                        cred_row.key_version = CURRENT_KEY_VERSION
                        cred_row.encryption_mode = "byok"
                        cred_row.wrapped_dek = wrapped_dek
                        cred_row.byok_key_id = byok_key.id
                        row.byok_key_alias = byok_key.key_alias
                    else:
                        cred_row.connection_string_enc = _encrypt(raw_cred)
                        cred_row.extras_enc = _encrypt(json.dumps(extras))
                        cred_row.key_version = CURRENT_KEY_VERSION
                    if byok_state._dek_cache is not None:
                        byok_state._dek_cache.invalidate(cred_row.id)
            except Exception as e:
                logger.error("Credential encryption failed for connection %s: %s", name, e)
                raise CredentialEncryptionError(f"Failed to encrypt credentials for connection '{name}'") from e

        await self.session.commit()
        await self.session.refresh(row)
        return ConnectionInfo(**row.to_info_dict())

    async def get_connection_string(self, name: str) -> str | None:
        if self.eval_connection and name != self.eval_connection:
            return None
        self._require_allowed_connection(name)
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayCredential, GatewayConnection)
            .join(
                GatewayConnection,
                (GatewayConnection.org_id == GatewayCredential.org_id)
                & (GatewayConnection.name == GatewayCredential.connection_name),
                isouter=True,
            )
            .where(
                GatewayCredential.org_id == oid,
                GatewayCredential.connection_name == name,
            )
        )
        row_pair = result.first()
        if not row_pair:
            return None
        cred_row, conn_row = row_pair

        if cred_row.encryption_mode == "byok":
            if byok_state._byok_provider is None:
                raise CredentialEncryptionError("BYOK provider not configured")
            if cred_row.wrapped_dek is None:
                raise CredentialEncryptionError("Credential is in BYOK mode but has no wrapped DEK")
            org_id = conn_row.org_id if conn_row else None
            key_alias = conn_row.byok_key_alias if conn_row else None
            if not org_id or not key_alias:
                raise CredentialEncryptionError("Connection is missing BYOK configuration for decryption")
            provider = await self._byok_decrypt_provider(org_id, cred_row.byok_key_id, key_alias)
            return await decrypt_envelope(
                provider=provider,
                org_id=org_id,
                key_alias=key_alias,
                wrapped_dek=cred_row.wrapped_dek,
                ciphertext=cred_row.connection_string_enc,
                cache=byok_state._dek_cache,
                credential_id=cred_row.id,
            )

        # Managed (default) path: existing Fernet-based decryption
        plaintext, needs_migration = _decrypt_with_migration(cred_row.connection_string_enc)
        # Re-encrypt if an explicitly configured rotation key was used or the
        # stored key version is behind current.
        # Concurrent reads may both re-encrypt: this is safe because re-encryption
        # with the same key is idempotent (same plaintext, same key version result).
        needs_version_upgrade = cred_row.key_version != CURRENT_KEY_VERSION
        if needs_migration or needs_version_upgrade:
            cred_row.connection_string_enc = _encrypt(plaintext)
            # Re-encrypt extras_enc too so key_version covers both fields
            if cred_row.extras_enc:
                extras_plain, _ = _decrypt_with_migration(cred_row.extras_enc)
                cred_row.extras_enc = _encrypt(extras_plain)
            cred_row.key_version = CURRENT_KEY_VERSION
            await self.session.commit()
        return plaintext

    async def get_credential_extras(self, name: str) -> dict:
        if self.eval_connection and name != self.eval_connection:
            return {}
        self._require_allowed_connection(name)
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayCredential, GatewayConnection)
            .join(
                GatewayConnection,
                (GatewayConnection.org_id == GatewayCredential.org_id)
                & (GatewayConnection.name == GatewayCredential.connection_name),
                isouter=True,
            )
            .where(
                GatewayCredential.org_id == oid,
                GatewayCredential.connection_name == name,
            )
        )
        row_pair = result.first()
        if not row_pair:
            return {}
        cred_row, conn_row = row_pair
        if not cred_row.extras_enc:
            return {}

        if cred_row.encryption_mode == "byok":
            if byok_state._byok_provider is None:
                raise CredentialEncryptionError("BYOK provider not configured")
            if cred_row.wrapped_dek is None:
                raise CredentialEncryptionError("Credential is in BYOK mode but has no wrapped DEK")
            org_id = conn_row.org_id if conn_row else None
            key_alias = conn_row.byok_key_alias if conn_row else None
            if not org_id or not key_alias:
                raise CredentialEncryptionError("Connection is missing BYOK configuration for decryption")
            provider = await self._byok_decrypt_provider(org_id, cred_row.byok_key_id, key_alias)
            extras_json = await decrypt_envelope(
                provider=provider,
                org_id=org_id,
                key_alias=key_alias,
                wrapped_dek=cred_row.wrapped_dek,
                ciphertext=cred_row.extras_enc,
                cache=byok_state._dek_cache,
                credential_id=cred_row.id,
            )
            extras = json.loads(extras_json)
            return self._with_pool_identity(extras, cred_row)

        # Managed (default) path: existing Fernet-based decryption
        plaintext, needs_migration = _decrypt_with_migration(cred_row.extras_enc)
        # Re-encrypt if an explicitly configured rotation key was used or the
        # stored key version is behind current.
        # Concurrent reads may both re-encrypt: this is safe because re-encryption
        # with the same key is idempotent (same plaintext, same key version result).
        needs_version_upgrade = cred_row.key_version != CURRENT_KEY_VERSION
        if needs_migration or needs_version_upgrade:
            cred_row.extras_enc = _encrypt(plaintext)
            # Re-encrypt connection_string_enc too so key_version covers both fields
            if cred_row.connection_string_enc:
                cs_plain, _ = _decrypt_with_migration(cred_row.connection_string_enc)
                cred_row.connection_string_enc = _encrypt(cs_plain)
            cred_row.key_version = CURRENT_KEY_VERSION
            await self.session.commit()
        return self._with_pool_identity(json.loads(plaintext), cred_row)

    async def _byok_decrypt_provider(self, org_id: str, key_id: str | None, key_alias: str):
        """Provider that wrapped this credential's DEK: never the process default."""
        try:
            return await byok_state.resolve_decrypt_provider(self.session, org_id, key_id, key_alias)
        except byok_state.BYOKProviderUnavailable as exc:
            raise CredentialEncryptionError(str(exc)) from exc

    @staticmethod
    def _with_pool_identity(extras: dict, cred_row: GatewayCredential) -> dict:
        """Attach the non-secret credential identity consumed by the pool manager.

        Derived from the credential row id plus a digest of the stored ciphertext:
        never plaintext: so the value rotates whenever the credential is rewritten
        and carries nothing sensitive.
        """
        if not isinstance(extras, dict):
            return extras
        material = (cred_row.connection_string_enc or b"") + (cred_row.extras_enc or b"")
        digest = hashlib.sha256(material).hexdigest()[:16]
        return {**extras, CREDENTIAL_IDENTITY_KEY: f"{cred_row.id}.{digest}"}
