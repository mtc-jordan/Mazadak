"""Reusable FastAPI parameter types."""

from __future__ import annotations

from typing import Annotated

from fastapi import Path, Query

# UUID path parameter — validates format while keeping str type for DB compat
_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

UUIDPath = Annotated[str, Path(min_length=36, max_length=36, pattern=_UUID_PATTERN)]
UUIDQuery = Annotated[str, Query(min_length=36, max_length=36, pattern=_UUID_PATTERN)]
