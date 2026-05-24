"""Tests unitarios del cliente HTTP de radicado."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.radicado_client import RadicadoServiceError, _base_url, health_check


def test_base_url_strips_trailing_slash():
    from types import SimpleNamespace

    settings = SimpleNamespace(radicado_service_url="http://example.com:5437/")
    assert _base_url(settings) == "http://example.com:5437"


def test_health_check_success():
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"status": "ok"}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch("app.services.radicado_client.httpx.Client", return_value=mock_client):
        result = health_check()
    assert result == {"status": "ok"}


def test_health_check_raises_on_http_error():
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 503
    mock_response.text = "unavailable"
    mock_response.json.side_effect = ValueError()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch("app.services.radicado_client.httpx.Client", return_value=mock_client):
        with pytest.raises(RadicadoServiceError) as exc:
            health_check()
    assert exc.value.status_code == 503
