from __future__ import annotations

import json

import pytest
from scripts.jsdelivr_url import DEFAULT_JSDELIVR_BASE, build_url, main, normalize_base


def test_build_url_uses_china_mirror_by_default() -> None:
    assert DEFAULT_JSDELIVR_BASE == "https://cdn.jsdmirror.com"
    assert build_url(DEFAULT_JSDELIVR_BASE, "webees/immich-cn", "main", "/README.md") == (
        "https://cdn.jsdmirror.com/gh/webees/immich-cn@main/README.md"
    )


def test_main_allows_user_configured_base(capsys) -> None:
    assert main(["--base", "https://jsd.onmicrosoft.cn/", "--path", "docs/conventions.md"]) == 0
    assert capsys.readouterr().out.strip() == (
        "https://jsd.onmicrosoft.cn/gh/webees/immich-cn@main/docs/conventions.md"
    )


def test_main_outputs_fallbacks(capsys) -> None:
    assert main(["--json", "--path", "README.md"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["primary"].startswith("https://cdn.jsdmirror.com/gh/")
    assert "https://cdn.jsdelivr.net/gh/" in payload["fallbacks"][0]


@pytest.mark.parametrize(
    "base",
    [
        "http://cdn.example.com",
        "https://user:pass@cdn.example.com",
        "https://cdn.example.com?x=1",
        "https://cdn.example.com/#frag",
        "https://",
    ],
)
def test_normalize_base_rejects_unsafe_urls(base: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        normalize_base(base)
