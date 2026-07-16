"""URL and DNS safety checks for live trend-research providers."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

AddressResolver = Callable[[str], Sequence[str]]

_INTERNAL_HOST_SUFFIXES = (
    ".internal",
    ".intranet",
    ".lan",
    ".local",
    ".localhost",
    ".home",
)
_RESERVED_HOST_SUFFIXES = (".example", ".invalid", ".test")


class TrendUrlSafetyError(ValueError):
    """Raised when a live-provider URL violates the public-network policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_trend_url(
    url: str,
    *,
    allowed_domains: Sequence[str] = (),
    blocked_domains: Sequence[str] = (),
    allowlist_enabled: bool = False,
    require_https: bool = False,
) -> str:
    """Validate syntax, scheme, host, credentials, and configured domain policy."""

    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise TrendUrlSafetyError("INVALID_URL", "The URL is malformed.") from exc
    schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme.lower() not in schemes:
        raise TrendUrlSafetyError(
            "UNSUPPORTED_SCHEME",
            "Only public HTTP(S) trend sources are allowed.",
        )
    if parsed.username or parsed.password:
        raise TrendUrlSafetyError(
            "URL_CREDENTIALS_REJECTED",
            "Trend source URLs cannot contain credentials.",
        )
    hostname = _normalized_domain(parsed.hostname)
    if not hostname:
        raise TrendUrlSafetyError("MISSING_HOST", "The URL does not contain a valid host.")
    if port is not None and port not in {80, 443}:
        raise TrendUrlSafetyError(
            "UNSAFE_PORT",
            "Trend providers may use only standard HTTP or HTTPS ports.",
        )
    _validate_hostname(hostname)
    if any(_domain_matches(hostname, domain) for domain in blocked_domains):
        raise TrendUrlSafetyError(
            "BLOCKED_DOMAIN",
            "The trend source domain is blocked by configuration.",
        )
    if allowlist_enabled and not any(
        _domain_matches(hostname, domain) for domain in allowed_domains
    ):
        raise TrendUrlSafetyError(
            "DOMAIN_NOT_ALLOWLISTED",
            "The trend source domain is not in the configured allowlist.",
        )
    return hostname


async def ensure_public_dns(
    hostname: str,
    *,
    resolver: AddressResolver | None = None,
) -> tuple[str, ...]:
    """Resolve a host and reject any private, local, or reserved destination."""

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        _validate_ip(literal)
        return (str(literal),)

    try:
        addresses = (
            tuple(resolver(hostname))
            if resolver is not None
            else await asyncio.to_thread(_resolve_addresses, hostname)
        )
    except OSError as exc:
        raise TrendUrlSafetyError(
            "DNS_RESOLUTION_FAILED",
            "The trend source host could not be resolved.",
        ) from exc
    unique = tuple(dict.fromkeys(str(address) for address in addresses if str(address)))
    if not unique:
        raise TrendUrlSafetyError(
            "DNS_RESOLUTION_FAILED",
            "The trend source host did not resolve to a public address.",
        )
    for value in unique:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise TrendUrlSafetyError(
                "DNS_RESULT_INVALID",
                "The trend source host returned an invalid address.",
            ) from exc
        _validate_ip(address)
    return unique


def domain_matches(hostname: str, domain: str) -> bool:
    """Return whether ``hostname`` is ``domain`` or one of its subdomains."""

    return _domain_matches(_normalized_domain(hostname), domain)


def _resolve_addresses(hostname: str) -> tuple[str, ...]:
    records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    return tuple(str(record[4][0]) for record in records)


def _validate_hostname(hostname: str) -> None:
    if hostname in {"localhost", "localhost.localdomain"}:
        raise TrendUrlSafetyError("LOCAL_HOST_REJECTED", "Local hosts are not allowed.")
    if hostname.endswith((*_INTERNAL_HOST_SUFFIXES, *_RESERVED_HOST_SUFFIXES)):
        raise TrendUrlSafetyError(
            "INTERNAL_HOST_REJECTED",
            "Internal and reserved hostnames are not allowed.",
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname:
            raise TrendUrlSafetyError(
                "INTERNAL_HOST_REJECTED",
                "Single-label internal hostnames are not allowed.",
            ) from None
        return
    _validate_ip(address)


def _validate_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not address.is_global:
        raise TrendUrlSafetyError(
            "PRIVATE_ADDRESS_REJECTED",
            "Private, loopback, link-local, reserved, and unspecified addresses are not allowed.",
        )


def _normalized_domain(value: str | None) -> str:
    return (value or "").strip().rstrip(".").lower()


def _domain_matches(hostname: str, domain: str) -> bool:
    normalized = _normalized_domain(domain)
    return bool(normalized) and (
        hostname == normalized or hostname.endswith(f".{normalized}")
    )
