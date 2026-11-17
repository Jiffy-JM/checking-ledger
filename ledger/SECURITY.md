# Security

Checking Ledger holds personal financial data, so it is built to keep that
data on the machine it runs on.

## What the app does and doesn't do

* The server code makes no outbound connections. It imports no networking
  libraries, and the tests run every page and action with networking blocked.
* Pages load only files served by the app itself. A Content-Security-Policy
  header tells the browser to refuse anything else, including connections
  made by script.
* The container runs as an unprivileged user with a read-only filesystem
  (except `data/`), no Linux capabilities, and no privilege escalation.
* Sign-in uses one password (`APP_PASSWORD`). Sessions are signed cookies
  tied to that password, so changing it signs out every browser.
* Every form carries a cross-site request token.
* Text you enter is escaped on every page, and names can't begin with the
  characters spreadsheets treat as the start of a formula.

## Known limits

* **Plain HTTP.** On your home network the password and session cookie
  travel unencrypted. Don't forward the port through your router. To use it
  across networks, put it behind a reverse proxy with HTTPS and set
  `COOKIE_SECURE=1`.
* **No password means no protection.** If `APP_PASSWORD` is empty, anything
  that can reach the port can read and change the ledger. Set
  `ALLOWED_HOSTS` as well so web pages elsewhere can't reach the app through
  your browser by DNS rebinding.
* **Lock signs out one browser.** A copied session cookie stays valid until
  it expires (30 days) or the password changes.
* **Wrong passwords are only slowed, not locked out.** Each wrong guess
  takes one second. Use a long password.
* **Very old dates are slow.** A ledger whose balance dates go back decades
  with many weekly rows takes a long time to project. If an upload makes the
  app unresponsive, restore the previous file from `data/backups/`.
* **What-ifs live in the page address.** Trying a what-if puts its amount
  and date in the address bar, so it can appear in your browser history. It
  is never saved to the ledger, and the server's log records paths only,
  not the part after the question mark.
* **Build-time downloads.** Building the image downloads the Python base
  image and the pinned packages in `requirements.txt`. Those are the only
  outside code involved.

## Cloud backup

The optional backup runs in its own container so the app keeps its promise
of never connecting to the internet.

* **Separation.** The app container has no storage keys and no backup code.
  The backup container mounts `data` read-only, so it cannot alter or delete
  the ledger. The two share one small status file, which the app only reads
  and treats as untrusted.
* **Encryption before upload.** Backups are made with restic. Every stored
  file is encrypted with AES-256 and authenticated with Poly1305-AES, with a
  fresh random value per file. The keys are protected by your password using
  the scrypt key-derivation function. File names and folder structure are
  encrypted too.
* **In transit.** The script refuses any storage address that isn't
  `https://`.
* **Password rules.** The script refuses passwords shorter than 20
  characters. The password and keys are never written to the status file or
  the logs.
* **Restore is non-destructive.** Restored files go to `restore/`, never
  over live data.

Limits to know about:

* `backup.env` holds the password and keys in plain text on the server. Keep
  it readable only by you (`chmod 600 backup.env`). Anyone who takes over
  the server can read it, but they could read the ledger itself anyway.
* The storage token can delete objects, because old backups are pruned. If
  the server were taken over, the attacker could delete the backups. To
  rule that out, add a Bucket Lock retention rule in R2 and set
  `BACKUP_PRUNE=0` in `backup.env`.
* The backup container can reach the internet in general, not only your
  storage provider.
* Image versions are fixed by tag. Pinning by digest is stricter; see
  `docs/PUBLISHING.md`.

## The browser preview

`preview/` is a static page with made-up data. It has no server, stores
nothing, and its `_headers` file blocks every outside connection.

## Reporting a problem

Please use **Report a vulnerability** on this repository's Security tab
rather than a public issue.
