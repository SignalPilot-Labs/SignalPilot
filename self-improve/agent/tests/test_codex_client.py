"""Unit tests for agent/codex_client.py — OpenAI Codex adapter."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codex_client import CodexClient, CodexResponse


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_response():
    """Create a mock httpx response for a successful completion."""
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "output": [{"content": [{"text": "Hello world"}]}],
        "usage": {"input_tokens": 10, "output_tokens": 20},
        "model": "codex-mini-latest",
    }
    return response


@pytest.fixture
def mock_client(mock_response):
    """Create a mock httpx.AsyncClient context manager."""
    client = AsyncMock()
    client.post.return_value = mock_response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# 1. Default model
# ---------------------------------------------------------------------------


class TestDefaultModel:
    def test_default_model_is_codex_mini(self):
        """CodexClient uses 'codex-mini-latest' when no model is specified."""
        codex = CodexClient(api_key="sk-test")
        assert codex.model == "codex-mini-latest"

    def test_custom_model_is_respected(self):
        """CodexClient stores a caller-supplied model name."""
        codex = CodexClient(api_key="sk-test", model="gpt-4o")
        assert codex.model == "gpt-4o"


# ---------------------------------------------------------------------------
# 2. Authorization header
# ---------------------------------------------------------------------------


class TestCompleteHeaders:
    @pytest.mark.asyncio
    async def test_complete_sends_correct_headers(self, mock_client):
        """complete() passes Authorization: Bearer {key} to the HTTP post."""
        codex = CodexClient(api_key="sk-secret-key")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("Say hello")

        _assert_post_called(mock_client)
        _, kwargs = mock_client.post.call_args
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer sk-secret-key"

    @pytest.mark.asyncio
    async def test_complete_uses_different_key_in_header(self, mock_client):
        """Authorization header reflects the key passed at construction time."""
        codex = CodexClient(api_key="sk-other-key")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("prompt")

        _, kwargs = mock_client.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer sk-other-key"


# ---------------------------------------------------------------------------
# 3. Request payload
# ---------------------------------------------------------------------------


class TestCompletePayload:
    @pytest.mark.asyncio
    async def test_complete_sends_correct_payload(self, mock_client):
        """complete() sends model, input, and max_output_tokens in the JSON body."""
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("Write a loop", max_tokens=512)

        _assert_post_called(mock_client)
        _, kwargs = mock_client.post.call_args
        body = kwargs.get("json", {})
        assert body["model"] == "codex-mini-latest"
        assert body["input"] == "Write a loop"
        assert body["max_output_tokens"] == 512

    @pytest.mark.asyncio
    async def test_complete_default_max_tokens_is_4096(self, mock_client):
        """max_output_tokens defaults to 4096 when not specified by caller."""
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("Hello")

        _, kwargs = mock_client.post.call_args
        assert kwargs["json"]["max_output_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_complete_posts_to_responses_endpoint(self, mock_client):
        """complete() posts to the /v1/responses endpoint."""
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("Hello")

        args, _ = mock_client.post.call_args
        url = args[0]
        assert url.endswith("/v1/responses")


# ---------------------------------------------------------------------------
# 4. Response parsing
# ---------------------------------------------------------------------------


class TestCompleteResponse:
    @pytest.mark.asyncio
    async def test_complete_parses_response(self, mock_client, mock_response):
        """complete() extracts content, usage, and model from the API response."""
        mock_response.json.return_value = {
            "output": [{"content": [{"text": "Generated text here"}]}],
            "usage": {"input_tokens": 5, "output_tokens": 15},
            "model": "codex-mini-latest",
        }
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await codex.complete("prompt")

        assert isinstance(result, CodexResponse)
        assert result.content == "Generated text here"
        assert result.usage == {"input_tokens": 5, "output_tokens": 15}
        assert result.model == "codex-mini-latest"

    @pytest.mark.asyncio
    async def test_complete_returns_codex_response_instance(self, mock_client):
        """Return type of complete() is always CodexResponse."""
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await codex.complete("test")

        assert isinstance(result, CodexResponse)

    @pytest.mark.asyncio
    async def test_complete_uses_instance_model_when_api_omits_it(self, mock_client, mock_response):
        """When the API response has no 'model' key, CodexResponse.model falls back to the instance model."""
        mock_response.json.return_value = {
            "output": [{"content": [{"text": "ok"}]}],
            "usage": {},
            # no 'model' key
        }
        codex = CodexClient(api_key="sk-test", model="codex-mini-latest")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await codex.complete("test")

        assert result.model == "codex-mini-latest"

    @pytest.mark.asyncio
    async def test_complete_usage_defaults_to_empty_dict_when_missing(self, mock_client, mock_response):
        """When the API response omits 'usage', CodexResponse.usage is an empty dict."""
        mock_response.json.return_value = {
            "output": [{"content": [{"text": "ok"}]}],
            "model": "codex-mini-latest",
            # no 'usage' key
        }
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await codex.complete("test")

        assert result.usage == {}


# ---------------------------------------------------------------------------
# 5. HTTP error handling
# ---------------------------------------------------------------------------


class TestCompleteHttpErrors:
    @pytest.mark.asyncio
    async def test_complete_raises_on_http_error(self, mock_client, mock_response):
        """complete() propagates the exception when the server returns a 4xx/5xx."""
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=mock_response,
        )
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await codex.complete("bad prompt")

    @pytest.mark.asyncio
    async def test_complete_raises_on_500_error(self, mock_client, mock_response):
        """complete() propagates HTTPStatusError for 500 internal server errors."""
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=mock_response,
        )
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await codex.complete("any prompt")

    @pytest.mark.asyncio
    async def test_complete_calls_raise_for_status(self, mock_client, mock_response):
        """complete() always calls raise_for_status() so errors are not silently swallowed."""
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("hello")

        mock_response.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Timeout
# ---------------------------------------------------------------------------


class TestCompleteTimeout:
    @pytest.mark.asyncio
    async def test_complete_respects_timeout(self, mock_client):
        """complete() passes timeout=120.0 to the underlying HTTP call."""
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("hello")

        _assert_post_called(mock_client)
        _, kwargs = mock_client.post.call_args
        assert kwargs.get("timeout") == 120.0

    @pytest.mark.asyncio
    async def test_timeout_is_not_none(self, mock_client):
        """Timeout must be explicitly set — None would let the request hang forever."""
        codex = CodexClient(api_key="sk-test")
        with patch("httpx.AsyncClient", return_value=mock_client):
            await codex.complete("hello")

        _, kwargs = mock_client.post.call_args
        assert kwargs.get("timeout") is not None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _assert_post_called(mock_client):
    """Raise AssertionError with a helpful message if post() was not called."""
    assert mock_client.post.called, "Expected httpx.AsyncClient.post() to be called"
