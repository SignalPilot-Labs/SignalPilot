"""Tests for Redshift IAM auth and MSSQL Azure AD auth."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestRedshiftIAMAuth:
    """Test Redshift IAM auth configuration."""

    def test_iam_auth_defaults(self):
        from gateway.connectors.redshift import RedshiftConnector
        c = RedshiftConnector()
        assert c._iam_auth is False
        assert c._iam_region == "us-east-1"
        assert c._iam_cluster_id == ""
        assert c._iam_workgroup == ""

    def test_iam_auth_enabled_via_extras(self):
        from gateway.connectors.redshift import RedshiftConnector
        c = RedshiftConnector()
        c.set_credential_extras({
            "auth_method": "iam",
            "aws_region": "eu-west-1",
            "cluster_id": "my-cluster",
        })
        assert c._iam_auth is True
        assert c._iam_region == "eu-west-1"
        assert c._iam_cluster_id == "my-cluster"

    def test_iam_serverless_workgroup(self):
        from gateway.connectors.redshift import RedshiftConnector
        c = RedshiftConnector()
        c.set_credential_extras({
            "iam_auth": True,
            "aws_region": "us-west-2",
            "workgroup": "default",
        })
        assert c._iam_auth is True
        assert c._iam_workgroup == "default"
        assert c._iam_cluster_id == ""

    def test_generate_iam_credentials_method_exists(self):
        from gateway.connectors.redshift import RedshiftConnector
        c = RedshiftConnector()
        assert hasattr(c, "_generate_iam_credentials")

    def test_iam_without_explicit_keys(self):
        """IAM auth should work without explicit AWS keys (uses env/instance profile)."""
        from gateway.connectors.redshift import RedshiftConnector
        c = RedshiftConnector()
        c.set_credential_extras({"auth_method": "iam"})
        assert c._iam_auth is True
        assert c._iam_access_key == ""
        assert c._iam_secret_key == ""


class TestMSSQLAzureADAuth:
    """Test MSSQL Azure AD / Entra ID auth configuration."""

    def test_azure_ad_defaults(self):
        from gateway.connectors.mssql import MSSQLConnector
        c = MSSQLConnector()
        assert c._azure_ad_auth is False
        assert c._azure_tenant_id == ""
        assert c._azure_client_id == ""

    def test_azure_ad_enabled_via_extras(self):
        from gateway.connectors.mssql import MSSQLConnector
        c = MSSQLConnector()
        c.set_credential_extras({
            "auth_method": "azure_ad",
            "azure_tenant_id": "tenant-123",
            "azure_client_id": "client-456",
            "azure_client_secret": "secret-789",
        })
        assert c._azure_ad_auth is True
        assert c._azure_tenant_id == "tenant-123"
        assert c._azure_client_id == "client-456"
        assert c._azure_client_secret == "secret-789"

    def test_acquire_token_method_exists(self):
        from gateway.connectors.mssql import MSSQLConnector
        c = MSSQLConnector()
        assert hasattr(c, "_acquire_azure_ad_token")

    def test_non_azure_ad_does_not_enable(self):
        from gateway.connectors.mssql import MSSQLConnector
        c = MSSQLConnector()
        c.set_credential_extras({"connection_timeout": 30})
        assert c._azure_ad_auth is False
