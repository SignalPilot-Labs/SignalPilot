"""Self-improving evaluation loop.

Modules:
- registry: per-task per-round status history (JSONL append-only)
- sampler: stratified per-round task sampling with regression anchors
- runner: drive one round (sample → run → evaluate → judge → record)
"""
