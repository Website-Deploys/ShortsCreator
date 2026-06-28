"""API contract certification.

Asserts that EVERY error - client or server, validation or storage - is returned
through the single Olympus error envelope::

    {"error": {"code": str, "message": str, "details"?: ...}, "request_id"?: str}

and never as FastAPI's default ``{"detail": [...]}`` shape, never as HTML or
plain text, and always as JSON-serializable content. Includes regression tests
for two contract defects found during certification:

* the validation handler crashed serializing a pydantic ``ctx`` carrying a
  ValueError (-> 500 instead of a clean 422 envelope), and
* hostile/oversized or traversal storage keys raised OSError/StorageError that
  surfaced as 5xx instead of a clean 4xx.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from olympus.data.storage.local import LocalStorage

_HUGE_ID = "proj_" + "A" * 5000


def _assert_envelope(resp, *, expected_status: int | None = None) -> dict:
    """Assert a response is a well-formed Olympus JSON error envelope."""

    if expected_status is not None:
        assert resp.status_code == expected_status, (resp.status_code, resp.text)
    # Must be JSON (never HTML/plain text).
    assert resp.headers["content-type"].startswith("application/json"), resp.headers
    body = resp.json()
    # Olympus envelope, never FastAPI's default {"detail": ...} shape.
    assert "error" in body, body
    assert "detail" not in body, body
    assert isinstance(body["error"].get("code"), str) and body["error"]["code"]
    assert isinstance(body["error"].get("message"), str) and body["error"]["message"]
    return body


# --------------------------------------------------------------------------- #
# Regression: validation handler must never crash serializing its own payload.
# --------------------------------------------------------------------------- #
def test_malformed_multipart_returns_json_envelope_not_500(client: TestClient) -> None:
    """A string where an UploadFile is expected previously crashed the validation
    handler (pydantic ctx carried a non-serializable ValueError) -> 500."""

    resp = client.post("/api/v1/uploads", files={"file": ("", b"x", "video/mp4")})
    body = _assert_envelope(resp, expected_status=422)
    assert body["error"]["code"] == "validation_error"
    # The whole payload round-trips as JSON (no serialization crash).
    import json

    json.dumps(body)


def test_validation_envelope_is_json_serializable_with_ctx(client: TestClient) -> None:
    """Invalid JSON body yields a 422 envelope whose details serialize cleanly."""

    resp = client.post(
        "/api/v1/projects",
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )
    body = _assert_envelope(resp, expected_status=422)
    import json

    json.dumps(body)  # must not raise


# --------------------------------------------------------------------------- #
# Regression: hostile/oversized/traversal keys must be 4xx envelopes, not 5xx.
# --------------------------------------------------------------------------- #
def test_oversized_project_id_returns_404_envelope(client: TestClient) -> None:
    resp = client.get(f"/api/v1/projects/{_HUGE_ID}")
    _assert_envelope(resp, expected_status=404)


def test_oversized_project_id_analysis_returns_404_envelope(client: TestClient) -> None:
    resp = client.get(f"/api/v1/projects/{_HUGE_ID}/analysis")
    _assert_envelope(resp, expected_status=404)


def test_oversized_project_id_delete_is_clean(client: TestClient) -> None:
    resp = client.delete(f"/api/v1/projects/{_HUGE_ID}")
    # Idempotent delete of a non-existent project: 2xx or a 4xx envelope, never 5xx.
    assert resp.status_code < 500, resp.text


def test_traversal_storage_key_on_create_returns_4xx_envelope(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/projects",
        json={
            "storage_key": "../../../etc/passwd",
            "source_filename": "x.mp4",
            "size_bytes": 10,
            "video_format": "mp4",
        },
    )
    body = _assert_envelope(resp)
    assert 400 <= resp.status_code < 500, resp.status_code
    assert body["error"]["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# Envelope consistency across a representative set of error conditions.
# --------------------------------------------------------------------------- #
def test_unknown_route_returns_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/this-route-does-not-exist")
    _assert_envelope(resp, expected_status=404)


def test_unsupported_upload_format_returns_envelope(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/uploads",
        files={"file": ("x.exe", b"MZ", "application/octet-stream")},
    )
    body = _assert_envelope(resp, expected_status=422)
    assert body["error"]["code"] == "validation_error"


def test_no_endpoint_leaks_internal_text_on_unknown_error() -> None:
    """The generic 500 handler must reveal nothing internal."""

    import asyncio
    import json

    from olympus.platform.errors import handlers

    class _Req:
        class state:  # noqa: N801
            request_id = "req_test"

    async def _run() -> object:
        return await handlers._handle_unexpected_error(
            _Req(), RuntimeError("secret internals: /etc/passwd")
        )

    resp = asyncio.run(_run())
    assert resp.status_code == 500
    body = json.loads(bytes(resp.body))
    assert body["error"]["code"] == "internal_error"
    assert "secret internals" not in json.dumps(body)


# --------------------------------------------------------------------------- #
# Storage layer: hostile keys must degrade to absent, never raise.
# --------------------------------------------------------------------------- #
async def test_local_storage_robust_to_oversized_keys(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    huge = "x" * 6000
    assert await storage.exists(huge) is False
    assert storage.local_path(huge) is None
    assert await storage.list_keys(huge) == []


async def test_local_storage_robust_to_traversal_keys(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    # exists()/local_path()/list_keys() answer "absent" for an invalid key rather
    # than raising; get()/put()/delete() still reject traversal (tested elsewhere).
    assert await storage.exists("../../etc/passwd") is False
    assert storage.local_path("../../etc/passwd") is None
    assert await storage.list_keys("../../etc/passwd") == []
