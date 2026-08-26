"""Internal API for package management."""

from signalpilot._runtime.packages.package_manager import (
    PackageDescription,
    PackageManager,
)
from signalpilot._runtime.packages.package_managers import create_package_manager

__all__ = [
    "PackageDescription",
    "PackageManager",
    "create_package_manager",
]
