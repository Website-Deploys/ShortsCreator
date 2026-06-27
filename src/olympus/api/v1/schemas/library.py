"""Schemas for the Project Management & Asset Library API.

The library aggregates rich, evolving records from across the engines, so most
responses pass structured dicts through intact (each record already carries its
real fields, with UNKNOWN where an engine produced nothing). Mutation requests
(favorite, tag) are small typed bodies.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DashboardResponse(BaseModel):
    total_projects: int
    videos_processed: int
    minutes_analyzed: float
    clips_generated: int
    renders_completed: int
    exports: int
    average_viral_score: float | None
    storage_bytes: int
    archived_projects: int


class AssetsResponse(BaseModel):
    count: int
    assets: list[dict[str, Any]]


class ClipsResponse(BaseModel):
    count: int
    clips: list[dict[str, Any]]


class ExportsResponse(BaseModel):
    count: int
    exports: list[dict[str, Any]]


class SearchResponse(BaseModel):
    query: str
    count: int
    hits: list[dict[str, Any]]


class ActivityResponse(BaseModel):
    count: int
    events: list[dict[str, Any]]


class StorageResponse(BaseModel):
    total_bytes: int
    breakdowns: list[dict[str, Any]]


class VersionEnginesResponse(BaseModel):
    project_id: str
    engines: list[str]


class VersionsResponse(BaseModel):
    project_id: str
    engine: str
    versions: list[dict[str, Any]]


class VersionPayloadResponse(BaseModel):
    project_id: str
    engine: str
    version: int
    payload: dict[str, Any]


class CapturedVersionsResponse(BaseModel):
    project_id: str
    captured: list[dict[str, Any]]


class MetaResponse(BaseModel):
    meta: dict[str, Any]


class CleanupResponse(BaseModel):
    result: dict[str, Any]


class FavoriteRequest(BaseModel):
    favorite: bool


class TagRequest(BaseModel):
    tag: str
