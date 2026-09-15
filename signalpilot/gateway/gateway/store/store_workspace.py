"""Reports, workspace projects, uploads, chat, traces, agent runs and evals."""

from __future__ import annotations


class WorkspaceStoreMixin:
    """Reports, workspace projects, uploads, chat, traces, agent runs and evals."""

    # Reports (rendered HTML).

    async def insert_report(self, payload, *, user_id: str | None, agent: str | None = None):
        from . import reports as reports_mod

        oid = self._require_org_id()
        return await reports_mod.insert_report(self.session, org_id=oid, payload=payload, user_id=user_id, agent=agent)

    async def list_reports(self, *, scope_ref: str | None = None, limit: int = 200, offset: int = 0):
        from . import reports as reports_mod

        oid = self._require_org_id()
        return await reports_mod.list_reports(self.session, org_id=oid, scope_ref=scope_ref, limit=limit, offset=offset)

    async def get_report(self, report_id: str, *, bump_view: bool = False):
        import asyncio

        from . import reports as reports_mod

        oid = self._require_org_id()
        report = await reports_mod.get_report(self.session, org_id=oid, report_id=report_id)
        if report is None:
            return None
        if bump_view:
            asyncio.create_task(self.increment_report_view(report_id))
        return report

    async def delete_report(self, report_id: str) -> bool:
        from . import reports as reports_mod

        oid = self._require_org_id()
        return await reports_mod.delete_report(self.session, org_id=oid, report_id=report_id)

    async def update_report_html(self, report_id: str, payload):
        from . import reports as reports_mod

        oid = self._require_org_id()
        return await reports_mod.update_report_html(self.session, org_id=oid, report_id=report_id, payload=payload)

    async def increment_report_view(self, report_id: str) -> None:
        from gateway.db.engine import get_session_factory

        from . import reports as reports_mod

        oid = self._require_org_id()
        factory = get_session_factory()
        async with factory() as session:
            await reports_mod.increment_report_view(session, org_id=oid, report_id=report_id)

    # Workspace Projects.

    async def create_workspace_project(self, **kwargs):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.create_project(self.session, org_id=oid, user_id=self.user_id, **kwargs)

    async def list_workspace_projects(self, **kwargs):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.list_projects(self.session, org_id=oid, **kwargs)

    async def get_workspace_project(self, project_id: str):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.get_project(self.session, org_id=oid, project_id=project_id)

    async def update_workspace_project(self, project_id: str, updates: dict):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.update_project(self.session, org_id=oid, project_id=project_id, updates=updates)

    async def delete_workspace_project(self, project_id: str):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.delete_project(self.session, org_id=oid, project_id=project_id)

    # Upload Sessions.

    async def reserve_upload_session(
        self,
        *,
        user_id: str,
        key: str,
        size_bytes: int,
        part_lengths: list[int],
        max_open: int,
        max_bytes: int,
        ttl_s: float,
    ) -> None:
        from . import upload_sessions

        oid = self._require_org_id()
        await upload_sessions.reserve(
            self.session,
            org_id=oid,
            user_id=user_id,
            key=key,
            size_bytes=size_bytes,
            part_lengths=part_lengths,
            max_open=max_open,
            max_bytes=max_bytes,
            ttl_s=ttl_s,
        )

    async def bind_upload_session(self, key: str, upload_id: str) -> None:
        from . import upload_sessions

        oid = self._require_org_id()
        await upload_sessions.bind_upload_id(self.session, org_id=oid, key=key, upload_id=upload_id)

    async def release_upload_session(self, key: str) -> None:
        from . import upload_sessions

        oid = self._require_org_id()
        await upload_sessions.release(self.session, org_id=oid, key=key)

    async def get_upload_session(self, *, user_id: str, key: str, upload_id: str):
        from . import upload_sessions

        oid = self._require_org_id()
        return await upload_sessions.get_owned(self.session, org_id=oid, user_id=user_id, key=key, upload_id=upload_id)

    # Chat.

    async def create_conversation(self, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.create_conversation(self.session, org_id=oid, user_id=self.user_id or "local", **kwargs)

    async def list_conversations(self, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.list_conversations(self.session, org_id=oid, user_id=self.user_id or "local", **kwargs)

    async def get_conversation(self, conversation_id: str):
        from . import chat

        oid = self._require_org_id()
        return await chat.get_conversation(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id
        )

    async def delete_conversation(self, conversation_id: str):
        from . import chat

        oid = self._require_org_id()
        return await chat.delete_conversation(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id
        )

    async def append_message(self, conversation_id: str, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.append_message(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id, **kwargs
        )

    async def list_messages(self, conversation_id: str, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.list_messages(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id, **kwargs
        )

    # Chat Traces.

    async def upsert_chat_trace_thread(self, thread):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.upsert_thread(self.session, org_id=oid, user_id=self.user_id or "local", thread=thread)

    async def clear_chat_trace_events(self, thread_id: str):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.clear_events(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id
        )

    async def append_chat_trace_event(self, thread_id: str, event):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.append_event(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id, event=event
        )

    async def list_chat_trace_threads(self, **kwargs):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.list_threads(self.session, org_id=oid, user_id=self.user_id or "local", **kwargs)

    async def get_chat_trace_thread(self, thread_id: str):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.get_thread(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id
        )

    async def get_chat_trace_events(self, thread_id: str, **kwargs):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.get_events(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id, **kwargs
        )

    # Agent Runs.

    async def create_agent_run(self, **kwargs):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.create_run(self.session, org_id=oid, user_id=self.user_id, **kwargs)

    async def list_agent_runs(self, **kwargs):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.list_runs(self.session, org_id=oid, **kwargs)

    async def get_agent_run(self, run_id: str):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.get_run(self.session, org_id=oid, run_id=run_id)

    async def update_agent_run(self, run_id: str, updates: dict):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.update_run(self.session, org_id=oid, run_id=run_id, updates=updates)

    # Branches.

    # Use the Git CLI to manage branch references.

    # Evals.

    async def get_eval_config(self) -> dict:
        from . import evals

        oid = self._require_org_id()
        return await evals.get_config(self.session, org_id=oid)

    async def save_eval_config(self, cfg: dict) -> dict:
        from . import evals

        oid = self._require_org_id()
        return await evals.save_config(self.session, org_id=oid, cfg=cfg)

    async def get_eval_run(self, run_id: str) -> dict | None:
        from . import evals

        oid = self._require_org_id()
        return await evals.get_run(self.session, org_id=oid, run_id=run_id)

    async def list_eval_runs(self, limit: int = 50) -> list[dict]:
        from . import evals

        oid = self._require_org_id()
        return await evals.list_runs(self.session, org_id=oid, limit=limit)

    async def list_live_eval_runs(self) -> list[dict]:
        from . import evals

        oid = self._require_org_id()
        return await evals.list_live_runs(self.session, org_id=oid)

    async def get_eval_tasks(self, run_id: str) -> list[dict]:
        from . import evals

        oid = self._require_org_id()
        return await evals.get_tasks(self.session, org_id=oid, run_id=run_id)

    async def eval_sandbox_index(self, limit_runs: int = 25) -> dict[str, dict]:
        from . import evals

        oid = self._require_org_id()
        return await evals.tasks_with_live_sandboxes(self.session, org_id=oid, limit_runs=limit_runs)

    async def list_eval_accuracy(self, limit: int = 500) -> list[dict]:
        from . import evals

        oid = self._require_org_id()
        return await evals.list_accuracy(self.session, org_id=oid, limit=limit)

    async def list_eval_regressions(self, limit: int = 100) -> list[dict]:
        from . import evals

        oid = self._require_org_id()
        return await evals.list_regressions(self.session, org_id=oid, limit=limit)

    async def list_eval_task_performance(self, limit_runs: int = 50) -> list[dict]:
        from . import evals

        oid = self._require_org_id()
        return await evals.list_task_performance(self.session, org_id=oid, limit_runs=limit_runs)
