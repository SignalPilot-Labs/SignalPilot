from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from gateway.api.settings import update_mcp_agent_defaults
from gateway.models.settings import MCPAgentDefaults


async def test_reject_conflicting_project_connection_before_saving():
    store = SimpleNamespace(
        get_workspace_project=AsyncMock(return_value=SimpleNamespace(status="active", connection_name="warehouse")),
        save_settings=AsyncMock(),
    )
    with pytest.raises(HTTPException) as error:
        await update_mcp_agent_defaults(
            MCPAgentDefaults(mcp_agent_default_project_id="project", mcp_agent_default_connection_name="other"),
            store,
            None,
        )
    assert error.value.status_code == 400
    assert "Chats connection" in error.value.detail
    store.save_settings.assert_not_awaited()
