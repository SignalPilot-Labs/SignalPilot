"""Verify repository restrictions in gateway/evals/runner._assert_repo_allowed.

The gateway passes the repository URL to Git clone. Local mode restricts local
paths to projects_dir and permits only GitHub URLs. Cloud mode permits only
HTTPS URLs for github.com.
"""

from __future__ import annotations

import pytest

from gateway.config.evals import get_eval_run_settings
from gateway.evals import runner


class _Settings:
    """Just what the gate reads."""

    def __init__(self, projects_dir: str) -> None:
        self.projects_dir = projects_dir


@pytest.fixture(autouse=True)
def _settings_cache():
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects"
    (root / "set-1").mkdir(parents=True)
    return root


@pytest.fixture
def settings(projects):
    return _Settings(str(projects))


@pytest.fixture
def local_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setattr("gateway.runtime.mode.is_cloud_mode", lambda: False)


@pytest.fixture
def cloud_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("gateway.runtime.mode.is_cloud_mode", lambda: True)


def _refused(url: str, settings) -> None:
    with pytest.raises(runner.RepoRefused):
        runner._assert_repo_allowed(url, settings=settings, what="eval repo")


class TestLocalMode:
    def test_a_path_under_projects_dir_is_allowed(self, local_mode, projects, settings) -> None:
        runner._assert_repo_allowed(
            str(projects / "set-1"), settings=settings, what="eval repo"
        )  # must not raise

    def test_projects_dir_itself_is_allowed(self, local_mode, projects, settings) -> None:
        runner._assert_repo_allowed(str(projects), settings=settings, what="eval repo")

    def test_a_path_outside_projects_dir_is_refused(
        self, local_mode, tmp_path, settings
    ) -> None:
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        _refused(str(outside), settings)

    def test_dotdot_traversal_out_of_projects_dir_is_refused(
        self, local_mode, tmp_path, projects, settings
    ) -> None:
        (tmp_path / "escape").mkdir()
        _refused(str(projects / "set-1" / ".." / ".." / "escape"), settings)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ssh://host/repo.git",
            "git@host:org/repo.git",
            "git://host/repo.git",
            "http://evil/x",
        ],
    )
    def test_non_github_url_schemes_are_refused(self, local_mode, settings, url) -> None:
        _refused(url, settings)

    def test_https_github_is_allowed(self, local_mode, settings) -> None:
        runner._assert_repo_allowed(
            "https://github.com/o/r.git", settings=settings, what="eval repo"
        )

    def test_empty_string_is_refused(self, local_mode, settings) -> None:
        _refused("", settings)
        _refused("   ", settings)

    def test_the_refusal_names_what_was_gated(self, local_mode, settings) -> None:
        with pytest.raises(runner.RepoRefused, match="dbt project repo"):
            runner._assert_repo_allowed(
                "git://host/x", settings=settings, what="dbt project repo"
            )


class TestCloudMode:
    def test_https_github_is_the_only_allowed_shape(self, cloud_mode, settings) -> None:
        runner._assert_repo_allowed(
            "https://github.com/o/r.git", settings=settings, what="eval repo"
        )

    def test_a_local_path_under_projects_dir_is_refused_too(
        self, cloud_mode, projects, settings
    ) -> None:
        _refused(str(projects / "set-1"), settings)

    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.com/o/r.git",
            "http://github.com/o/r.git",  # not https
            "file:///eval-projects/set-1",
            "ssh://github.com/o/r.git",
            "git@github.com:o/r.git",
            "git://github.com/o/r.git",
            "http://evil/x",
        ],
    )
    def test_everything_else_is_refused(self, cloud_mode, settings, url) -> None:
        _refused(url, settings)

    def test_empty_string_is_refused(self, cloud_mode, settings) -> None:
        _refused("", settings)


class TestXataExtrasKeyNames:
    """resolve_branch_provider must read the key names the connection model
    actually persists. Reading xata_org/database instead of
    xata_organization/xata_database produced an empty org and a 404 on every
    control-plane call — silently, because the empty string is falsy but not
    an error until the URL is built.
    """

    async def test_missing_organization_is_refused_not_silently_empty(self, tmp_path) -> None:
        from gateway.config.evals import get_eval_run_settings
        from gateway.evals.provision import ProvisioningError, resolve_branch_provider

        class Store:
            org_id = "org-1"

            async def get_credential_extras(self, name: str) -> dict:
                # A Xata connection with the pin but no organization.
                return {"xata_project": "prj_x", "branch": "main"}

        get_eval_run_settings.cache_clear()
        try:
            settings = get_eval_run_settings()
            with pytest.raises(ProvisioningError) as exc:
                await resolve_branch_provider(Store(), {"connection": "c"}, settings)
            assert "xata_organization" in str(exc.value)
        finally:
            get_eval_run_settings.cache_clear()

    def test_reads_the_persisted_key_names(self) -> None:
        import inspect

        from gateway.evals import provision

        src = inspect.getsource(provision.resolve_branch_provider)
        assert "xata_organization" in src
        assert "xata_database" in src
