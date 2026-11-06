"""Garde-fous sur l'exposition reseau du dashboard.

Le dashboard lit la memoire, le journal d'evenements, le store de refs et la
configuration effective. Une ecoute sur le reseau sans authentification
divulgue des donnees locales : le refus doit etre systematique et explicite.
"""

from __future__ import annotations

import pathlib
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

_DASHBOARD = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
if str(_DASHBOARD.parent) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD.parent))

from dashboard import server as dash  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_auth_token():
    dash.AUTH_TOKEN = None
    yield
    dash.AUTH_TOKEN = None


# ======================================================================
# Politique d'exposition
# ======================================================================


def test_loopback_hosts_are_recognized():
    assert dash.is_loopback("127.0.0.1") is True
    assert dash.is_loopback("::1") is True
    assert dash.is_loopback("localhost") is True
    # Toute la plage 127/8 est locale.
    assert dash.is_loopback("127.0.0.5") is True


def test_non_loopback_hosts_are_rejected():
    assert dash.is_loopback("0.0.0.0") is False
    assert dash.is_loopback("192.168.1.10") is False
    assert dash.is_loopback("::") is False
    assert dash.is_loopback("example.com") is False


def test_remote_host_without_allow_remote_is_refused():
    """`--host 0.0.0.0` seul doit etre refuse : l'exposition est opt-in."""
    with pytest.raises(SystemExit) as exc:
        dash.check_exposure("0.0.0.0", False, "")
    message = str(exc.value)
    assert "--allow-remote" in message
    assert "127.0.0.1" in message


def test_allow_remote_without_token_is_refused():
    """`--allow-remote` sans jeton laisse lire les API : refuse."""
    with pytest.raises(SystemExit) as exc:
        dash.check_exposure("0.0.0.0", True, "")
    assert "--token" in str(exc.value)


def test_allow_remote_with_token_is_accepted():
    dash.check_exposure("0.0.0.0", True, "s3cret")
    assert dash.AUTH_TOKEN == "s3cret"


def test_loopback_does_not_require_a_token():
    """Un acces local reste utilisable sans jeton (comportement historique)."""
    dash.check_exposure("127.0.0.1", False, "")
    assert dash.AUTH_TOKEN is None


def test_loopback_accepts_an_optional_token():
    dash.check_exposure("127.0.0.1", False, "s3cret")
    assert dash.AUTH_TOKEN == "s3cret"


# ======================================================================
# Verification du jeton
# ======================================================================


class _FakeHeaders(dict):
    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


def test_no_token_configured_accepts_everything():
    dash.AUTH_TOKEN = None
    assert dash.token_provided(_FakeHeaders(), {}) is True


def test_bearer_header_is_accepted():
    dash.AUTH_TOKEN = "s3cret"
    headers = _FakeHeaders({"Authorization": "Bearer s3cret"})
    assert dash.token_provided(headers, {}) is True


def test_bearer_header_with_wrong_token_is_rejected():
    dash.AUTH_TOKEN = "s3cret"
    headers = _FakeHeaders({"Authorization": "Bearer nope"})
    assert dash.token_provided(headers, {}) is False


def test_query_parameter_is_accepted():
    """Le dashboard est une appli web : le jeton doit pouvoir venir de l'URL."""
    dash.AUTH_TOKEN = "s3cret"
    assert dash.token_provided(_FakeHeaders(), {"token": ["s3cret"]}) is True
    assert dash.token_provided(_FakeHeaders(), {"token": ["nope"]}) is False


def test_missing_token_is_rejected():
    dash.AUTH_TOKEN = "s3cret"
    assert dash.token_provided(_FakeHeaders(), {}) is False


# ======================================================================
# Le gate HTTP reel
# ======================================================================


def _serve(token: str | None):
    dash.AUTH_TOKEN = token
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _get(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_api_requires_the_token_when_configured():
    srv, base = _serve("s3cret")
    try:
        assert _get(f"{base}/api/health") == 401
        assert _get(f"{base}/api/health", {"Authorization": "Bearer s3cret"}) == 200
        assert _get(f"{base}/api/health?token=s3cret") == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_is_open_without_token():
    srv, base = _serve(None)
    try:
        assert _get(f"{base}/api/health") == 200
    finally:
        srv.shutdown()
        srv.server_close()
