from gateway.mcp.transport_security import build_allowed_hosts


def test_internal_gateway_host_is_allowed_when_public_port_is_remapped() -> None:
    assert build_allowed_hosts(["gateway"], public_port=3310) == [
        "gateway",
        "gateway:3310",
        "gateway:3300",
    ]
