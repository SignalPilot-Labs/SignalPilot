"""Eval runs: "Evaluate Change" for knowledge-base entries.

Runs the agent system in docker against a linked eval-question repo, with
proposed knowledge entries overlaid via the MCP X-SP-Eval-Docs header.
State is file-based under SP_DATA_DIR/eval-runs — no database tables.
"""
