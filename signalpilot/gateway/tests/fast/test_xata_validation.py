"""Pure-unit tests for Xata field validation, URL-quoting, and related helpers.

No DB, no network — all external I/O is mocked.
Groups:
  1. SSRF rejection on Create and Update
  2. Branch regex valid/invalid
  3. xata_org regex rejection (NEW — Item 2 coverage)
  4. xata_org URL-quote at the call site (NEW — Item 2 coverage)
  5. OIDC missing-cred error
  6. sanitize_db_error strips secrets
  7. _profile_pg_stats uses positional placeholders
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from gateway.api.deps import sanitize_db_error
from gateway.connectors.xata_control import XataControlClient, XataControlConfig, XataControlError
from gateway.mcp.tools.model_map import _profile_pg_stats
from gateway.models import ConnectionCreate, ConnectionUpdate

# ─── Module-level helpers ─────────────────────────────────────────────────────

_MINIMAL_XATA_CREATE = {
    "name": "t",
    "db_type": "xata",
    "region": "us-east-1",
    "database": "mydb",
}

_FAKE_CREDENTIALS_JSON = json.dumps(
    {
        "type": "service_account",
        "project_id": "p",
        "private_key_id": "k",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----",
        "client_email": "sa@p.iam.gserviceaccount.com",
        "client_id": "1",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


def _make_xata_create(**kwargs) -> dict:
    return {**_MINIMAL_XATA_CREATE, **kwargs}


# ─── Group 1: SSRF rejection ──────────────────────────────────────────────────


class TestSsrfRejection:
    _PRIVATE_URLS = [
        "http://127.0.0.1/",
        "http://169.254.169.254/",
        "http://10.0.0.1/",
        "http://[::1]/",
        "http://metadata.google.internal/",
    ]

    @pytest.mark.parametrize("bad_url", _PRIVATE_URLS)
    def test_ssrf_rejected_on_create_xata_api_url(self, bad_url: str) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(**_make_xata_create(xata_api_url=bad_url))

    @pytest.mark.parametrize("bad_url", _PRIVATE_URLS)
    def test_ssrf_rejected_on_create_xata_token_url(self, bad_url: str) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(
                **_make_xata_create(
                    xata_token_url=bad_url,
                    xata_client_id="c",
                    xata_client_secret="s",
                    xata_username="u",
                    xata_password="p",
                )
            )

    def test_ssrf_rejected_on_update_xata_api_url(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionUpdate(xata_api_url="http://127.0.0.1/")


# ─── Group 2: Branch regex ────────────────────────────────────────────────────


class TestBranchRegex:
    _VALID_BRANCHES = ["main", "feature-1", "release.2024", "a_b.c-d"]
    _INVALID_BRANCHES = [
        "",
        "has space",
        "slash/x",
        "dollar$",
        "a" * 65,
    ]

    @pytest.mark.parametrize("branch", _VALID_BRANCHES)
    def test_valid_branch_accepted_on_create(self, branch: str) -> None:
        obj = ConnectionCreate(**_make_xata_create(branch=branch))
        assert obj.branch == branch

    @pytest.mark.parametrize("branch", _INVALID_BRANCHES)
    def test_invalid_branch_rejected_on_create(self, branch: str) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(**_make_xata_create(branch=branch))


# ─── Group 3: xata_org regex ─────────────────────────────────────────────────


class TestXataOrgRegex:
    _VALID_ORGS = ["my-org", "org_1", "OrgABC"]
    _INVALID_ORGS = [
        "my/org",
        "my..org",
        "my?x",
        "my#x",
        "my org",
        "",
        "a" * 65,
    ]

    @pytest.mark.parametrize("org", _VALID_ORGS)
    def test_valid_org_accepted_on_create(self, org: str) -> None:
        obj = ConnectionCreate(**_make_xata_create(xata_org=org))
        assert obj.xata_org == org

    @pytest.mark.parametrize("org", _INVALID_ORGS)
    def test_invalid_org_rejected_on_create(self, org: str) -> None:
        with pytest.raises(ValidationError):
            ConnectionCreate(**_make_xata_create(xata_org=org))

    def test_invalid_org_rejected_on_update(self) -> None:
        with pytest.raises(ValidationError):
            ConnectionUpdate(xata_org="my/org")


# ─── Group 4: xata_org URL-quote at the call site ────────────────────────────


class TestXataOrgUrlQuote:
    @pytest.mark.asyncio
    async def test_safe_org_url_contains_literal_org_name(self) -> None:
        """list_projects encodes org into the request URL."""
        cfg = XataControlConfig(api_url="https://api.xata.io", org="ok-org", bearer_token="t")
        client = XataControlClient(cfg)

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b'{"projects":[]}'
        fake_response.json = lambda: {"projects": []}

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=fake_response)
        client._client = mock_http

        result = await client.list_projects()
        assert result == []

        called_url = mock_http.request.call_args[0][1]
        assert "/organizations/ok-org/projects" in called_url

    @pytest.mark.asyncio
    async def test_org_with_special_chars_is_percent_encoded(self) -> None:
        """URL-quote encodes unsafe chars in org; 'weird org' becomes 'weird%20org'."""
        cfg = XataControlConfig(api_url="https://api.xata.io", org="weird org", bearer_token="t")
        client = XataControlClient(cfg)

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b'{"projects":[]}'
        fake_response.json = lambda: {"projects": []}

        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=fake_response)
        client._client = mock_http

        await client.list_projects()

        called_url = mock_http.request.call_args[0][1]
        assert "/organizations/weird%20org/projects" in called_url


# ─── Group 5: OIDC missing-cred error ────────────────────────────────────────


class TestOidcMissingCredError:
    @pytest.mark.asyncio
    async def test_token_raises_when_oidc_creds_missing(self) -> None:
        """_token raises XataControlError('OIDC credentials missing') when creds absent."""
        cfg = XataControlConfig(
            api_url="https://api.xata.io",
            token_url="https://sso.example.com/token",
            # no client_id / client_secret / username / password
        )
        client = XataControlClient(cfg)
        mock_http = AsyncMock()
        client._client = mock_http

        with pytest.raises(XataControlError, match="OIDC credentials missing"):
            await client._token(mock_http)


# ─── Group 6: sanitize_db_error strips secrets ───────────────────────────────


class TestSanitizeDbError:
    def test_access_token_is_redacted(self) -> None:
        msg = "request failed: access_token=super-secret-value and something else"
        result = sanitize_db_error(msg)
        assert "super-secret-value" not in result
        assert result  # non-empty

    def test_private_key_is_redacted(self) -> None:
        msg = "auth failed: private_key=BEGINPRIVATE and other info"
        result = sanitize_db_error(msg)
        assert "BEGINPRIVATE" not in result
        assert result

    def test_password_is_redacted(self) -> None:
        msg = "connect error: password=hunter2"
        result = sanitize_db_error(msg)
        assert "hunter2" not in result
        assert result

    def test_function_does_not_raise_on_clean_message(self) -> None:
        result = sanitize_db_error("connection refused: host unreachable")
        assert result


# ─── Group 7: _profile_pg_stats uses positional placeholders ─────────────────


class TestProfilePgStatsParameterization:
    @pytest.mark.asyncio
    async def test_uses_positional_placeholders_not_interpolation(self) -> None:
        """_profile_pg_stats must pass schema/table as params ($1/$2), never interpolated.

        The fake execute returns a stat row for the 'id' column so the column is
        satisfied from pg_stats and _profile_exact is NOT called (avoiding the
        need to mock quote_table / quote_identifier).
        """
        captured_sql: list[str] = []
        captured_params: list[list] = []

        async def fake_execute(sql: str, params: list) -> list:
            captured_sql.append(sql)
            captured_params.append(params)
            # Return a fake pg_stats row so 'id' column is resolved here and
            # _profile_exact is never reached.
            return [{"attname": "id", "null_frac": 0.0, "n_distinct": 100.0}]

        connector = MagicMock()
        connector.execute = fake_execute

        await _profile_pg_stats(connector, "public", "public.users", [("id", "INT")], rows=1000)

        assert captured_sql, "execute was never called"
        sql = captured_sql[0]
        assert "$1" in sql, f"Expected positional placeholder $1 in SQL; got: {sql!r}"
        assert "$2" in sql, f"Expected positional placeholder $2 in SQL; got: {sql!r}"
        # 'schemaname' and 'tablename' literals are allowed in the SQL template;
        # what must NOT appear is the literal value of the schema/table name.
        template_only = sql.replace("schemaname", "").replace("tablename", "")
        assert "public.users" not in template_only, (
            "Table key 'public.users' appears to be interpolated directly into SQL"
        )
        params = captured_params[0]
        assert params == ["public", "users"], f"Expected params=['public', 'users']; got {params!r}"
