"""Slack Socket Mode proof-of-concept for notebook-backed SignalPilot analysis."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import signal
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.db.engine import close_db, get_session_factory, init_db
from gateway.notebooks.session_service import NotebookRuntime, ensure_notion_notebook_session
from gateway.notion import analysis as notebook_analysis

LOGGER = logging.getLogger(__name__)
SLACK_API_BASE = "https://slack.com/api"
SLACK_TEXT_LIMIT = 35000
SLACK_CHART_LIMIT = 3


class SlackApiError(RuntimeError):
    """Raised when Slack Web API returns ok=false or a non-2xx response."""


def _slack_api_error(method: str, data: dict[str, Any]) -> SlackApiError:
    details = data.get("error") or data
    metadata = data.get("response_metadata")
    if isinstance(metadata, dict):
        messages = metadata.get("messages")
        if isinstance(messages, list) and messages:
            details = f"{details}: {'; '.join(str(message) for message in messages)}"
    return SlackApiError(f"Slack {method} failed: {details}")


@dataclass(frozen=True)
class SlackPoCConfig:
    bot_token: str
    app_token: str
    signing_secret: str | None = None
    bot_user_id: str | None = None
    org_id: str = "slack-poc"
    user_id: str = "slack-poc-worker"
    allowed_channel_ids: frozenset[str] = frozenset()
    ack_text: str = "I'm on it and will post the answer back here soon."


@dataclass(frozen=True)
class SlackRequest:
    event_id: str
    team_id: str
    channel_id: str
    user_id: str
    text: str
    event_ts: str
    thread_ts: str
    source_url: str


class SlackApiClient:
    def __init__(self, bot_token: str, app_token: str, *, http_client: httpx.AsyncClient | None = None) -> None:
        self.bot_token = bot_token
        self.app_token = app_token
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=30)

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def _api(self, method: str, payload: dict[str, Any] | None = None, *, token: str | None = None) -> dict[str, Any]:
        response = await self._client.post(
            f"{SLACK_API_BASE}/{method}",
            headers={"Authorization": f"Bearer {token or self.bot_token}", "Content-Type": "application/json"},
            json=payload or {},
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise _slack_api_error(method, data)
        return data

    async def _api_form(self, method: str, payload: dict[str, str], *, token: str | None = None) -> dict[str, Any]:
        response = await self._client.post(
            f"{SLACK_API_BASE}/{method}",
            headers={"Authorization": f"Bearer {token or self.bot_token}"},
            data=payload,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise _slack_api_error(method, data)
        return data

    async def fetch_bytes(self, url: str) -> tuple[bytes, str]:
        response = await self._client.get(url)
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "application/octet-stream").split(";", 1)[0]
        return response.content, content_type.strip() or "application/octet-stream"

    async def auth_test(self) -> dict[str, Any]:
        return await self._api("auth.test")

    async def socket_url(self) -> str:
        data = await self._api("apps.connections.open", token=self.app_token)
        url = data.get("url")
        if not isinstance(url, str) or not url:
            raise SlackApiError("Slack apps.connections.open did not return a websocket URL")
        return url

    async def post_message(self, *, channel: str, text: str, thread_ts: str | None = None) -> str:
        payload: dict[str, Any] = {
            "channel": channel,
            "text": _clip_text(text),
            "mrkdwn": True,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        data = await self._api("chat.postMessage", payload)
        ts = data.get("ts")
        return str(ts) if ts else ""

    async def upload_file(
        self,
        *,
        channel: str,
        thread_ts: str,
        filename: str,
        title: str,
        content: bytes,
        content_type: str,
    ) -> None:
        upload = await self._api_form(
            "files.getUploadURLExternal",
            {"filename": filename, "length": str(len(content))},
        )
        upload_url = upload.get("upload_url")
        file_id = upload.get("file_id")
        if not isinstance(upload_url, str) or not isinstance(file_id, str):
            raise SlackApiError("Slack files.getUploadURLExternal did not return upload_url and file_id")

        response = await self._client.post(
            upload_url,
            content=content,
            headers={"Content-Type": content_type, "Content-Length": str(len(content))},
        )
        response.raise_for_status()

        await self._api_form(
            "files.completeUploadExternal",
            {
                "files": json.dumps([{"id": file_id, "title": title}]),
                "channel_id": channel,
                "thread_ts": thread_ts,
            },
        )

    async def thread_messages(self, *, channel: str, thread_ts: str) -> list[dict[str, Any]]:
        data = await self._api("conversations.replies", {"channel": channel, "ts": thread_ts, "limit": 20})
        messages = data.get("messages")
        return messages if isinstance(messages, list) else []

    async def permalink(self, *, channel: str, message_ts: str) -> str:
        try:
            data = await self._api("chat.getPermalink", {"channel": channel, "message_ts": message_ts})
        except Exception as exc:
            LOGGER.info("Could not fetch Slack permalink for channel=%s ts=%s: %s", channel, message_ts, exc)
            return f"slack://channel/{channel}/p{message_ts.replace('.', '')}"
        permalink = data.get("permalink")
        return str(permalink) if permalink else f"slack://channel/{channel}/p{message_ts.replace('.', '')}"


class SlackPoCWorker:
    def __init__(
        self,
        config: SlackPoCConfig,
        slack: SlackApiClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.config = config
        self.slack = slack
        self.session_factory = session_factory
        self._seen_event_ids: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def handle_events_api_payload(self, payload: dict[str, Any]) -> None:
        request = await self._request_from_payload(payload)
        if request is None:
            return
        if request.event_id in self._seen_event_ids:
            LOGGER.info("Ignoring duplicate Slack event_id=%s", request.event_id)
            return
        self._seen_event_ids.add(request.event_id)
        task = asyncio.create_task(self._process_request(request), name=f"slack-poc-{request.event_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _request_from_payload(self, payload: dict[str, Any]) -> SlackRequest | None:
        event = payload.get("event")
        if not isinstance(event, dict):
            return None

        event_type = event.get("type")
        channel_id = _string(event.get("channel"))
        if self.config.allowed_channel_ids and channel_id not in self.config.allowed_channel_ids:
            LOGGER.info("Ignoring Slack event in non-allowed channel=%s", channel_id)
            return None

        if event.get("subtype") or event.get("bot_id"):
            return None

        user_id = _string(event.get("user"))
        if not user_id or user_id == self.config.bot_user_id:
            return None

        text = _string(event.get("text")).strip()
        if event_type == "app_mention":
            text = _remove_bot_mention(text, self.config.bot_user_id).strip()
        elif event_type == "message" and event.get("channel_type") == "im":
            pass
        else:
            return None

        if not text:
            await self.slack.post_message(
                channel=channel_id,
                thread_ts=_string(event.get("thread_ts")) or _string(event.get("ts")),
                text="Ask me a data question after the mention and I'll run it through SignalPilot.",
            )
            return None

        event_ts = _string(event.get("ts") or event.get("event_ts"))
        thread_ts = _string(event.get("thread_ts")) or event_ts
        team_id = _string(event.get("team") or payload.get("team_id") or _first_authorization_team_id(payload))
        source_url = await self.slack.permalink(channel=channel_id, message_ts=event_ts)

        return SlackRequest(
            event_id=_string(payload.get("event_id")) or f"{team_id}:{channel_id}:{event_ts}",
            team_id=team_id,
            channel_id=channel_id,
            user_id=user_id,
            text=text,
            event_ts=event_ts,
            thread_ts=thread_ts,
            source_url=source_url,
        )

    async def _process_request(self, request: SlackRequest) -> None:
        trail_url: str | None = None
        await self.slack.post_message(channel=request.channel_id, thread_ts=request.thread_ts, text=self.config.ack_text)
        try:
            previous_messages = await self._previous_thread_messages(request)
            async with self.session_factory() as db:
                runtime = await ensure_notion_notebook_session(db, self.config.org_id, self.config.user_id)
                start = await self._start_analysis(runtime, request, previous_messages)
                trail_url = notebook_analysis._public_signalpilot_url(_string(start.get("trailUrl")), runtime)
                status = await notebook_analysis._poll_analysis(
                    _string(start["requestId"]),
                    runtime,
                    self.config.org_id,
                    self.config.user_id,
                )
                slack_status = notebook_analysis._with_public_chart_urls(status, runtime)
            await self.slack.post_message(
                channel=request.channel_id,
                thread_ts=request.thread_ts,
                text=_final_slack_text(slack_status, trail_url),
            )
            await self._post_chart_attachments(request, status, runtime)
        except Exception as exc:
            LOGGER.warning("Slack PoC request failed: event_id=%s error=%s", request.event_id, exc, exc_info=True)
            await self.slack.post_message(
                channel=request.channel_id,
                thread_ts=request.thread_ts,
                text=_failure_slack_text(str(exc), trail_url),
            )

    async def _post_chart_attachments(
        self,
        request: SlackRequest,
        status: dict[str, Any],
        runtime: NotebookRuntime,
    ) -> None:
        charts = _status_charts(status)[:SLACK_CHART_LIMIT]
        if not charts:
            return

        attached = 0
        errors: list[str] = []
        for index, chart in enumerate(charts):
            title = _chart_value(chart, "title") or f"Chart {index + 1}"
            source_url = _chart_value(chart, "url")
            if not source_url:
                continue
            try:
                fetch_url = notebook_analysis._internal_signalpilot_url(source_url, runtime)
                content, content_type = await self.slack.fetch_bytes(fetch_url)
                if not content_type.startswith("image/"):
                    raise RuntimeError(f"chart response is not an image: {content_type}")
                await self.slack.upload_file(
                    channel=request.channel_id,
                    thread_ts=request.thread_ts,
                    filename=_chart_filename(chart, index, content_type),
                    title=title,
                    content=content,
                    content_type=content_type,
                )
                attached += 1
            except Exception as exc:
                LOGGER.warning(
                    "Could not attach Slack chart event_id=%s title=%s url=%s: %s",
                    request.event_id,
                    title,
                    source_url,
                    exc,
                    exc_info=True,
                )
                errors.append(str(exc))

        if errors and attached == 0:
            await self.slack.post_message(
                channel=request.channel_id,
                thread_ts=request.thread_ts,
                text=(
                    "I finished the analysis, but could not attach the chart images. "
                    "If Slack says `missing_scope`, add the bot scope `files:write` "
                    "and reinstall the app.\n\n"
                    f"```{errors[0][:1200]}```"
                ),
            )

    async def _previous_thread_messages(self, request: SlackRequest) -> list[str]:
        try:
            messages = await self.slack.thread_messages(channel=request.channel_id, thread_ts=request.thread_ts)
        except Exception as exc:
            LOGGER.info("Could not load Slack thread context: event_id=%s error=%s", request.event_id, exc)
            return []

        previous: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("ts") == request.event_ts or message.get("bot_id") or message.get("subtype"):
                continue
            if message.get("user") == self.config.bot_user_id:
                continue
            text = _string(message.get("text")).strip()
            if text:
                previous.append(_remove_bot_mention(text, self.config.bot_user_id).strip())
        return [message for message in previous if message]

    async def _start_analysis(
        self,
        runtime: NotebookRuntime,
        request: SlackRequest,
        previous_messages: list[str],
    ) -> dict[str, Any]:
        discussion_id = f"slack:{request.team_id}:{request.channel_id}:{request.thread_ts}"
        created_at = datetime.now(UTC).isoformat()
        return await notebook_analysis._call_notebook(
            runtime,
            "/api/notion-analysis/start",
            self.config.org_id,
            self.config.user_id,
            {
                "method": "POST",
                "json": {
                    "discussionId": discussion_id,
                    "sourceUrl": request.source_url,
                    "requester": [request.user_id],
                    "headline": notebook_analysis._headline_from_prompt(request.text),
                    "prompt": request.text,
                    "previousMessages": previous_messages,
                    "createdAt": created_at,
                },
            },
        )


async def run_worker(config: SlackPoCConfig) -> None:
    _apply_local_runtime_defaults()
    await init_db()
    slack = SlackApiClient(config.bot_token, config.app_token)
    try:
        auth = await slack.auth_test()
        bot_user_id = config.bot_user_id or _string(auth.get("user_id"))
        if not bot_user_id:
            raise SlackApiError("Slack auth.test did not return bot user_id; set SLACK_BOT_USER_ID")
        config = SlackPoCConfig(
            bot_token=config.bot_token,
            app_token=config.app_token,
            signing_secret=config.signing_secret,
            bot_user_id=bot_user_id,
            org_id=config.org_id,
            user_id=config.user_id,
            allowed_channel_ids=config.allowed_channel_ids,
            ack_text=config.ack_text,
        )
        worker = SlackPoCWorker(config, slack, get_session_factory())
        stop_event = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop_event.set)
        await _socket_loop(slack, worker, stop_event)
        await worker.drain()
    finally:
        await slack.aclose()
        await close_db()


async def run_http_server(config: SlackPoCConfig) -> None:
    if not config.signing_secret:
        raise RuntimeError("SLACK_SIGNING_SECRET is required for HTTP Events mode")
    _apply_local_runtime_defaults()
    app = create_http_app(config)
    host = os.getenv("SLACK_POC_HTTP_HOST") or "0.0.0.0"
    port = int(os.getenv("SLACK_POC_HTTP_PORT") or "8787")
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
        )
    )
    await server.serve()


def create_http_app(config: SlackPoCConfig, slack: SlackApiClient | None = None) -> FastAPI:
    if not config.signing_secret:
        raise RuntimeError("SLACK_SIGNING_SECRET is required for HTTP Events mode")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        worker = app.state.worker
        if worker is not None:
            await worker.drain()
        await app.state.slack.aclose()
        await close_db()

    app = FastAPI(title="SignalPilot Slack PoC", lifespan=lifespan)
    app.state.slack = slack or SlackApiClient(config.bot_token, config.app_token)
    app.state.worker = None
    app.state.worker_lock = asyncio.Lock()

    async def ensure_worker() -> SlackPoCWorker:
        if app.state.worker is not None:
            return app.state.worker
        async with app.state.worker_lock:
            if app.state.worker is None:
                await init_db()
                auth = await app.state.slack.auth_test()
                bot_user_id = config.bot_user_id or _string(auth.get("user_id"))
                if not bot_user_id:
                    raise SlackApiError("Slack auth.test did not return bot user_id; set SLACK_BOT_USER_ID")
                resolved_config = SlackPoCConfig(
                    bot_token=config.bot_token,
                    app_token=config.app_token,
                    signing_secret=config.signing_secret,
                    bot_user_id=bot_user_id,
                    org_id=config.org_id,
                    user_id=config.user_id,
                    allowed_channel_ids=config.allowed_channel_ids,
                    ack_text=config.ack_text,
                )
                app.state.worker = SlackPoCWorker(resolved_config, app.state.slack, get_session_factory())
        return app.state.worker

    async def dispatch(payload: dict[str, Any]) -> None:
        try:
            worker = await ensure_worker()
            await worker.handle_events_api_payload(payload)
        except Exception as exc:
            LOGGER.warning("Slack HTTP event dispatch failed: %s", exc, exc_info=True)

    @app.post("/slack/events")
    async def slack_events(request: Request):
        raw_body = await request.body()
        _verify_slack_signature(
            raw_body,
            timestamp=request.headers.get("x-slack-request-timestamp"),
            signature=request.headers.get("x-slack-signature"),
            signing_secret=config.signing_secret or "",
        )
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid Slack JSON body") from exc

        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge")
            if not isinstance(challenge, str):
                raise HTTPException(status_code=400, detail="Missing Slack challenge")
            return PlainTextResponse(challenge)

        if payload.get("type") == "event_callback":
            asyncio.create_task(dispatch(payload))
            return JSONResponse({"ok": True})

        return JSONResponse({"ok": True, "ignored": True})

    return app


def _verify_slack_signature(
    raw_body: bytes,
    *,
    timestamp: str | None,
    signature: str | None,
    signing_secret: str,
) -> None:
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature")
    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp") from exc
    if abs(time.time() - request_time) > 60 * 5:
        raise HTTPException(status_code=401, detail="Stale Slack timestamp")
    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    expected = "v0=" + hmac.new(signing_secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


async def _socket_loop(slack: SlackApiClient, worker: SlackPoCWorker, stop_event: asyncio.Event) -> None:
    reconnect_delay = 1.0
    while not stop_event.is_set():
        try:
            socket_url = await slack.socket_url()
            LOGGER.info("Connected Slack Socket Mode URL")
            async with websockets.connect(socket_url, ping_interval=20, ping_timeout=20) as ws:
                reconnect_delay = 1.0
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    except TimeoutError:
                        continue
                    await _handle_socket_message(raw, ws, worker)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("Slack Socket Mode connection error: %s", exc, exc_info=True)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


async def _handle_socket_message(raw: str | bytes, ws: Any, worker: SlackPoCWorker) -> None:
    envelope = json.loads(raw)
    envelope_id = envelope.get("envelope_id")
    if envelope_id:
        await ws.send(json.dumps({"envelope_id": envelope_id}))

    envelope_type = envelope.get("type")
    if envelope_type == "hello":
        LOGGER.info("Slack Socket Mode hello received")
        return
    if envelope_type == "disconnect":
        raise SlackApiError(f"Slack requested Socket Mode disconnect: {envelope.get('reason')}")
    if envelope_type != "events_api":
        LOGGER.info("Ignoring Slack Socket Mode envelope type=%s", envelope_type)
        return

    payload = envelope.get("payload")
    if isinstance(payload, dict):
        await worker.handle_events_api_payload(payload)


def load_config_from_env() -> SlackPoCConfig:
    _load_local_env()
    bot_token = _required_env("SLACK_BOT_TOKEN")
    app_token = _required_env("SLACK_APP_TOKEN")
    return SlackPoCConfig(
        bot_token=bot_token,
        app_token=app_token,
        signing_secret=os.getenv("SLACK_SIGNING_SECRET") or None,
        bot_user_id=os.getenv("SLACK_BOT_USER_ID") or None,
        org_id=os.getenv("SLACK_POC_ORG_ID") or os.getenv("SIGNALPILOT_SLACK_ORG_ID") or "slack-poc",
        user_id=os.getenv("SLACK_POC_USER_ID") or "slack-poc-worker",
        allowed_channel_ids=frozenset(_csv_env("SLACK_ALLOWED_CHANNEL_IDS") or _csv_env("SLACK_TEST_CHANNEL_ID")),
        ack_text=os.getenv("SLACK_POC_ACK_TEXT") or "I'm on it and will post the answer back here soon.",
    )


def _apply_local_runtime_defaults() -> None:
    os.environ.setdefault("SP_DEPLOYMENT_MODE", "local")
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://signalpilot:changeme_dev_only@localhost:5601/signalpilot")
    os.environ.setdefault("SP_NOTEBOOK_DIRECT_URL", "http://localhost:2718")
    os.environ.setdefault("SIGNALPILOT_NOTEBOOK_PUBLIC_URL", "http://localhost:3200/notebook")
    os.environ.setdefault("SP_WEB_URL", "http://localhost:3200")
    os.environ.setdefault("SP_INTERNAL_JWT_SECRET", "signalpilot-slack-poc-local-secret")


def _load_local_env() -> None:
    seen: set[Path] = set()
    for directory in (Path.cwd(), *Path.cwd().parents):
        for name in (".env", ".slack.local.env"):
            path = directory / name
            if path not in seen and path.exists():
                load_dotenv(path, override=False)
                seen.add(path)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required. Add it to .slack.local.env or export it before starting the worker.")
    return value


def _csv_env(name: str) -> list[str]:
    return [part.strip() for part in (os.getenv(name) or "").split(",") if part.strip()]


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _first_authorization_team_id(payload: dict[str, Any]) -> str:
    authorizations = payload.get("authorizations")
    if not isinstance(authorizations, list) or not authorizations:
        return ""
    first = authorizations[0]
    if not isinstance(first, dict):
        return ""
    return _string(first.get("team_id"))


def _remove_bot_mention(text: str, bot_user_id: str | None) -> str:
    if bot_user_id:
        text = re.sub(rf"<@{re.escape(bot_user_id)}>\s*", "", text)
    return re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()


def _clip_text(text: str) -> str:
    if len(text) <= SLACK_TEXT_LIMIT:
        return text
    return text[: SLACK_TEXT_LIMIT - 20].rstrip() + "\n\n... truncated"


def _status_charts(status: dict[str, Any]) -> list[dict[str, Any]]:
    charts = status.get("notionCharts", status.get("notion_charts", []))
    return [chart for chart in charts if isinstance(chart, dict)] if isinstance(charts, list) else []


def _chart_value(chart: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = chart.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _chart_filename_extension(content_type: str) -> str:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized == "image/jpeg":
        return "jpg"
    if normalized == "image/svg+xml":
        return "svg"
    if normalized == "image/gif":
        return "gif"
    if normalized == "image/webp":
        return "webp"
    return "png"


def _chart_filename(chart: dict[str, Any], index: int, content_type: str) -> str:
    explicit = _chart_value(chart, "fileName", "file_name")
    if explicit:
        return explicit
    title = _chart_value(chart, "title") or f"chart-{index + 1}"
    stem = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
    return f"{stem or f'chart-{index + 1}'}.{_chart_filename_extension(content_type)}"


def _slack_link(url: str, label: str) -> str:
    return f"<{url.replace('>', '%3E')}|{label}>"


def _to_slack_mrkdwn(text: str) -> str:
    text = re.sub(r"\*\*([^*\n]+?)\*\*", r"*\1*", text)
    text = re.sub(r"__([^_\n]+?)__", r"*\1*", text)
    return re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)


def _final_slack_text(status: dict[str, Any], trail_url: str | None) -> str:
    if status.get("status") != "Done" or status.get("error"):
        return _failure_slack_text(str(status.get("error") or "SignalPilot analysis failed."), trail_url)

    raw_answer = (
        _string(status.get("slackMessage")).strip()
        or _string(status.get("notionComment")).strip()
        or _string(status.get("finalAnswer")).strip()
        or _string(status.get("summary")).strip()
        or "I finished the analysis, but there was no written answer in the result."
    )
    answer = _to_slack_mrkdwn(notebook_analysis._compact_bullet_answer(raw_answer) or raw_answer)
    parts = ["*SignalPilot analysis complete*", answer]
    confidence = status.get("confidenceScore", status.get("confidence_score"))
    if confidence is not None:
        parts.append(f"*Confidence:* {confidence}")
    if trail_url:
        parts.append(f"*Notebook trail:* {_slack_link(trail_url, 'Open authenticated notebook')}")
    return _clip_text("\n\n".join(parts))


def _failure_slack_text(error: str, trail_url: str | None) -> str:
    text = f"I could not complete the analysis.\n\n```{error[:3000]}```"
    if trail_url:
        text += f"\n\nNotebook trail: {_slack_link(trail_url, 'Open notebook')}"
    return _clip_text(text)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config_from_env()
    mode = (os.getenv("SLACK_DELIVERY_MODE") or "socket").lower()
    if mode == "http":
        asyncio.run(run_http_server(config))
    else:
        asyncio.run(run_worker(config))


if __name__ == "__main__":
    main()
