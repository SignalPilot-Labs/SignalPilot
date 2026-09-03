"""Slug rule R9 — one rule, stated once.

slug = snake of the display name, ``[a-z0-9_]{2,40}``. Unique per (org, scope
owner). A personal slug that collides with an org slug in the same org gets
``_mine`` appended at creation and is never renamed later. Removing an org
connector never renames anything.
"""

from __future__ import annotations

import re

SLUG_PATTERN = re.compile(r"^[a-z0-9_]{2,40}$")
_MAX_LEN = 40
_MINE_SUFFIX = "_mine"


class SlugCollisionError(ValueError):
    """The slug is already taken in the caller's scope."""


def slugify(name: str) -> str:
    """Kebab/snake the display name into ``[a-z0-9_]{2,40}``."""
    lowered = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    collapsed = re.sub(r"_+", "_", lowered).strip("_")
    slug = collapsed[:_MAX_LEN].rstrip("_")
    if len(slug) < 2:
        raise ValueError("Name needs at least two letters or digits")
    return slug


def allocate_slug(name: str, *, scope: str, org_slugs: set[str], own_slugs: set[str]) -> str:
    """Return the slug a new connector gets, or raise SlugCollisionError."""
    base = slugify(name)
    if scope == "org":
        if base in org_slugs:
            raise SlugCollisionError(f'Your organization already has a connector named "{base}"')
        return base
    slug = base
    if slug in org_slugs:
        slug = base[: _MAX_LEN - len(_MINE_SUFFIX)].rstrip("_") + _MINE_SUFFIX
    if slug in own_slugs:
        raise SlugCollisionError(f'You already have a connector named "{slug}"')
    return slug


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_PATTERN.fullmatch(slug))
