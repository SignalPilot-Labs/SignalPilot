"""Target test suite for Notebook Runtime v2 (Vercel compute + S3 workspace).

THIS SUITE IS THE SPEC'S ACCEPTANCE CRITERIA, WRITTEN FIRST. Every test is
skipped with a pointer to the design section and migration gate it belongs to
(sp-local/docs/specs/notebook-vercel-s3-redesign.md and -migration.md). As
each phase lands, its tests get implemented and un-skipped — the suite going
green IS the migration finishing.

Run `pytest tests/test_notebook_workspace_v2_scaffold.py --collect-only -q`
to see the full target surface.
"""

from __future__ import annotations

import pytest


def _target(section: str, gate: str):
    pytest.skip(f"v2 target — spec {section}, migration gate {gate}: not built yet")


# ── §4.2 Workspace Files API (gate G1: S3 store + dual-write shadowing) ─────


class TestWorkspaceFilesAPI:
    def test_put_then_get_roundtrips_bytes_exactly(self):
        _target("§4.2", "G1")

    def test_get_missing_path_is_404_not_500(self):
        _target("§4.2", "G1")

    def test_delete_then_get_is_404_but_prior_revision_still_serves_it(self):
        """USER STORY: delete a file, hit an old link — the old revision's
        manifest still resolves it. Deletion is a new revision, not erasure."""
        _target("§4.1+§4.2", "G1")

    def test_list_copy_move_search_operate_within_project_only(self):
        _target("§4.2", "G1")

    def test_path_confinement_rejects_dotdot_nul_and_absolute(self):
        _target("§4.2 (path_confinement)", "G1")

    def test_batch_commit_is_atomic_all_or_nothing(self):
        _target("§4.2 files:batch", "G1")

    def test_snapshot_endpoint_serves_presigned_tarball_of_any_revision(self):
        _target("§4.2 snapshot", "G1")

    def test_revisions_endpoint_lists_manifest_history(self):
        _target("§4.2 revisions", "G1")

    def test_auth_requires_session_jwt_with_write_scope_for_mutations(self):
        _target("§4.2 auth", "G1")


# ── §4.1 Content-addressed store semantics (gate G1) ────────────────────────


class TestObjectStoreSemantics:
    def test_identical_content_across_branches_shares_one_blob(self):
        _target("§4.1 dedupe", "G1")

    def test_manifests_are_immutable_once_written(self):
        _target("§4.1", "G1")

    def test_head_cas_rejects_stale_base_revision(self):
        """Two writers race a HEAD bump — exactly one wins; the loser gets a
        CAS conflict, not a silent overwrite. Postgres is the lock."""
        _target("§4.1 CAS", "G1")

    def test_revision_numbers_are_strictly_monotonic_per_branch(self):
        _target("§4.1", "G1")

    def test_frozen_revision_pins_chat_runs_exactly(self):
        _target("§4.1 frozen_revision", "G1")


# ── §4.4 Session lease (gate G2) ────────────────────────────────────────────


class TestSessionLease:
    def test_second_writer_on_same_project_branch_is_refused(self):
        _target("§4.4", "G2")

    def test_expired_lease_is_reclaimable_after_ttl(self):
        _target("§4.4 TTL 90s", "G2")

    def test_sync_batches_renew_the_lease(self):
        _target("§4.4", "G2")

    def test_read_only_frozen_sessions_never_take_a_lease(self):
        _target("§4.4", "G2")


# ── §4.3 Sync agent (gate G2) ───────────────────────────────────────────────


class TestSyncAgent:
    def test_notebook_save_flushes_within_debounce_window(self):
        """USER STORY: save a file — it must be durable in S3 within the 2s
        debounce + one batch call, and visible to the next session."""
        _target("§4.3", "G2")

    def test_edit_then_save_roundtrip_preserves_exact_content(self):
        """USER STORY: edit an existing file, save, reopen — byte-identical,
        no CRLF/encoding mangling, mtime advances."""
        _target("§4.3", "G2")

    def test_flush_barrier_runs_before_snapshot_destroy_and_handoff(self):
        _target("§4.3 flush barriers", "G2")

    def test_crash_loses_at_most_the_debounce_window(self):
        _target("§4.3 / §7 failure modes", "G2")

    def test_conflict_replays_local_changes_then_retries_once(self):
        _target("§4.3 conflict", "G2")

    def test_spsyncignore_excludes_cache_venvs_tmp(self):
        _target("§4.3 .spsyncignore", "G2")

    def test_large_files_travel_by_presigned_put_and_commit_by_reference(self):
        _target("§4.3 >8MB path", "G2")

    def test_session_sidecars_sync_but_persistent_cache_does_not(self):
        _target("§4.3 __sp__", "G2")


# ── User interaction semantics (the jupyter-lab-like UX; gates G2–G4) ──────


class TestUserWorkflows:
    def test_save_edit_save_delete_navigate_back_full_journey(self):
        """USER STORY (end to end): create file → save → edit → save → delete
        → navigate back via an old link → recoverable from revision history,
        with a working 'restore' affordance, never a 500."""
        _target("§4 overall", "G4")

    def test_deleting_a_project_tombstones_links_instead_of_500(self):
        _target("§4.2", "G4")

    def test_rename_move_preserves_revision_lineage(self):
        _target("§4.2 files:move", "G2")

    def test_browser_refresh_mid_edit_rehydrates_unsaved_state(self):
        """USER STORY: refresh mid-edit — the __sp__ session sidecar restores
        the editor state; nothing silently lost."""
        _target("§4.3 __sp__ sidecars", "G4")

    def test_two_users_same_project_different_branches_never_interfere(self):
        _target("§4.4", "G4")

    def test_branch_switch_hydrates_the_other_branchs_snapshot(self):
        _target("§4.5", "G3")

    def test_notebook_page_loads_without_a_k8s_pod(self):
        """The point of the whole redesign: browsing project files and
        artifacts must not require pod scheduling."""
        _target("§3 target architecture", "G3")


# ── §5.3 Session lifecycle (gate G3: runtime v2 + backend seam) ─────────────


class TestSessionLifecycle:
    def test_active_session_extends_instead_of_dying_at_time_limit(self):
        _target("§5.3 extend-loop", "G3")

    def test_idle_session_snapshots_to_zero(self):
        _target("§5.3", "G3")

    def test_resume_from_snapshot_within_seconds_budget(self):
        _target("§5.3 resume", "G3")

    def test_backend_seam_flag_selects_vercel_like_the_eval_flag(self):
        _target("§5 SP_NOTEBOOK_EXECUTION_BACKEND", "G3")

    def test_pod_endpoints_require_auth_before_public_route_urls_exist(self):
        """Precondition from the design: /api/notion-analysis/* and
        /api/standalone-chat/* must authenticate — NetworkPolicy protection
        does not survive public sandbox route URLs."""
        _target("§5.7 security", "G3 (hard precondition)")

    def test_run_notebook_mcp_tool_uses_pinned_digest_runtime(self):
        _target("§5.6", "G3 (hard precondition)")


# ── §4.5 Git as exporter (gates G5–G6) ──────────────────────────────────────


class TestGitExporter:
    def test_every_s3_revision_maps_to_exactly_one_export_commit(self):
        _target("§4.5", "G5")

    def test_inbound_github_push_imports_as_a_new_revision(self):
        _target("§4.5", "G5")

    def test_export_failure_never_blocks_editing(self):
        _target("§4.5 / §7", "G5")

    def test_agent_branches_still_never_reach_github(self):
        _target("§4.5 (carries over sync.py contract)", "G5")


# ── Unified artifacts (new build item surfaced 2026-08-19) ──────────────────
# Today: chat artifacts have publish + download-by-id only; eval artifacts are
# per-run routes buried in the evals page. No listing endpoint, no browse page.


class TestUnifiedArtifacts:
    def test_artifact_index_lists_across_chat_eval_and_notebook_sources(self):
        """One endpoint (GET /api/artifacts?project=&kind=&run=&since=) that
        enumerates every artifact the org owns, wherever it was produced."""
        _target("artifacts index (new)", "G4")

    def test_artifact_records_carry_provenance_run_task_session(self):
        _target("artifacts index (new)", "G4")

    def test_browse_page_renders_and_downloads_without_a_pod(self):
        _target("artifacts browse page (new)", "G4")

    def test_agent_committed_artifacts_appear_in_the_index(self):
        """Ties to test_vercel_agent_workflow_live: an artifact committed on
        an agent branch must be discoverable without knowing the branch."""
        _target("artifacts index (new)", "G4")

    def test_artifact_retention_prunes_blobs_but_never_provenance_rows(self):
        _target("artifacts index (new)", "G4")
