"""Notion and Slack integrations, API keys and credential rotation."""

from __future__ import annotations

import gateway.store.api_keys as api_keys
import gateway.store.notion as notion_mod
import gateway.store.settings as settings_mod
import gateway.store.slack as slack_mod
from gateway.models import (
    ApiKeyRecord,
)


class IntegrationsStoreMixin:
    """Notion and Slack integrations, API keys and credential rotation."""

    # Notion Integrations.

    async def list_notion_integrations(self) -> list[notion_mod.NotionIntegrationInfo]:
        """List all Notion integrations for this org."""
        oid = self._require_org_id()
        return await notion_mod.list_integrations(self.session, org_id=oid)

    async def get_notion_integration(self, name: str) -> notion_mod.NotionIntegrationInfo | None:
        """Get a Notion integration by name."""
        oid = self._require_org_id()
        return await notion_mod.get_integration(self.session, org_id=oid, name=name)

    async def create_notion_integration(
        self,
        integration: notion_mod.NotionIntegrationCreate,
    ) -> notion_mod.NotionIntegrationInfo:
        """Create a Notion integration with encrypted API key."""
        oid = self._require_org_id()
        return await notion_mod.create_integration(self.session, org_id=oid, integration=integration)

    async def update_notion_integration(
        self,
        name: str,
        update: notion_mod.NotionIntegrationUpdate,
    ) -> notion_mod.NotionIntegrationInfo | None:
        """Update a Notion integration."""
        oid = self._require_org_id()
        return await notion_mod.update_integration(self.session, org_id=oid, name=name, update=update)

    async def delete_notion_integration(self, name: str) -> bool:
        """Delete a Notion integration."""
        oid = self._require_org_id()
        return await notion_mod.delete_integration(self.session, org_id=oid, name=name)

    async def get_notion_api_key(self, name: str) -> str | None:
        """Get the decrypted API key for a Notion integration."""
        oid = self._require_org_id()
        return await notion_mod.get_api_key(self.session, org_id=oid, name=name)

    async def create_notion_oauth_state(self, redirect_after: str | None, ttl_seconds: int = 600) -> str:
        """Create a short-lived Notion OAuth state value."""
        oid = self._require_org_id()
        return await notion_mod.create_oauth_state(
            self.session,
            org_id=oid,
            user_id=self.user_id,
            redirect_after=redirect_after,
            ttl_seconds=ttl_seconds,
        )

    async def list_notion_oauth_installations(self) -> list[notion_mod.NotionOAuthInstallationInfo]:
        """List Notion OAuth installations for this org."""
        oid = self._require_org_id()
        return await notion_mod.list_oauth_installations(self.session, org_id=oid)

    async def get_notion_oauth_installation(
        self,
        installation_id: str,
    ) -> notion_mod.NotionOAuthInstallationInfo | None:
        """Get a Notion OAuth installation for this org."""
        oid = self._require_org_id()
        return await notion_mod.get_oauth_installation(self.session, org_id=oid, installation_id=installation_id)

    async def get_notion_oauth_installation_token(self, installation_id: str) -> str | None:
        """Get the decrypted Notion OAuth access token for this org."""
        oid = self._require_org_id()
        return await notion_mod.get_oauth_installation_token(
            self.session,
            org_id=oid,
            installation_id=installation_id,
        )

    async def get_notion_oauth_installation_tokens(self, installation_id: str) -> tuple[str, str | None] | None:
        """Get the decrypted Notion OAuth access and refresh tokens for this org."""
        oid = self._require_org_id()
        return await notion_mod.get_oauth_installation_tokens(
            self.session,
            org_id=oid,
            installation_id=installation_id,
        )

    async def update_notion_oauth_installation_tokens(
        self,
        installation_id: str,
        access_token: str,
        refresh_token: str | None,
    ) -> None:
        """Update encrypted Notion OAuth tokens after refresh."""
        oid = self._require_org_id()
        await notion_mod.update_oauth_installation_tokens(
            self.session,
            org_id=oid,
            installation_id=installation_id,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def save_notion_oauth_installation_config(
        self,
        installation_id: str,
        parent_page_id: str | None,
        trigger_page_id: str,
        requests_data_source_id: str,
        requests_database_page_id: str,
        enabled: bool = True,
        default_project_id: str | None = None,
        default_branch: str = "main",
        analysis_branch_mode: str = "per_request",
    ) -> notion_mod.NotionOAuthInstallationInfo | None:
        """Save provisioned Notion resources for an OAuth installation."""
        oid = self._require_org_id()
        return await notion_mod.save_oauth_installation_config(
            self.session,
            org_id=oid,
            installation_id=installation_id,
            parent_page_id=parent_page_id,
            trigger_page_id=trigger_page_id,
            requests_data_source_id=requests_data_source_id,
            requests_database_page_id=requests_database_page_id,
            enabled=enabled,
            default_project_id=default_project_id,
            default_branch=default_branch,
            analysis_branch_mode=analysis_branch_mode,
        )

    async def disable_notion_oauth_installation(self, installation_id: str) -> bool:
        """Disable a Notion OAuth installation for this org."""
        oid = self._require_org_id()
        return await notion_mod.disable_oauth_installation(
            self.session,
            org_id=oid,
            installation_id=installation_id,
        )

    # Slack Integrations.

    async def create_slack_oauth_state(self, redirect_after: str | None, ttl_seconds: int = 600) -> str:
        """Create a short-lived Slack OAuth state value."""
        oid = self._require_org_id()
        return await slack_mod.create_oauth_state(
            self.session,
            org_id=oid,
            user_id=self.user_id,
            redirect_after=redirect_after,
            ttl_seconds=ttl_seconds,
        )

    async def list_slack_oauth_installations(self) -> list[slack_mod.SlackOAuthInstallationInfo]:
        """List Slack OAuth installations for this org."""
        oid = self._require_org_id()
        return await slack_mod.list_oauth_installations(self.session, org_id=oid)

    async def get_slack_oauth_installation(
        self,
        installation_id: str,
    ) -> slack_mod.SlackOAuthInstallationInfo | None:
        """Get a Slack OAuth installation for this org."""
        oid = self._require_org_id()
        return await slack_mod.get_oauth_installation(self.session, org_id=oid, installation_id=installation_id)

    async def save_slack_oauth_installation_config(
        self,
        installation_id: str,
        enabled: bool = True,
        default_project_id: str | None = None,
        default_branch: str = "main",
        analysis_branch_mode: str = "per_request",
        allowed_channel_ids: list[str] | None = None,
    ) -> slack_mod.SlackOAuthInstallationInfo | None:
        """Save setup defaults for a Slack OAuth installation."""
        oid = self._require_org_id()
        return await slack_mod.save_oauth_installation_config(
            self.session,
            org_id=oid,
            installation_id=installation_id,
            enabled=enabled,
            default_project_id=default_project_id,
            default_branch=default_branch,
            analysis_branch_mode=analysis_branch_mode,
            allowed_channel_ids=allowed_channel_ids,
        )

    async def disable_slack_oauth_installation(self, installation_id: str) -> bool:
        """Disable a Slack OAuth installation for this org."""
        oid = self._require_org_id()
        return await slack_mod.disable_oauth_installation(
            self.session,
            org_id=oid,
            installation_id=installation_id,
        )

    # API Keys.
    async def list_api_keys(self, *, user_id: str | None = None) -> list[ApiKeyRecord]:
        return await api_keys.list_api_keys(
            self.session, org_id=self.org_id, allow_unscoped=self._allow_unscoped, user_id=user_id
        )

    async def get_api_key(self, key_id: str) -> ApiKeyRecord | None:
        oid = self._require_org_id()
        return await api_keys.get_api_key(self.session, org_id=oid, key_id=key_id)

    async def create_api_key(
        self,
        name: str,
        scopes: list[str],
        expires_at: str | None = None,
        eval_binding: dict | None = None,
    ) -> tuple[ApiKeyRecord, str]:
        oid = self._require_org_id()
        return await api_keys.create_api_key(
            self.session,
            org_id=oid,
            user_id=self.user_id,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
            eval_binding=eval_binding,
        )

    async def delete_api_key(self, key_id: str) -> bool:
        oid = self._require_org_id()
        return await api_keys.delete_api_key(self.session, org_id=oid, key_id=key_id)

    async def validate_stored_api_key(self, raw_key: str) -> ApiKeyRecord | None:
        return await api_keys.validate_stored_api_key(self.session, raw_key)

    # Key Rotation.

    async def get_credentials_needing_rotation(self, org_scoped: bool = True) -> int:
        """Return count of credentials encrypted with a key version below CURRENT_KEY_VERSION.

        ORG-SCOPED by default (org_scoped=True): filters to the current org via
        _require_org_id(). Cross-org count is opt-in (org_scoped=False) and
        intended only for future operator-only callers: no production caller
        currently passes org_scoped=False.
        """
        org_id = self._require_org_id() if org_scoped else None
        return await settings_mod.get_credentials_needing_rotation(self.session, org_id=org_id)
