"""Tests for AWS IAM authentication in PostgreSQL and MySQL connectors."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestPostgresIAMAuth:
    def test_iam_auth_defaults(self):
        """IAM auth should be disabled by default."""
        from gateway.connectors.postgres import PostgresConnector
        connector = PostgresConnector()
        assert connector._iam_auth is False
        assert connector._iam_region == "us-east-1"

    def test_iam_auth_enabled_via_extras(self):
        """set_credential_extras with auth_method=iam should enable IAM auth."""
        from gateway.connectors.postgres import PostgresConnector
        connector = PostgresConnector()
        connector.set_credential_extras({
            "auth_method": "iam",
            "aws_region": "us-west-2",
            "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        })
        assert connector._iam_auth is True
        assert connector._iam_region == "us-west-2"
        assert connector._iam_access_key == "AKIAIOSFODNN7EXAMPLE"
        assert connector._iam_secret_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    def test_iam_default_region(self):
        """IAM auth without explicit region should default to us-east-1."""
        from gateway.connectors.postgres import PostgresConnector
        connector = PostgresConnector()
        connector.set_credential_extras({"auth_method": "iam"})
        assert connector._iam_region == "us-east-1"

    def test_iam_without_explicit_keys(self):
        """IAM auth without explicit keys should use instance profile (None keys)."""
        from gateway.connectors.postgres import PostgresConnector
        connector = PostgresConnector()
        connector.set_credential_extras({"auth_method": "iam", "aws_region": "eu-west-1"})
        assert connector._iam_auth is True
        assert connector._iam_access_key is None
        assert connector._iam_secret_key is None

    def test_generate_iam_token_method_exists(self):
        """_generate_iam_token method should exist."""
        from gateway.connectors.postgres import PostgresConnector
        assert hasattr(PostgresConnector, "_generate_iam_token")


class TestMySQLIAMAuth:
    def test_iam_auth_defaults(self):
        """IAM auth should be disabled by default."""
        from gateway.connectors.mysql import MySQLConnector
        connector = MySQLConnector()
        assert connector._iam_auth is False
        assert connector._iam_region == "us-east-1"

    def test_iam_auth_enabled_via_extras(self):
        """set_credential_extras with auth_method=iam should enable IAM auth."""
        from gateway.connectors.mysql import MySQLConnector
        connector = MySQLConnector()
        connector.set_credential_extras({
            "auth_method": "iam",
            "aws_region": "ap-southeast-1",
        })
        assert connector._iam_auth is True
        assert connector._iam_region == "ap-southeast-1"

    def test_generate_iam_token_method_exists(self):
        """_generate_iam_token method should exist."""
        from gateway.connectors.mysql import MySQLConnector
        assert hasattr(MySQLConnector, "_generate_iam_token")

    def test_non_iam_does_not_enable(self):
        """Setting auth_method to something other than iam should not enable it."""
        from gateway.connectors.mysql import MySQLConnector
        connector = MySQLConnector()
        connector.set_credential_extras({"auth_method": "password"})
        assert connector._iam_auth is False
