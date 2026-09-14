from collectors import bilibili_auth


def test_api_mode_does_not_attempt_buvid_cookie_self_healing(monkeypatch):
    monkeypatch.setattr(bilibili_auth, "COOKIE_WRITES_ENABLED", False)
    monkeypatch.setattr(
        bilibili_auth.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call not expected")),
    )
    monkeypatch.setattr(
        bilibili_auth,
        "save_cookie",
        lambda cookies: (_ for _ in ()).throw(AssertionError("cookie write not expected")),
    )

    cookies = {"SESSDATA": "session"}

    assert bilibili_auth._ensure_buvid3(cookies) == cookies
