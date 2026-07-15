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
from dataclasses import dataclass, field
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

from gateway.analysis_delivery import (
    AnalysisPreflightKind,
    SlackTraceProgressReporter,
    classify_analysis_request,
    delivery_api_key_for_org,
    delivery_result_to_status,
    load_delivery_packet,
    load_delivery_packet_from_events,
    render_delivery,
    render_slack_final_message,
)
from gateway.analysis_delivery.design_system import theme_token_map
from gateway.db.engine import close_db, get_session_factory, init_db
from gateway.notebooks.session_service import NotebookRuntime, ensure_analysis_notebook_session
from gateway.notion import analysis as notebook_analysis
from gateway.slack_poc.progress import (
    COMPLETING_PROGRESS_TEXT,
    INITIAL_PROGRESS_TEXT,
)
from gateway.store import slack as slack_store
from gateway.store.org_secrets import resolve_anthropic_key
from gateway.string_utils import string_value as _string

LOGGER = logging.getLogger(__name__)
SLACK_API_BASE = "https://slack.com/api"
SLACK_TEXT_LIMIT = 35000
SLACK_CHART_LIMIT = 3
SLACK_ACK_REACTION = "eyes"
SLACK_DONE_REACTION = "white_check_mark"
SLACK_ERROR_REACTION = "x"
SLACK_EVENT_DEDUPE_MAX_SIZE = 10_000
SLACK_EVENT_DEDUPE_TTL_SECONDS = 6 * 60 * 60
SLACK_POC_HTTP_DEFAULT_HOST = "127.0.0.1"
_PLACEHOLDER_CHART_TITLE_RE = re.compile(
    r"(?:notebook\s+)?(?:chart|image|figure|visualization)(?:\s+\d+)?",
    flags=re.I,
)
_DEFAULT_WEB_URL = "https://app.signalpilot.ai"
_MISSING_ANTHROPIC_KEY_TEMPLATE = (
    "SignalPilot needs an Anthropic API key. "
    "Ask your admin to add it on the integrations page: {url}"
)


class SlackApiError(RuntimeError):
    """Raised when Slack Web API returns ok=false or a non-2xx response."""


class _EventDeduper:
    def __init__(
        self,
        *,
        max_size: int = SLACK_EVENT_DEDUPE_MAX_SIZE,
        ttl_seconds: float = SLACK_EVENT_DEDUPE_TTL_SECONDS,
    ) -> None:
        self.max_size = max(1, int(max_size))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._seen: dict[str, float] = {}

    def add(self, event_id: str, *, now: float | None = None) -> bool:
        if not event_id:
            return True
        current = time.monotonic() if now is None else now
        self._prune(current)
        if event_id in self._seen:
            self._seen[event_id] = current
            return False
        self._seen[event_id] = current
        self._prune_to_size()
        return True

    def __len__(self) -> int:
        return len(self._seen)

    def _prune(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        for event_id, seen_at in list(self._seen.items()):
            if seen_at < cutoff:
                self._seen.pop(event_id, None)

    def _prune_to_size(self) -> None:
        overflow = len(self._seen) - self.max_size
        if overflow <= 0:
            return
        oldest = sorted(self._seen, key=self._seen.get)
        for event_id in oldest[:overflow]:
            self._seen.pop(event_id, None)


def _slack_api_error(method: str, data: dict[str, Any]) -> SlackApiError:
    details = data.get("error") or data
    metadata = data.get("response_metadata")
    if isinstance(metadata, dict):
        messages = metadata.get("messages")
        if isinstance(messages, list) and messages:
            details = f"{details}: {'; '.join(str(message) for message in messages)}"
    return SlackApiError(f"Slack {method} failed: {details}")


@dataclass(frozen=True)
class SlackAnalysisDefaults:
    default_project_id: str | None = None
    default_branch: str = "main"
    analysis_branch_mode: str = "per_request"


@dataclass(frozen=True)
class SlackPoCConfig:
    bot_token: str | None = None
    app_token: str | None = None
    signing_secret: str | None = None
    bot_user_id: str | None = None
    org_id: str = "slack-poc"
    user_id: str | None = None
    default_project_id: str | None = None
    default_branch: str = "main"
    analysis_branch_mode: str = "per_request"
    channel_defaults: dict[str, SlackAnalysisDefaults] = field(default_factory=dict)
    allowed_channel_ids: frozenset[str] = frozenset()
    ack_text: str = "I'm on it and will post the answer back here soon."
    progress_enabled: bool = True
    progress_interval_seconds: float = 15.0
    progress_model_provider: str = "anthropic"
    progress_model: str | None = None
    progress_model_timeout_seconds: float = 8.0


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
    def __init__(
        self, bot_token: str, app_token: str | None = None, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self.bot_token = bot_token
        self.app_token = app_token
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=30)

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def _api(
        self, method: str, payload: dict[str, Any] | None = None, *, token: str | None = None
    ) -> dict[str, Any]:
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
        if not self.app_token:
            raise SlackApiError("Slack app-level token is required for Socket Mode")
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

    async def update_message(self, *, channel: str, ts: str, text: str) -> None:
        await self._api(
            "chat.update",
            {
                "channel": channel,
                "ts": ts,
                "text": _clip_text(text),
                "mrkdwn": True,
                "unfurl_links": False,
                "unfurl_media": False,
            },
        )

    async def add_reaction(self, *, channel: str, timestamp: str, name: str) -> None:
        try:
            await self._api("reactions.add", {"channel": channel, "timestamp": timestamp, "name": name})
        except SlackApiError as exc:
            if "already_reacted" in str(exc):
                return
            raise

    async def remove_reaction(self, *, channel: str, timestamp: str, name: str) -> None:
        try:
            await self._api("reactions.remove", {"channel": channel, "timestamp": timestamp, "name": name})
        except SlackApiError as exc:
            if "no_reaction" in str(exc):
                return
            raise

    async def upload_file(
        self,
        *,
        channel: str,
        thread_ts: str,
        filename: str,
        title: str | None,
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

        file_payload = {"id": file_id}
        if title:
            file_payload["title"] = title
        await self._api_form(
            "files.completeUploadExternal",
            {
                "files": json.dumps([file_payload]),
                "channel_id": channel,
                "thread_ts": thread_ts,
            },
        )

    async def thread_messages(self, *, channel: str, thread_ts: str) -> list[dict[str, Any]]:
        data = await self._api_form("conversations.replies", {"channel": channel, "ts": thread_ts, "limit": "20"})
        messages = data.get("messages")
        return messages if isinstance(messages, list) else []

    async def permalink(self, *, channel: str, message_ts: str) -> str:
        try:
            data = await self._api_form("chat.getPermalink", {"channel": channel, "message_ts": message_ts})
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
        self._seen_event_ids = _EventDeduper()
        self._tasks: set[asyncio.Task[None]] = set()

    async def handle_events_api_payload(self, payload: dict[str, Any]) -> None:
        request = await self._request_from_payload(payload)
        if request is None:
            return
        if not self._seen_event_ids.add(request.event_id):
            LOGGER.info("Ignoring duplicate Slack event_id=%s", request.event_id)
            return
        if await self._handle_preflight(request):
            return
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

    async def _handle_preflight(self, request: SlackRequest) -> bool:
        decision = classify_analysis_request(request.text)
        if decision.kind == AnalysisPreflightKind.ANALYZE:
            return False
        await self.slack.post_message(
            channel=request.channel_id,
            thread_ts=request.thread_ts,
            text=decision.response or "Send me a specific data question and I will run it through SignalPilot.",
        )
        return True

    async def _process_request(self, request: SlackRequest) -> None:
        trail_url: str | None = None
        route: notebook_analysis.AnalysisRoute | None = None
        progress_ts = ""
        progress_stop: asyncio.Event | None = None
        progress_task: asyncio.Task[None] | None = None
        await self._add_request_reaction(request, SLACK_ACK_REACTION)
        try:
            async with self.session_factory() as db:
                has_org_anthropic_key = bool(await resolve_anthropic_key(db, self.config.org_id))
        except Exception as exc:
            LOGGER.info("Could not load org Anthropic key for Slack analysis: %s", exc, exc_info=True)
            has_org_anthropic_key = False
        if not has_org_anthropic_key:
            await self.slack.post_message(
                channel=request.channel_id,
                thread_ts=request.thread_ts,
                text=_missing_anthropic_key_text(),
            )
            await self._mark_request_failed(request)
            return
        try:
            progress_ts = await self.slack.post_message(
                channel=request.channel_id,
                thread_ts=request.thread_ts,
                text=INITIAL_PROGRESS_TEXT,
            )
        except Exception as exc:
            LOGGER.info("Could not post Slack progress message: %s", exc, exc_info=True)
        try:
            previous_messages = await self._previous_thread_messages(request)
            async with self.session_factory() as db:
                credential_user_id = await self._analysis_user_id(db)
                discussion_id = _discussion_id(request)
                request_id = notebook_analysis._analysis_request_id("slack", discussion_id)
                defaults = self._analysis_defaults(request)
                route = await notebook_analysis.resolve_analysis_route_for_defaults(
                    db,
                    org_id=self.config.org_id,
                    source="slack",
                    request_id=request_id,
                    headline=notebook_analysis._headline_from_prompt(request.text),
                    default_project_id=defaults.default_project_id,
                    default_branch=defaults.default_branch,
                    analysis_branch_mode=defaults.analysis_branch_mode,
                )
                analysis_user_id = credential_user_id or route.analysis_user_id
                runtime = await ensure_analysis_notebook_session(
                    db,
                    org_id=self.config.org_id,
                    source=route.source,
                    request_id=route.request_id,
                    project_id=route.project_id,
                    branch=route.branch,
                    credential_user_id=credential_user_id,
                )
                await notebook_analysis.upsert_analysis_trail_seed(
                    db,
                    org_id=self.config.org_id,
                    route=route,
                    runtime=runtime,
                    headline=notebook_analysis._headline_from_prompt(request.text),
                    source_url=request.source_url,
                    source_thread_id=discussion_id,
                    source_request_id=request.event_id,
                    analysis_user_id=analysis_user_id,
                )

            trace_thread_id = f"session-{route.request_id}"
            start = await self._start_analysis(runtime, request, previous_messages, analysis_user_id, route)
            trail_url = notebook_analysis._public_signalpilot_url(_string(start.get("trailUrl")), runtime)
            async with self.session_factory() as db:
                await notebook_analysis.upsert_analysis_trail_from_status(
                    db,
                    org_id=self.config.org_id,
                    route=route,
                    runtime=runtime,
                    status=start,
                    source_url=request.source_url,
                    source_thread_id=discussion_id,
                    source_request_id=request.event_id,
                    analysis_user_id=analysis_user_id,
                )
            if self.config.progress_enabled and progress_ts:
                progress_stop = asyncio.Event()
                progress_task = asyncio.create_task(
                    self._run_progress_reporter(
                        stop_event=progress_stop,
                        thread_id=trace_thread_id,
                        source_prompt=request.text,
                        channel_id=request.channel_id,
                        message_ts=progress_ts,
                        user_id=analysis_user_id,
                    ),
                    name=f"slack-progress-{request.event_id}",
                )
            poll_task = asyncio.create_task(
                notebook_analysis._poll_analysis(
                    _string(start["requestId"]),
                    runtime,
                    self.config.org_id,
                    analysis_user_id,
                    route,
                ),
                name=f"slack-analysis-poll-{request.event_id}",
            )
            try:
                status = await poll_task
            finally:
                await self._stop_progress_reporter(progress_stop, progress_task)
            await self._update_progress_message(
                channel_id=request.channel_id,
                message_ts=progress_ts,
                text=COMPLETING_PROGRESS_TEXT,
            )
            async with self.session_factory() as db:
                await notebook_analysis.update_analysis_trail_from_status(
                    db,
                    org_id=self.config.org_id,
                    route=route,
                    status=status,
                )
            public_status = notebook_analysis._with_public_chart_urls(status, runtime)
            delivery_api_key = ""
            try:
                async with self.session_factory() as db:
                    delivery_api_key = await delivery_api_key_for_org(
                        db,
                        org_id=self.config.org_id,
                    )
                    packet = await load_delivery_packet(
                        db,
                        org_id=self.config.org_id,
                        user_id=analysis_user_id,
                        thread_id=trace_thread_id,
                        user_request=request.text,
                        status_payload=public_status,
                        trail_url=trail_url or "",
                    )
            except Exception as exc:
                LOGGER.info("Could not load Slack delivery trace; using status fallback: %s", exc, exc_info=True)
                packet = load_delivery_packet_from_events(
                    [],
                    user_request=request.text,
                    status_payload=public_status,
                    trail_url=trail_url or "",
                    thread_status="done",
                )
            delivery = await render_delivery(packet, api_key=delivery_api_key)
            slack_status = delivery_result_to_status(delivery, packet, base_status=public_status)
            await self._update_or_post_result_message(
                channel=request.channel_id,
                thread_ts=request.thread_ts,
                message_ts=progress_ts,
                text=render_slack_final_message(packet, delivery, trail_url=trail_url),
            )
            await self._mark_request_done(request)
            await self._post_chart_attachments(request, slack_status, runtime)
        except Exception as exc:
            LOGGER.warning("Slack PoC request failed: event_id=%s error=%s", request.event_id, exc, exc_info=True)
            if route is not None:
                try:
                    async with self.session_factory() as db:
                        from gateway.models.analysis_trails import AnalysisTrailUpdate
                        from gateway.store import analysis_trails

                        await analysis_trails.update_trail(
                            db,
                            org_id=self.config.org_id,
                            source=route.source,
                            request_id=route.request_id,
                            update=AnalysisTrailUpdate(status="failed"),
                        )
                except Exception:
                    LOGGER.debug("Could not mark Slack analysis trail failed", exc_info=True)
            await self._update_or_post_result_message(
                channel=request.channel_id,
                thread_ts=request.thread_ts,
                message_ts=progress_ts,
                text=_failure_slack_text(str(exc), trail_url),
            )
            await self._mark_request_failed(request)
        finally:
            await self._stop_progress_reporter(progress_stop, progress_task)
            await self._remove_request_reaction(request, SLACK_ACK_REACTION)

    async def _add_request_reaction(self, request: SlackRequest, name: str) -> None:
        if not request.event_ts:
            return
        try:
            await self.slack.add_reaction(channel=request.channel_id, timestamp=request.event_ts, name=name)
        except Exception as exc:
            LOGGER.info("Could not add Slack reaction=%s event_id=%s: %s", name, request.event_id, exc, exc_info=True)

    async def _remove_request_reaction(self, request: SlackRequest, name: str) -> None:
        if not request.event_ts:
            return
        try:
            await self.slack.remove_reaction(channel=request.channel_id, timestamp=request.event_ts, name=name)
        except Exception as exc:
            LOGGER.info(
                "Could not remove Slack reaction=%s event_id=%s: %s", name, request.event_id, exc, exc_info=True
            )

    async def _mark_request_done(self, request: SlackRequest) -> None:
        await self._add_request_reaction(request, SLACK_DONE_REACTION)
        await self._remove_request_reaction(request, SLACK_ACK_REACTION)
        await self._remove_request_reaction(request, SLACK_ERROR_REACTION)

    async def _mark_request_failed(self, request: SlackRequest) -> None:
        await self._add_request_reaction(request, SLACK_ERROR_REACTION)
        await self._remove_request_reaction(request, SLACK_ACK_REACTION)
        await self._remove_request_reaction(request, SLACK_DONE_REACTION)

    async def _update_or_post_result_message(
        self,
        *,
        channel: str,
        thread_ts: str,
        message_ts: str,
        text: str,
    ) -> None:
        if message_ts:
            try:
                await self.slack.update_message(channel=channel, ts=message_ts, text=text)
                return
            except Exception as exc:
                LOGGER.info("Could not update Slack result message: %s", exc, exc_info=True)
        await self.slack.post_message(channel=channel, thread_ts=thread_ts, text=text)

    async def _run_progress_reporter(
        self,
        *,
        stop_event: asyncio.Event,
        thread_id: str,
        source_prompt: str,
        channel_id: str,
        message_ts: str,
        user_id: str,
    ) -> None:
        reporter = SlackTraceProgressReporter(
            slack=self.slack,
            session_factory=self.session_factory,
            org_id=self.config.org_id,
            user_id=user_id,
            thread_id=thread_id,
            source_prompt=source_prompt,
            channel_id=channel_id,
            message_ts=message_ts,
            interval_seconds=self.config.progress_interval_seconds,
        )
        await reporter.run(stop_event)

    async def _stop_progress_reporter(
        self,
        stop_event: asyncio.Event | None,
        task: asyncio.Task[None] | None,
    ) -> None:
        if stop_event is None or task is None:
            return
        stop_event.set()
        try:
            await asyncio.wait_for(task, timeout=2)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except Exception as exc:
            LOGGER.info("Slack progress reporter stopped with error: %s", exc, exc_info=True)

    async def _update_progress_message(self, *, channel_id: str, message_ts: str, text: str) -> None:
        if not self.config.progress_enabled or not message_ts:
            return
        try:
            await self.slack.update_message(channel=channel_id, ts=message_ts, text=text)
        except Exception as exc:
            LOGGER.info("Could not update Slack progress message: %s", exc, exc_info=True)

    async def _analysis_user_id(self, db: AsyncSession) -> str | None:
        del db
        if self.config.user_id:
            return self.config.user_id
        return None

    def _analysis_defaults(self, request: SlackRequest) -> SlackAnalysisDefaults:
        defaults = self.config.channel_defaults.get(request.channel_id)
        if defaults is None:
            defaults = SlackAnalysisDefaults(
                default_project_id=self.config.default_project_id,
                default_branch=self.config.default_branch,
                analysis_branch_mode=self.config.analysis_branch_mode,
            )
        if not defaults.default_project_id:
            raise RuntimeError(
                "SignalPilot needs a default dbt project before it can run Slack analysis. "
                "Configure a default project for this Slack workspace in integrations."
            )
        return defaults

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
            title = _chart_attachment_title(chart)
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
                    title or _chart_value(chart, "title") or f"chart-{index + 1}",
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
        user_id: str,
        route: notebook_analysis.AnalysisRoute,
    ) -> dict[str, Any]:
        discussion_id = _discussion_id(request)
        created_at = datetime.now(UTC).isoformat()
        async with self.session_factory() as db:
            theme = await notebook_analysis._org_deliverable_theme(db, self.config.org_id)
        return await notebook_analysis._call_notebook(
            runtime,
            "/api/notion-analysis/start",
            self.config.org_id,
            user_id,
            {
                "method": "POST",
                "json": {
                    "source": "slack",
                    "discussionId": discussion_id,
                    "sourceUrl": request.source_url,
                    "requester": [request.user_id],
                    "headline": notebook_analysis._headline_from_prompt(request.text),
                    "prompt": request.text,
                    "previousMessages": previous_messages,
                    "createdAt": created_at,
                    "theme": theme_token_map(theme),
                },
                "headers": {
                    "X-Gateway-Project-Id": route.project_id,
                    "X-Gateway-Branch-Id": route.branch,
                },
            },
        )


async def run_worker(config: SlackPoCConfig) -> None:
    if not config.bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN is required for Slack Socket Mode")
    if not config.app_token:
        raise RuntimeError("SLACK_APP_TOKEN is required for Slack Socket Mode")
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
            default_project_id=config.default_project_id,
            default_branch=config.default_branch,
            analysis_branch_mode=config.analysis_branch_mode,
            channel_defaults=config.channel_defaults,
            allowed_channel_ids=config.allowed_channel_ids,
            ack_text=config.ack_text,
            progress_enabled=config.progress_enabled,
            progress_interval_seconds=config.progress_interval_seconds,
            progress_model_provider=config.progress_model_provider,
            progress_model=config.progress_model,
            progress_model_timeout_seconds=config.progress_model_timeout_seconds,
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
    host = os.getenv("SLACK_POC_HTTP_HOST") or SLACK_POC_HTTP_DEFAULT_HOST
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


def register_http_routes(
    app: FastAPI,
    config: SlackPoCConfig,
    *,
    slack: SlackApiClient | None = None,
    initialize_db_on_first_request: bool = False,
) -> None:
    if not config.signing_secret:
        raise RuntimeError("SLACK_SIGNING_SECRET is required for HTTP Events mode")

    if slack is not None:
        app.state.slack_poc_client = slack
    elif config.bot_token:
        app.state.slack_poc_client = SlackApiClient(config.bot_token, config.app_token)
    else:
        app.state.slack_poc_client = None
    app.state.slack_poc_worker = None
    app.state.slack_poc_worker_lock = asyncio.Lock()
    app.state.slack_poc_selfserve_event_ids = _EventDeduper()

    async def ensure_worker() -> SlackPoCWorker:
        if not config.bot_token:
            raise SlackApiError("SLACK_BOT_TOKEN is required for legacy Slack HTTP worker mode")
        if app.state.slack_poc_worker is not None:
            return app.state.slack_poc_worker
        async with app.state.slack_poc_worker_lock:
            if app.state.slack_poc_worker is None:
                if initialize_db_on_first_request:
                    await init_db()
                if app.state.slack_poc_client is None:
                    app.state.slack_poc_client = SlackApiClient(config.bot_token, config.app_token)
                auth = await app.state.slack_poc_client.auth_test()
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
                    default_project_id=config.default_project_id,
                    default_branch=config.default_branch,
                    analysis_branch_mode=config.analysis_branch_mode,
                    channel_defaults=config.channel_defaults,
                    allowed_channel_ids=config.allowed_channel_ids,
                    ack_text=config.ack_text,
                    progress_enabled=config.progress_enabled,
                    progress_interval_seconds=config.progress_interval_seconds,
                    progress_model_provider=config.progress_model_provider,
                    progress_model=config.progress_model,
                    progress_model_timeout_seconds=config.progress_model_timeout_seconds,
                )
                app.state.slack_poc_worker = SlackPoCWorker(
                    resolved_config,
                    app.state.slack_poc_client,
                    get_session_factory(),
                )
        return app.state.slack_poc_worker

    async def dispatch(payload: dict[str, Any]) -> None:
        try:
            if config.bot_token:
                worker = await ensure_worker()
                await worker.handle_events_api_payload(payload)
                return

            event_id = _string(payload.get("event_id"))
            if event_id:
                seen: _EventDeduper = app.state.slack_poc_selfserve_event_ids
                if not seen.add(event_id):
                    LOGGER.info("Ignoring duplicate Slack event_id=%s", event_id)
                    return
            if initialize_db_on_first_request:
                await init_db()
            await _dispatch_self_serve_payload(payload, config)
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


def create_http_app(config: SlackPoCConfig, slack: SlackApiClient | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        worker = app.state.slack_poc_worker
        if worker is not None:
            await worker.drain()
        client = app.state.slack_poc_client
        if client is not None:
            await client.aclose()
        await close_db()

    app = FastAPI(title="SignalPilot Slack PoC", lifespan=lifespan)
    register_http_routes(app, config, slack=slack, initialize_db_on_first_request=True)
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


async def _dispatch_self_serve_payload(payload: dict[str, Any], base_config: SlackPoCConfig) -> None:
    team_id = _payload_team_id(payload)
    if not team_id:
        LOGGER.info("Ignoring Slack event without team_id")
        return

    factory = get_session_factory()
    async with factory() as db:
        records = await slack_store.list_active_installation_records_for_team(db, team_id)

    if not records:
        LOGGER.info("Ignoring Slack event for team_id=%s without active Slack installation", team_id)
        return
    if len(records) > 1:
        LOGGER.warning(
            "Ignoring Slack event for ambiguous team_id=%s active_installations=%s",
            team_id,
            ",".join(record[0].id for record in records),
        )
        return

    installation, install_config, bot_token = records[0]
    slack = SlackApiClient(bot_token, base_config.app_token)
    worker_config = SlackPoCConfig(
        bot_token=bot_token,
        app_token=base_config.app_token,
        signing_secret=base_config.signing_secret,
        bot_user_id=installation.bot_user_id,
        org_id=installation.org_id,
        user_id=installation.user_id,
        default_project_id=install_config.default_project_id,
        default_branch=install_config.default_branch or "main",
        analysis_branch_mode=install_config.analysis_branch_mode or "per_request",
        allowed_channel_ids=frozenset(install_config.allowed_channel_ids or []),
        ack_text=base_config.ack_text,
        progress_enabled=base_config.progress_enabled,
        progress_interval_seconds=base_config.progress_interval_seconds,
        progress_model_provider=base_config.progress_model_provider,
        progress_model=base_config.progress_model,
        progress_model_timeout_seconds=base_config.progress_model_timeout_seconds,
    )
    worker = SlackPoCWorker(worker_config, slack, factory)
    try:
        await worker.handle_events_api_payload(payload)
        await worker.drain()
    finally:
        await slack.aclose()


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
        user_id=os.getenv("SLACK_POC_USER_ID") or os.getenv("SIGNALPILOT_SLACK_USER_ID") or None,
        default_project_id=os.getenv("SLACK_POC_DEFAULT_PROJECT_ID")
        or os.getenv("SIGNALPILOT_SLACK_DEFAULT_PROJECT_ID")
        or None,
        default_branch=os.getenv("SLACK_POC_DEFAULT_BRANCH") or "main",
        analysis_branch_mode=os.getenv("SLACK_POC_ANALYSIS_BRANCH_MODE") or "per_request",
        channel_defaults=_channel_defaults_from_env(),
        allowed_channel_ids=frozenset(_csv_env("SLACK_ALLOWED_CHANNEL_IDS") or _csv_env("SLACK_TEST_CHANNEL_ID")),
        ack_text=os.getenv("SLACK_POC_ACK_TEXT") or "I'm on it and will post the answer back here soon.",
        progress_enabled=_bool_env("SLACK_PROGRESS_ENABLED", True),
        progress_interval_seconds=_float_env("SLACK_PROGRESS_INTERVAL_SECONDS", 15.0),
        progress_model_provider=os.getenv("SLACK_PROGRESS_MODEL_PROVIDER") or "anthropic",
        progress_model=os.getenv("SLACK_PROGRESS_MODEL") or None,
        progress_model_timeout_seconds=_float_env("SLACK_PROGRESS_MODEL_TIMEOUT_SECONDS", 8.0),
    )


def load_http_config_from_env() -> SlackPoCConfig:
    _load_local_env()
    return SlackPoCConfig(
        bot_token=os.getenv("SLACK_BOT_TOKEN") or None,
        app_token=os.getenv("SLACK_APP_TOKEN") or None,
        signing_secret=_required_env("SLACK_SIGNING_SECRET"),
        bot_user_id=os.getenv("SLACK_BOT_USER_ID") or None,
        org_id=os.getenv("SLACK_POC_ORG_ID") or os.getenv("SIGNALPILOT_SLACK_ORG_ID") or "slack-poc",
        user_id=os.getenv("SLACK_POC_USER_ID") or os.getenv("SIGNALPILOT_SLACK_USER_ID") or None,
        default_project_id=os.getenv("SLACK_POC_DEFAULT_PROJECT_ID")
        or os.getenv("SIGNALPILOT_SLACK_DEFAULT_PROJECT_ID")
        or None,
        default_branch=os.getenv("SLACK_POC_DEFAULT_BRANCH") or "main",
        analysis_branch_mode=os.getenv("SLACK_POC_ANALYSIS_BRANCH_MODE") or "per_request",
        channel_defaults=_channel_defaults_from_env(),
        allowed_channel_ids=frozenset(_csv_env("SLACK_ALLOWED_CHANNEL_IDS") or _csv_env("SLACK_TEST_CHANNEL_ID")),
        ack_text=os.getenv("SLACK_POC_ACK_TEXT") or "I'm on it and will post the answer back here soon.",
        progress_enabled=_bool_env("SLACK_PROGRESS_ENABLED", True),
        progress_interval_seconds=_float_env("SLACK_PROGRESS_INTERVAL_SECONDS", 15.0),
        progress_model_provider=os.getenv("SLACK_PROGRESS_MODEL_PROVIDER") or "anthropic",
        progress_model=os.getenv("SLACK_PROGRESS_MODEL") or None,
        progress_model_timeout_seconds=_float_env("SLACK_PROGRESS_MODEL_TIMEOUT_SECONDS", 8.0),
    )


def _apply_local_runtime_defaults() -> None:
    if os.getenv("SP_DEPLOYMENT_MODE", "").lower() == "cloud":
        return
    os.environ.setdefault("SP_DEPLOYMENT_MODE", "local")
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://signalpilot:changeme_dev_only@localhost:5601/signalpilot"
    )
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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def _channel_defaults_from_env() -> dict[str, SlackAnalysisDefaults]:
    raw = os.getenv("SLACK_POC_CHANNEL_DEFAULTS") or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("SLACK_POC_CHANNEL_DEFAULTS must be JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("SLACK_POC_CHANNEL_DEFAULTS must be a JSON object")

    defaults: dict[str, SlackAnalysisDefaults] = {}
    for channel_id, value in data.items():
        if not isinstance(channel_id, str) or not isinstance(value, dict):
            continue
        defaults[channel_id] = SlackAnalysisDefaults(
            default_project_id=_string(value.get("default_project_id") or value.get("project_id")) or None,
            default_branch=_string(value.get("default_branch")) or "main",
            analysis_branch_mode=_string(value.get("analysis_branch_mode")) or "per_request",
        )
    return defaults


def _first_authorization_team_id(payload: dict[str, Any]) -> str:
    authorizations = payload.get("authorizations")
    if not isinstance(authorizations, list) or not authorizations:
        return ""
    first = authorizations[0]
    if not isinstance(first, dict):
        return ""
    return _string(first.get("team_id"))


def _payload_team_id(payload: dict[str, Any]) -> str:
    event = payload.get("event")
    event_team = event.get("team") if isinstance(event, dict) else None
    return _string(payload.get("team_id") or event_team or _first_authorization_team_id(payload))


def _remove_bot_mention(text: str, bot_user_id: str | None) -> str:
    if bot_user_id:
        text = re.sub(rf"<@{re.escape(bot_user_id)}>\s*", "", text)
    return re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()


def _integrations_url() -> str:
    web_url = os.getenv("SIGNALPILOT_WEB_URL") or os.getenv("SP_WEB_URL") or _DEFAULT_WEB_URL
    return f"{web_url.rstrip('/')}/integrations" if web_url else "/integrations"


def _missing_anthropic_key_text() -> str:
    return _MISSING_ANTHROPIC_KEY_TEMPLATE.format(url=_integrations_url())


def _clip_text(text: str) -> str:
    if len(text) <= SLACK_TEXT_LIMIT:
        return text
    return text[: SLACK_TEXT_LIMIT - 20].rstrip() + "\n\n... truncated"


def _status_charts(status: dict[str, Any]) -> list[dict[str, Any]]:
    charts = status.get("notionCharts", status.get("notion_charts", []))
    return [chart for chart in charts if isinstance(chart, dict)] if isinstance(charts, list) else []


def _discussion_id(request: SlackRequest) -> str:
    return f"slack:{request.team_id}:{request.channel_id}:{request.thread_ts}"


def _chart_value(chart: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = chart.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_placeholder_chart_title(value: str) -> bool:
    return bool(_PLACEHOLDER_CHART_TITLE_RE.fullmatch(value.strip()))


def _chart_attachment_title(chart: dict[str, Any]) -> str | None:
    for key in ("title", "caption", "altText", "alt_text"):
        value = _chart_value(chart, key)
        if value and not _is_placeholder_chart_title(value):
            return value
    return None


def _is_placeholder_chart_filename(value: str) -> bool:
    stem = Path(value).stem.replace("-", " ").replace("_", " ").strip()
    return _is_placeholder_chart_title(stem)


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
    if explicit and not _is_placeholder_chart_filename(explicit):
        return explicit
    title = _chart_attachment_title(chart) or f"chart-{index + 1}"
    stem = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
    return f"{stem or f'chart-{index + 1}'}.{_chart_filename_extension(content_type)}"


def _failure_slack_text(error: str, trail_url: str | None) -> str:
    text = f"I could not complete the analysis.\n\n```{error[:3000]}```"
    if trail_url:
        text += f"\n\nNotebook trail: <{trail_url.replace('>', '%3E')}|Open notebook>"
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
