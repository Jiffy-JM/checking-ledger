# Preview

A copy of Checking Ledger that runs entirely in the browser on made-up data,
so people can try it without installing anything. Nothing is saved and
nothing is sent anywhere: reloading the page starts over.

* `engine.js` is the ledger and net worth math from `ledger_core.py`,
  `networth.py`, and the chart code in `app.py`, rewritten in JavaScript.
* `ui.js` draws the same pages as `templates/`.
* `app.css`, `fonts/`, and the icons are copies of the files in `static/`.
* `help.js` is the app's Help page text, made from `templates/_help_body.html`.

Run `python3 preview/sync.py` to refresh those copies.

## Host it on Cloudflare Pages

1. In the Cloudflare dashboard, create a Pages project connected to this
   repository.
2. Set the build command to `exit 0` and the build output directory to
   `preview`.

Or, without connecting a repository, create a Direct Upload project and
drag in this folder.

`_headers` gives every response a Content-Security-Policy that blocks all
outside connections. If you turn on Cloudflare Web Analytics or other
injected scripts, that policy blocks them too.

To look at it on your own computer: `python3 -m http.server -d preview 8080`
and open `http://localhost:8080`.

## Matching your own site

The preview starts with the theme named on the first line of `index.html`
(`data-theme="ember" data-mode="dark"`). Change those two values to any theme
from `themes.py`, for example `data-theme="indigo" data-mode="auto"`.

## Keeping it in step with the app

`tests/test_preview.py` fails if the styles, font, icons, or Help text differ
from the app's, if any preview file mentions an outside address or a network
call, or (when Node is installed) if `engine.js` computes different numbers
than the Python code for the same ledger. After changing the math or the
templates, update `engine.js` or `ui.js` to match, run
`python3 preview/sync.py`, and run the tests.
