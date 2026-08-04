"""Manage warehouse branches for evaluation runs.

Each write task uses a disposable branch from the shared build branch.
Read tasks use the build branch without a fork.
Evaluation branch names start with ``eval-``. Demo branch names start with ``demo-``.

``XataBranchProvider`` creates copy-on-write branches through the Xata control plane.
The server resolves each endpoint. Only a write task receives its branch DSN.

``PostgresBranchProvider`` creates a database from a PostgreSQL template.
It provides the same isolation behavior for local deployments.

The task cleanup deletes its branch. An independent reaper deletes branches for inactive runs.
"""

from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

EVAL_BRANCH_PREFIX = "eval-"

_BRANCH_SAFE = re.compile(r"[^a-z0-9-]")


class BranchQuotaExceeded(RuntimeError):
    """Report that the evaluation branch pool reached its limit."""


class BranchError(RuntimeError):
    pass


def branch_name_for(run_id: str, task_id: str) -> str:
    """Return a lowercase, bounded evaluation branch name.

    Normalization maps `foo.bar` and `foo_bar` to `foo-bar`.
    A digest of the original task identifier prevents branch name collisions.
    """
    import hashlib

    run6 = run_id.rsplit("-", 1)[-1][:6]
    task = _BRANCH_SAFE.sub("-", task_id.lower())[:32].strip("-") or "task"
    digest = hashlib.sha256(task_id.encode()).hexdigest()[:6]
    return f"{EVAL_BRANCH_PREFIX}{run6}-{task}-{digest}"


def run_suffix_of(branch: str) -> str:
    """The <run6> segment of an eval branch name ('' if not an eval branch)."""
    if not branch.startswith(EVAL_BRANCH_PREFIX):
        return ""
    rest = branch[len(EVAL_BRANCH_PREFIX) :]
    return rest.split("-", 1)[0]


@dataclass
class BranchInfo:
    name: str
    dsn: str  # writable DSN for the branch (goes to dbt in the pod, never to MCP)


class BranchProvider(Protocol):
    async def fork(self, name: str) -> BranchInfo: ...

    async def delete(self, name: str) -> None: ...

    async def list_eval_branches(self) -> list[str]: ...

    async def database_size_bytes(self, name: str) -> int | None: ...

    async def parent_dsn(self) -> str: ...

    async def aclose(self) -> None: ...


async def enforce_branch_quota(provider: BranchProvider, ceiling: int) -> None:
    """The pre-fork check. The primary control is per-task teardown; this
    ceiling exists for when that fails, which is exactly when nothing else
    will save you."""
    existing = await provider.list_eval_branches()
    if len(existing) >= ceiling:
        raise BranchQuotaExceeded(
            f"{len(existing)} eval branches already exist (ceiling {ceiling}) — "
            "a previous run may have leaked; the reaper will clean up, or delete eval-* branches manually"
        )


# Xata.


class XataBranchProvider:
    """Forks copy-on-write children of the shared build branch."""

    def __init__(self, control, project_id: str, parent_branch: str, database: str = "xata") -> None:
        self._control = control  # gateway.connectors.xata_control.XataControlClient
        self._project_id = project_id
        self._parent_branch = parent_branch
        self._database = database

    async def _branch_by_name(self, name: str) -> dict | None:
        branches = await self._control.list_branches(self._project_id)
        return next((b for b in branches if b.get("name") == name), None)

    async def fork(self, name: str) -> BranchInfo:
        parent = await self._branch_by_name(self._parent_branch)
        if parent is None:
            raise BranchError(f"build branch '{self._parent_branch}' not found")
        await self._control.create_child_branch(self._project_id, name, parent["id"])
        dsn = await self._control.resolve_branch_endpoint(self._project_id, name, self._database)
        return BranchInfo(name=name, dsn=dsn)

    async def delete(self, name: str) -> None:
        b = await self._branch_by_name(name)
        if b is None:
            return  # A missing branch makes this operation idempotent.
        await self._control.delete_branch(self._project_id, b["id"])

    async def list_eval_branches(self) -> list[str]:
        branches = await self._control.list_branches(self._project_id)
        return [b["name"] for b in branches if str(b.get("name", "")).startswith(EVAL_BRANCH_PREFIX)]

    async def database_size_bytes(self, name: str) -> int | None:
        # The Xata control plane does not report branch storage.
        # Only PostgresBranchProvider enforces the storage delta quota.
        return None

    async def parent_dsn(self) -> str:
        return await self._control.resolve_branch_endpoint(
            self._project_id, self._parent_branch, self._database
        )

    async def aclose(self) -> None:
        # XataControlClient exposes its teardown as __aexit__, not aclose;
        # accept either so a stubbed control object in tests also closes.
        close = getattr(self._control, "aclose", None)
        if close is not None:
            await close()
            return
        aexit = getattr(self._control, "__aexit__", None)
        if aexit is not None:
            await aexit(None, None, None)


# Local Postgres.


def _swap_database(dsn: str, database: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def _branch_dsn(admin_dsn: str, database: str, user: str, password: str) -> str:
    """Same host/port as the admin DSN, but the branch-scoped credential."""
    from urllib.parse import quote

    parts = urlsplit(admin_dsn)
    hostport = parts.netloc.rsplit("@", 1)[-1]
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{hostport}"
    return urlunsplit((parts.scheme, netloc, f"/{database}", parts.query, parts.fragment))


class PostgresBranchProvider:
    """CREATE DATABASE <branch> TEMPLATE <parent> on an admin DSN.

    Each database provides an isolated branch.
    The Docker end-to-end tests use this provider.
    """

    def __init__(self, admin_dsn: str, parent_database: str) -> None:
        self._admin_dsn = admin_dsn
        self._parent_database = parent_database

    async def _admin_conn(self):
        import asyncpg

        return await asyncpg.connect(dsn=self._admin_dsn, timeout=20)

    @staticmethod
    def _ident(name: str) -> str:
        if not re.fullmatch(r"[a-z0-9_-]{1,63}", name):
            raise BranchError(f"unsafe database name: {name!r}")
        return f'"{name}"'

    @staticmethod
    def _role_for(branch: str) -> str:
        return f"{branch}_role"[:63]

    async def _mint_branch_role(self, branch: str) -> tuple[str, str]:
        """Create a role that can access only one branch database.

        Do not give the administrator DSN to model-authored code.
        An administrator can connect to the parent warehouse and bypass branch isolation.
        Create a temporary login role for each branch.
        Revoke CONNECT on every other database and delete the role during cleanup.
        """
        import secrets

        role = self._role_for(branch)
        password = secrets.token_urlsafe(24)
        conn = await self._admin_conn()
        try:
            await conn.execute(f'DROP ROLE IF EXISTS "{role}"')
            await conn.execute(
                f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}' "
                f"NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
            )
            # PUBLIC holds CONNECT on every database by default, so scoping
            # means revoking that from this role everywhere it is not wanted.
            await conn.execute(f'REVOKE ALL ON DATABASE "{self._parent_database}" FROM "{role}"')
            await conn.execute(f'GRANT CONNECT ON DATABASE {self._ident(branch)} TO "{role}"')
            reachable = await conn.fetch(
                "SELECT datname FROM pg_database "
                "WHERE datallowconn AND NOT datistemplate AND datname <> $2 "
                "AND has_database_privilege($1, datname, 'CONNECT') "
                "ORDER BY datname",
                role,
                branch,
            )
            if reachable:
                names = ", ".join(row["datname"] for row in reachable)
                await conn.execute(f'DROP ROLE IF EXISTS "{role}"')
                raise BranchError(
                    "Postgres eval isolation is not configured: PUBLIC CONNECT lets the "
                    f"task role reach {names}. Revoke PUBLIC CONNECT on every non-eval "
                    "non-template database before enabling the local branch provider."
                )
        finally:
            await conn.close()

        # Grant ownership from inside the branch database.
        # A task requires ownership to drop and rebuild marts.
        # The ownership grant applies only to this database.
        branch_conn = await self._connect_to(branch)
        try:
            for schema_row in await branch_conn.fetch(
                "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
                "AND nspname <> 'information_schema'"
            ):
                schema = schema_row["nspname"]
                await branch_conn.execute(f'ALTER SCHEMA "{schema}" OWNER TO "{role}"')
                await branch_conn.execute(f'GRANT ALL ON SCHEMA "{schema}" TO "{role}"')
                for kind, rel in (
                    ("TABLE", "r"),
                    ("TABLE", "p"),
                    ("VIEW", "v"),
                    ("SEQUENCE", "S"),
                ):
                    for obj in await branch_conn.fetch(
                        "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                        # Cast the column to text because relkind uses the PostgreSQL "char" type.
                        # A "char" parameter requires a bytes value in asyncpg.
                        "ON n.oid = c.relnamespace WHERE n.nspname = $1 AND c.relkind::text = $2",
                        schema,
                        rel,
                    ):
                        await branch_conn.execute(
                            f'ALTER {kind} "{schema}"."{obj["relname"]}" OWNER TO "{role}"'
                        )
        finally:
            await branch_conn.close()
        return role, password

    async def _connect_to(self, database: str):
        import asyncpg

        return await asyncpg.connect(dsn=_swap_database(self._admin_dsn, database), timeout=20)

    async def _drop_branch_role(self, branch: str) -> None:
        role = self._role_for(branch)
        conn = await self._admin_conn()
        try:
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = $1", role
            )
            await conn.execute(f'DROP ROLE IF EXISTS "{role}"')
        except Exception:
            logger.warning("could not drop branch role for %s", branch, exc_info=True)
        finally:
            await conn.close()

    async def fork(self, name: str) -> BranchInfo:
        import asyncio

        conn = await self._admin_conn()
        try:
            # CREATE DATABASE with TEMPLATE requires the template to have no sessions.
            # The build branch can serve concurrent read tasks and pooled MCP connections.
            # Retry the operation and close other sessions after the first rejection.
            # Governed queries and idle pool members reconnect when necessary.
            last: Exception | None = None
            for attempt in range(6):
                try:
                    await conn.execute(
                        f"CREATE DATABASE {self._ident(name)} "
                        f"TEMPLATE {self._ident(self._parent_database)}"
                    )
                    last = None
                    break
                except Exception as exc:
                    if "being accessed" not in str(exc):
                        raise
                    last = exc
                    await conn.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = $1 AND pid <> pg_backend_pid()",
                        self._parent_database,
                    )
                    await asyncio.sleep(0.3 * (attempt + 1))
            if last is not None:
                raise BranchError(
                    f"could not fork {name}: the build branch stayed busy — {last}"
                ) from last
            # PostgreSQL grants CONNECT to PUBLIC on a new database.
            # Revoke that grant before the system creates task credentials.
            # _mint_branch_role grants the task role access to this branch only.
            await conn.execute(f"REVOKE CONNECT ON DATABASE {self._ident(name)} FROM PUBLIC")
        finally:
            await conn.close()
        # Give model-authored code a least-privilege DSN instead of the administrator DSN.
        # Delete the branch immediately if role creation fails.
        try:
            role, password = await self._mint_branch_role(name)
        except Exception:
            logger.exception("role minting failed for %s — dropping the branch", name)
            with contextlib.suppress(Exception):
                await self.delete(name)
            raise
        return BranchInfo(name=name, dsn=_branch_dsn(self._admin_dsn, name, role, password))

    async def delete(self, name: str) -> None:
        if not name.startswith(EVAL_BRANCH_PREFIX):
            raise BranchError(f"refusing to drop non-eval database {name!r}")
        conn = await self._admin_conn()
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {self._ident(name)} WITH (FORCE)")
        finally:
            await conn.close()
        # Delete the role with the branch to prevent an unused credential from remaining active.
        await self._drop_branch_role(name)

    async def list_eval_branches(self) -> list[str]:
        conn = await self._admin_conn()
        try:
            rows = await conn.fetch(
                "SELECT datname FROM pg_database WHERE datname LIKE $1", f"{EVAL_BRANCH_PREFIX}%"
            )
            return [r["datname"] for r in rows]
        finally:
            await conn.close()

    async def database_size_bytes(self, name: str) -> int | None:
        conn = await self._admin_conn()
        try:
            row = await conn.fetchrow(
                "SELECT pg_database_size(datname) AS s FROM pg_database WHERE datname = $1", name
            )
            return int(row["s"]) if row else None
        finally:
            await conn.close()

    async def parent_dsn(self) -> str:
        return _swap_database(self._admin_dsn, self._parent_database)

    async def aclose(self) -> None:
        return None
