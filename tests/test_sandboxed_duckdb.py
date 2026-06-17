from signalpilot.gateway.gateway.connectors.drivers.sandboxed_duckdb import SandboxedDuckDBConnector


def test_translate_path_uses_configured_host_data_dir(monkeypatch, tmp_path):
    host_root = tmp_path / "allowed"
    host_root.mkdir()
    db_file = host_root / "nested" / "analytics.duckdb"

    monkeypatch.setenv("SP_HOST_DATA_DIR", str(host_root))

    assert SandboxedDuckDBConnector._translate_path(str(db_file)) == "/host-data/nested/analytics.duckdb"


def test_translate_path_keeps_existing_host_data_path(monkeypatch):
    monkeypatch.setenv("SP_HOST_DATA_DIR", "/tmp/allowed")

    assert SandboxedDuckDBConnector._translate_path("/host-data/nested/analytics.duckdb") == (
        "/host-data/nested/analytics.duckdb"
    )
