import time
from urllib.parse import parse_qs, urlparse

import pytest

from tests.api_fakes import REPO, FakeGraph, client
from whycode.api import auth

KEY = "test-session-secret"
USER = {"login": "octocat", "name": "The Octocat", "avatar_url": "https://example.com/a.png"}


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv(auth.AUTH_ENV, "github")
    monkeypatch.setenv("SESSION_SECRET", KEY)
    monkeypatch.setenv("GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("CRON_SECRET", "cron-secret")


def session(user=USER, exp=None):
    return {auth.SESSION_COOKIE: auth.sign({"user": user, "exp": exp or time.time() + 60}, KEY)}


def test_signed_tokens_round_trip_and_reject_tampering_and_expiry():
    token = auth.sign({"a": 1, "exp": 200}, KEY)
    assert auth.unsign(token, KEY, now=100) == {"a": 1, "exp": 200}
    assert auth.unsign(token, KEY, now=300) is None
    assert auth.unsign(token, "other-key", now=100) is None
    body, mac = token.split(".")
    forged = auth.sign({"a": 2, "exp": 200}, KEY).split(".")[0] + "." + mac
    assert auth.unsign(forged, KEY, now=100) is None
    for junk in (None, "", "abc", "a.b.c", "!!.!!"):
        assert auth.unsign(junk, KEY) is None


@pytest.mark.parametrize(
    ("given", "safe"),
    [
        (None, "/"),
        ("/why?q=x", "/why?q=x"),
        ("https://evil.example", "/"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
    ],
)
def test_after_sign_in_only_paths_on_this_site(given, safe):
    assert auth._safe_next(given) == safe


def test_with_sign_in_off_routes_stay_open():
    c = client(FakeGraph())
    assert c.get("/api/repos").status_code == 200
    assert c.get("/api/auth/me").json() == {"enabled": False, "user": None}


def test_data_routes_need_a_session(auth_on):
    c = client(FakeGraph())
    res = c.get("/api/repos")
    assert res.status_code == 401
    assert res.json()["detail"] == "Sign in with GitHub to use WhyCode."
    assert c.get("/api/health", params={"repo": REPO}).status_code == 401
    assert c.get("/api/repos", cookies=session()).status_code == 200
    expired = session(exp=time.time() - 1)
    assert c.get("/api/repos", cookies=expired).status_code == 401


def test_me_returns_the_signed_in_user(auth_on):
    c = client(FakeGraph())
    assert c.get("/api/auth/me").json() == {"enabled": True, "user": None}
    assert c.get("/api/auth/me", cookies=session()).json() == {"enabled": True, "user": USER}


def test_login_sends_to_github_with_a_state_cookie(auth_on):
    res = client(FakeGraph()).get(
        "/api/auth/login", params={"next": "/health"}, follow_redirects=False
    )
    assert res.status_code == 302
    url = urlparse(res.headers["location"])
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == auth.AUTHORIZE_URL
    assert query["client_id"] == ["client-id"] and query["scope"] == ["read:user"]
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{auth.STATE_COOKIE}=")
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    saved = auth.unsign(res.cookies[auth.STATE_COOKIE], KEY)
    assert saved["state"] == query["state"][0] and saved["next"] == "/health"


class FakeGitHub:
    """Stands in for httpx.Client against GitHub's token and user endpoints."""

    def __init__(self, token="gho_x", status=200):
        self.token, self.status, self.calls = token, status, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, data, headers):
        self.calls.append(("post", url, data))
        return FakeResponse(200, {"access_token": self.token} if self.token else {"error": "bad"})

    def get(self, url, headers):
        self.calls.append(("get", url, headers["Authorization"]))
        return FakeResponse(self.status, {**USER, "id": 1})


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code, self.data = status_code, data

    def json(self):
        return self.data


def callback(github, state="s1", saved_state="s1", next_path="/why?q=x"):
    app_client = client(FakeGraph(), {auth.http_client: lambda: github})
    cookie = auth.sign({"state": saved_state, "next": next_path, "exp": time.time() + 60}, KEY)
    return app_client.get(
        "/api/auth/callback",
        params={"code": "c1", "state": state},
        cookies={auth.STATE_COOKIE: cookie},
        follow_redirects=False,
    )


def test_callback_signs_the_user_in_and_keeps_no_token(auth_on):
    github = FakeGitHub()
    res = callback(github)
    assert res.status_code == 302 and res.headers["location"] == "/why?q=x"
    payload = auth.unsign(res.cookies[auth.SESSION_COOKIE], KEY)
    assert payload["user"] == USER
    assert "gho_x" not in res.headers["set-cookie"]
    assert github.calls[0] == (
        "post",
        auth.TOKEN_URL,
        {"client_id": "client-id", "client_secret": "client-secret", "code": "c1"},
    )
    assert github.calls[1] == ("get", auth.USER_URL, "Bearer gho_x")


def test_callback_refuses_a_state_it_did_not_start(auth_on):
    github = FakeGitHub()
    res = callback(github, state="forged")
    assert res.status_code == 400 and github.calls == []


def test_callback_reports_a_refused_code(auth_on):
    assert callback(FakeGitHub(token=None)).status_code == 401
    assert callback(FakeGitHub(status=500)).status_code == 502


def test_logout_clears_the_session(auth_on):
    res = client(FakeGraph()).post("/api/auth/logout", cookies=session())
    assert res.status_code == 204
    assert res.headers["set-cookie"].startswith(f'{auth.SESSION_COOKIE}=""')


def test_missing_config_is_named_not_shown(monkeypatch):
    monkeypatch.setenv(auth.AUTH_ENV, "github")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    res = client(FakeGraph()).get("/api/repos")
    assert res.status_code == 503
    assert res.json()["detail"] == "Sign-in is not configured (SESSION_SECRET is not set)."


def test_keepalive_only_for_the_cron_secret(auth_on):
    c = client(FakeGraph(keepalive=[{"n": 1}]))
    assert c.get("/api/keepalive").status_code == 401
    bad = c.get("/api/keepalive", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401
    ok = c.get("/api/keepalive", headers={"Authorization": "Bearer cron-secret"})
    assert ok.status_code == 200 and ok.json() == {"repos": 1}


REVIEWER_PASSWORD = "correct-horse-battery-staple-42"


@pytest.fixture
def reviewer(auth_on, monkeypatch):
    monkeypatch.setenv("REVIEWER_USERNAME", "reviewer")
    monkeypatch.setenv("REVIEWER_PASSWORD", REVIEWER_PASSWORD)
    attempts = auth.MemoryAttempts()
    return client(FakeGraph(), {auth.get_attempts: lambda: attempts}), attempts


def login(c, password=REVIEWER_PASSWORD, username="reviewer", ip="1.2.3.4"):
    return c.post(
        "/api/auth/password",
        json={"username": username, "password": password},
        headers={"X-Forwarded-For": f"{ip}, 10.0.0.1"},
    )


def test_reviewer_signs_in_with_the_same_session(reviewer):
    c, _ = reviewer
    res = login(c)
    assert res.status_code == 204
    cookie = res.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    payload = auth.unsign(res.cookies[auth.SESSION_COOKIE], KEY)
    assert payload["user"] == {"login": "reviewer", "name": "Reviewer account", "avatar_url": None}


def test_wrong_details_are_refused_without_saying_which(reviewer):
    c, attempts = reviewer
    for res in (login(c, password="nope"), login(c, username="admin")):
        assert res.status_code == 401
        assert res.json()["detail"] == "Wrong username or password."
        assert auth.SESSION_COOKIE not in res.cookies
    assert attempts.failures("1.2.3.4", 60) == (2, 2)


def test_five_failures_lock_that_client_out_even_with_the_right_password(reviewer):
    c, _ = reviewer
    for _ in range(auth.MAX_FAILURES_PER_CLIENT):
        assert login(c, password="guess").status_code == 401
    locked = login(c)
    assert locked.status_code == 429
    assert locked.json()["detail"] == "Too many failed sign-ins. Try again in 15 minutes."
    assert login(c, ip="5.6.7.8").status_code == 204  # another client still gets in


def test_many_failures_overall_lock_everyone_out(reviewer):
    c, attempts = reviewer
    for i in range(auth.MAX_FAILURES_OVERALL):
        attempts.record(f"10.0.{i}.1")
    assert login(c, ip="9.9.9.9").status_code == 429


@pytest.mark.parametrize(
    ("username", "password"), [("", REVIEWER_PASSWORD), ("reviewer", "too-short-password")]
)
def test_reviewer_sign_in_is_off_without_a_long_password(auth_on, monkeypatch, username, password):
    monkeypatch.setenv("REVIEWER_USERNAME", username)
    monkeypatch.setenv("REVIEWER_PASSWORD", password)
    res = login(client(FakeGraph(), {auth.get_attempts: auth.MemoryAttempts}), password=password)
    assert res.status_code == 404


def test_reviewer_sign_in_is_off_when_sign_in_is_off(monkeypatch):
    monkeypatch.setenv("REVIEWER_USERNAME", "reviewer")
    monkeypatch.setenv("REVIEWER_PASSWORD", REVIEWER_PASSWORD)
    assert login(client(FakeGraph())).status_code == 404


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return FakeCursor((2, 7))


def test_postgres_attempts_sql():
    conn = FakeConn()
    store = auth.PgAttempts(conn)
    assert store.failures("1.2.3.4", 900) == (2, 7)
    store.record("1.2.3.4")
    statements = [s for s, _ in conn.sql]
    assert "CREATE TABLE IF NOT EXISTS login_failures" in statements[0]
    assert conn.sql[1][1] == ("1.2.3.4", 900)
    assert conn.sql[2] == ("INSERT INTO login_failures (client) VALUES (%s)", ("1.2.3.4",))
    assert "DELETE FROM login_failures" in statements[3]
