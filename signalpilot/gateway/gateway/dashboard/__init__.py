"""First-class governed dashboard domain contracts."""

from .domain import DashboardDefinition, dashboard_content_hash, normalize_dashboard_definition

__all__ = [
    "DashboardDefinition",
    "dashboard_content_hash",
    "normalize_dashboard_definition",
]
