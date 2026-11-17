"""The Theme page and the theme list."""
import pathlib
import re
from datetime import date

import pytest

from app import create_app
from themes import MODES, THEMES

ROOT = pathlib.Path(__file__).resolve().parent.parent
TODAY = date(2026, 9, 20)


@pytest.fixture
def client(tmp_path):
    return create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY).test_client()


def token(client):
    return re.search(r'name="_csrf" value="([^"]+)"', client.get("/appearance").get_data(as_text=True)).group(1)


def look(client, path="/setup"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'<html lang="en" data-theme="([^"]*)" data-mode="([^"]*)">', html).groups()


def test_ember_violet_dark_is_the_default(client):
    assert look(client) == ("ember", "dark")


def test_picking_a_theme_is_remembered_by_that_browser(client, tmp_path):
    r = client.post("/appearance", data={"_csrf": token(client), "theme": "indigo", "mode": "dark"})
    assert r.status_code == 302
    assert look(client) == ("indigo", "dark")
    page = client.get("/appearance").get_data(as_text=True)
    assert 'content="#06070F"' in page                       # toolbar color follows the theme
    other = create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY).test_client()
    assert look(other) == ("ember", "dark")                   # another browser is unaffected


def test_unknown_choices_are_refused_and_ignored(client):
    client.post("/appearance", data={"_csrf": token(client), "theme": "nope", "mode": "dark"})
    assert look(client) == ("ember", "dark")
    client.set_cookie("theme", '"><script>')
    client.set_cookie("mode", "sideways")
    assert look(client) == ("ember", "dark")


def test_changing_the_theme_needs_the_form_token(client):
    assert client.post("/appearance", data={"theme": "indigo", "mode": "dark"}).status_code == 400


def test_the_server_can_set_the_starting_theme(tmp_path, monkeypatch):
    monkeypatch.setenv("THEME", "Indigo")
    monkeypatch.setenv("THEME_MODE", "dark")
    c = create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY).test_client()
    assert look(c) == ("indigo", "dark")
    c.post("/appearance", data={"_csrf": token(c), "theme": "gold", "mode": "light"})
    assert look(c) == ("gold", "light")                      # a browser's own choice wins
    monkeypatch.setenv("THEME", "not-a-theme")
    assert look(create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY).test_client())[0] == "ember"


def test_theme_page_sits_behind_the_password(tmp_path):
    c = create_app(data_dir=str(tmp_path), password="pw", today=lambda: TODAY).test_client()
    assert "/login" in c.get("/appearance").headers["Location"]


def test_every_listed_theme_has_its_colors_in_the_stylesheet():
    css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
    source = (ROOT / "tailwind" / "input.css").read_text(encoding="utf-8")
    for key in THEMES:
        assert len(re.findall(rf"\[data-theme=\"?{key}\"?\]", css)) >= 3, f"{key} is missing from static/app.css (run ./tailwind/build.sh)"
        assert f'[data-theme="{key}"]' in source
    assert set(re.findall(r'\[data-theme="(\w+)"\]', source)) == set(THEMES)
    assert list(MODES) == ["auto", "light", "dark"]


def test_theme_page_lists_every_theme(client):
    page = client.get("/appearance").get_data(as_text=True)
    for key, (name, *_rest) in THEMES.items():
        assert f'name="theme" value="{key}"' in page and name in page
