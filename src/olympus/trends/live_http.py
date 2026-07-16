"""Bounded public HTTP access for live trend providers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from olympus.platform.config.settings import TrendResearchSettings
from olympus.trends.url_safety import (
    AddressResolver,
    TrendUrlSafetyError,
    ensure_public_dns,
    validate_trend_url,
)

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_TEXT_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
)
_JSON_CONTENT_TYPES = ("application/json", "text/json")


class TrendFetchError(RuntimeError):
    """A safe, user-displayable live-fetch failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FetchedTrendDocument:
    """Transient bounded document; callers must not persist ``text`` verbatim."""

    url: str
    text: str
    content_type: str
    last_modified: str | None
    byte_count: int


class SafeTrendHttpClient:
    """Fetch allowlisted text/JSON with DNS, redirect, and byte-limit checks."""

    def __init__(
        self,
        settings: TrendResearchSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: AddressResolver | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._resolver = resolver

    async def fetch_text(
        self,
        url: str,
        *,
        enforce_allowlist: bool = True,
    ) -> FetchedTrendDocument:
        response, content, final_url = await self._request_bytes(
            url,
            headers={"Accept": "text/html,text/plain;q=0.9"},
            enforce_allowlist=enforce_allowlist,
            require_https=False,
            expected_content_types=_TEXT_CONTENT_TYPES,
        )
        encoding = response.encoding or "utf-8"
        return FetchedTrendDocument(
            url=final_url,
            text=content.decode(encoding, errors="replace"),
            content_type=response.headers.get("content-type", "").split(";", 1)[0].lower(),
            last_modified=response.headers.get("last-modified"),
            byte_count=len(content),
        )

    async def fetch_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        enforce_allowlist: bool = False,
    ) -> Any:
        merged_headers = {"Accept": "application/json", **dict(headers or {})}
        _, content, _ = await self._request_bytes(
            url,
            params=params,
            headers=merged_headers,
            enforce_allowlist=enforce_allowlist,
            require_https=True,
            expected_content_types=_JSON_CONTENT_TYPES,
        )
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrendFetchError(
                "MALFORMED_JSON",
                "The configured trend search endpoint returned malformed JSON.",
            ) from exc

    async def _request_bytes(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        enforce_allowlist: bool,
        require_https: bool,
        expected_content_types: tuple[str, ...],
    ) -> tuple[httpx.Response, bytes, str]:
        current_url = url
        current_params = params
        request_headers = {
            "User-Agent": self._settings.user_agent,
            **dict(headers or {}),
        }
        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            for redirect_count in range(self._settings.max_redirects + 1):
                hostname = validate_trend_url(
                    current_url,
                    allowed_domains=self._settings.allowed_domains,
                    blocked_domains=self._settings.blocked_domains,
                    allowlist_enabled=(
                        self._settings.source_allowlist_enabled and enforce_allowlist
                    ),
                    require_https=require_https,
                )
                await ensure_public_dns(hostname, resolver=self._resolver)
                try:
                    client.cookies.clear()
                    async with client.stream(
                        "GET",
                        current_url,
                        params=current_params,
                        headers=request_headers,
                    ) as response:
                        if response.status_code in _REDIRECT_CODES:
                            location = response.headers.get("location")
                            if not location:
                                raise TrendFetchError(
                                    "REDIRECT_WITHOUT_LOCATION",
                                    "The trend source returned an invalid redirect.",
                                )
                            if redirect_count >= self._settings.max_redirects:
                                raise TrendFetchError(
                                    "TOO_MANY_REDIRECTS",
                                    "The trend source exceeded the redirect limit.",
                                )
                            current_url = urljoin(str(response.url), location)
                            current_params = None
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").lower()
                        if not any(
                            content_type.startswith(expected)
                            for expected in expected_content_types
                        ):
                            raise TrendFetchError(
                                "UNSUPPORTED_CONTENT_TYPE",
                                "The trend source did not return supported text or JSON content.",
                            )
                        content_length = response.headers.get("content-length")
                        if content_length and int(content_length) > self._settings.max_fetch_bytes:
                            raise TrendFetchError(
                                "RESPONSE_TOO_LARGE",
                                "The trend source exceeded the configured byte limit.",
                            )
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self._settings.max_fetch_bytes:
                                raise TrendFetchError(
                                    "RESPONSE_TOO_LARGE",
                                    "The trend source exceeded the configured byte limit.",
                                )
                            chunks.append(chunk)
                        return response, b"".join(chunks), str(response.url)
                except httpx.TimeoutException as exc:
                    raise TrendFetchError(
                        "REQUEST_TIMEOUT",
                        "The trend source request timed out.",
                    ) from exc
                except httpx.HTTPStatusError as exc:
                    raise TrendFetchError(
                        "HTTP_ERROR",
                        f"The trend source returned HTTP {exc.response.status_code}.",
                    ) from exc
                except httpx.RequestError as exc:
                    raise TrendFetchError(
                        "NETWORK_ERROR",
                        "The trend source could not be reached.",
                    ) from exc
                except (TypeError, ValueError) as exc:
                    raise TrendFetchError(
                        "INVALID_RESPONSE_METADATA",
                        "The trend source returned invalid response metadata.",
                    ) from exc
        raise TrendFetchError("FETCH_FAILED", "The trend source fetch did not complete.")


__all__ = [
    "FetchedTrendDocument",
    "SafeTrendHttpClient",
    "TrendFetchError",
    "TrendUrlSafetyError",
]
