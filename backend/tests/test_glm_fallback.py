"""Tests for GLM-5.2 primary + Claude Sonnet fallback in /contracts/generate."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.config import settings as _s
from backend.app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_settings():
    orig_anthropic = _s.anthropic_api_key
    orig_glm = _s.glm_api_key
    yield
    _s.anthropic_api_key = orig_anthropic
    _s.glm_api_key = orig_glm


def _anthropic_mock_client(text: str) -> MagicMock:
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def _glm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


_GENERATE_PAYLOAD = {
    "project_type": "website",
    "client_name": "Acme Corp",
    "client_company": "Acme Ltd",
    "scope": "5-page responsive website",
    "fee": 50000,
    "payment_terms": "50% advance, 50% on delivery",
    "timeline": "30 days",
}


def test_glm_used_when_configured_and_available(client):
    """GLM-5.2 is tried first; its content is returned and Claude is never called."""
    _s.glm_api_key = "glm-test-key"
    _s.anthropic_api_key = "sk-ant-test"

    with patch(
        "backend.app.routers.contracts.httpx.post",
        return_value=_glm_response("GLM generated content."),
    ) as mock_post, patch(
        "anthropic.Anthropic", return_value=_anthropic_mock_client("Claude content.")
    ) as mock_anthropic:
        resp = client.post(
            "/contracts/generate",
            json={**_GENERATE_PAYLOAD, "user_email": "glm-success@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["content"] == "GLM generated content."
    mock_post.assert_called_once()
    mock_anthropic.assert_not_called()


def test_falls_back_to_claude_on_glm_auth_failure(client):
    """A GLM/OpenRouter auth failure falls back to Claude instead of raising."""
    _s.glm_api_key = "glm-bad-key"
    _s.anthropic_api_key = "sk-ant-test"

    bad_resp = MagicMock()
    bad_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized", request=MagicMock(), response=MagicMock(status_code=401)
    )

    with patch(
        "backend.app.routers.contracts.httpx.post", return_value=bad_resp
    ), patch(
        "anthropic.Anthropic",
        return_value=_anthropic_mock_client("Claude fallback content."),
    ):
        resp = client.post(
            "/contracts/generate",
            json={**_GENERATE_PAYLOAD, "user_email": "glm-auth-fail@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["content"] == "Claude fallback content."


def test_falls_back_to_claude_on_glm_malformed_response(client):
    """A malformed OpenRouter response body falls back to Claude, not a crash."""
    _s.glm_api_key = "glm-test-key"
    _s.anthropic_api_key = "sk-ant-test"

    malformed_resp = MagicMock()
    malformed_resp.raise_for_status.return_value = None
    malformed_resp.json.return_value = {"error": "unexpected shape"}  # no "choices"

    with patch(
        "backend.app.routers.contracts.httpx.post", return_value=malformed_resp
    ), patch(
        "anthropic.Anthropic",
        return_value=_anthropic_mock_client("Claude fallback content."),
    ):
        resp = client.post(
            "/contracts/generate",
            json={**_GENERATE_PAYLOAD, "user_email": "glm-malformed@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["content"] == "Claude fallback content."


def test_skips_glm_entirely_when_not_configured(client):
    """No GLM_API_KEY set → GLM is never called, Claude serves the request directly."""
    _s.glm_api_key = ""
    _s.anthropic_api_key = "sk-ant-test"

    with patch(
        "backend.app.routers.contracts.httpx.post"
    ) as mock_post, patch(
        "anthropic.Anthropic",
        return_value=_anthropic_mock_client("Claude only content."),
    ):
        resp = client.post(
            "/contracts/generate",
            json={**_GENERATE_PAYLOAD, "user_email": "no-glm@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["content"] == "Claude only content."
    mock_post.assert_not_called()
