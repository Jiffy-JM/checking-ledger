"""Copies what the preview shares with the app: styles, font, icons, and the
Help page text. Run after changing any of them:   python3 preview/sync.py"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "preview"


def help_js() -> str:
    body = (ROOT / "templates" / "_help_body.html").read_text(encoding="utf-8")
    return "// Made by preview/sync.py from templates/_help_body.html. Don\'t edit by hand.\nvar HELP_HTML = " + json.dumps(body) + ";\n"


def main() -> None:
    shutil.copyfile(ROOT / "static" / "app.css", PREVIEW / "app.css")
    shutil.copyfile(ROOT / "static" / "fonts" / "public-sans.woff2", PREVIEW / "fonts" / "public-sans.woff2")
    for icon in ("icon-180.png", "favicon-32.png"):
        shutil.copyfile(ROOT / "static" / icon, PREVIEW / icon)
    (PREVIEW / "help.js").write_text(help_js(), encoding="utf-8")


if __name__ == "__main__":
    main()
