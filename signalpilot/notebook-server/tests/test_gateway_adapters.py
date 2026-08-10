from signalpilot._data.models import Database, DataSourceConnection
from signalpilot._gateway.adapters import (
    gateway_connection_to_datasource,
    gateway_schema_to_database,
)


def test_gateway_connection_uses_connection_name_without_database() -> None:
    connection = {
        "name": "warehouse-demo",
        "db_type": "xata",
        "database": None,
        "schema_name": None,
    }

    assert gateway_connection_to_datasource(connection) == DataSourceConnection(
        source="xata",
        dialect="xata",
        name="warehouse-demo",
        display_name="Xata (warehouse-demo)",
        databases=[
            Database(
                name="warehouse-demo",
                dialect="xata",
                schemas=[],
                engine="warehouse-demo",
            )
        ],
        default_database=None,
        default_schema=None,
    )


def test_gateway_schema_uses_connection_name_without_database() -> None:
    connection = {
        "name": "warehouse-demo",
        "db_type": "xata",
        "database": None,
    }

    assert gateway_schema_to_database({"tables": {}}, connection) == Database(
        name="warehouse-demo",
        dialect="xata",
        schemas=[],
        engine="warehouse-demo",
    )
