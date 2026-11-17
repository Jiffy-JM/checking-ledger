# Publishing the app to a container registry

This explains how to publish Checking Ledger as a ready-made image, how to
update a server from it, and why the registry can never hold your data or
hand you a tampered image.

The registry used here is GitHub's (GHCR), because the code already lives on
GitHub and no extra account or password is needed.

## What gets published, and what never can

The image contains the program only: five Python files, the page templates,
and the styles, script, icon, and font. Your ledger is not part of it, and
several independent things keep it that way:

| Safeguard | Where |
|---|---|
| The image is built from a named list of files, not "everything in the folder" | `Dockerfile` (`COPY` lines) |
| `data/`, `.env`, `backup.env`, `backup-status/`, and `restore/` are excluded from the build | `.dockerignore` |
| Those same paths are never committed, so they don't exist where the image is built | `.gitignore` |
| The image is built by GitHub from a clean copy of the repository, never on your server | `.github/workflows/publish.yml` |
| The build stops if a settings file or any data file is present | "Refuse to build" step |
| The finished image is opened and checked for data, settings, and running as root | "Check the published image" step |
| The tests fail if any of the exclusions above are removed | `tests/test_backup.py` |

Your data only ever exists in the `data` folder on your own server. It is
attached to the container when it starts and is never copied into an image.
Both containers run with a read-only filesystem, so nothing can be written
into them, and you never run `docker commit` or `docker push` on the server.
The server only downloads; it holds no credential that can write to the
registry.

## One-time setup

1. **Push the repository to GitHub.** Both workflow files come with it.
2. **Protect version tags.** In the repository, go to Settings, Rules,
   Rulesets, and add a tag ruleset for `v*` that restricts creation, update,
   and deletion to you. This stops anyone else from triggering a publish.
3. **Turn on two-factor sign-in** for your GitHub account if it isn't already.
   Your account is the only thing that can publish.
4. **Do not create a personal access token for the registry.** The workflow
   signs in with a temporary token GitHub creates for that one run, limited
   to this repository's package. There is no long-lived password to leak.

## Publishing a version

1. Make sure the tests pass on `main`.
2. Tag the commit and push the tag:
   ```
   git tag v1.0.0
   git push origin v1.0.0
   ```
3. Open the Actions tab and wait for "Publish image". It runs the tests,
   builds for Intel/AMD and ARM (Raspberry Pi, Apple silicon), publishes,
   and then checks the result.
4. The run's summary page shows one line to copy, like:
   ```
   LEDGER_IMAGE=ghcr.io/OWNER/checking-ledger@sha256:4f2a...
   ```
5. The first time only: open the package on GitHub (your profile, Packages,
   `checking-ledger`), and in Package settings set visibility to Public so
   servers can download it without signing in. Under "Manage Actions access",
   confirm only this repository is listed.

Never reuse a version number. If a release is wrong, publish the next number.

## Why you can trust what you download

A tag such as `:1.0.0` is a label, and anyone who can write to the package
could point it at different contents. The `sha256:...` digest is a
fingerprint of the contents themselves. If a single byte of the image were
changed, the digest would be different, and Docker refuses to run an image
whose contents don't match the digest you asked for.

So always run by digest, as the summary line above does. Then:

* Nobody can swap the image under you, including someone who took over the
  registry account. A changed image has a different digest and is never
  pulled.
* Updating is a deliberate act: you change the digest in `.env` yourself.
* Each published image carries a signed build record (provenance) and a
  list of its contents, created by GitHub during the build. To see which
  commit and workflow produced an image:
  ```
  docker buildx imagetools inspect ghcr.io/OWNER/checking-ledger@sha256:... --format '{{ json .Provenance }}'
  ```

## Updating your server

Your data is in the `data` folder, outside the container. Updating replaces
the container and leaves that folder alone. Take a copy first anyway.

```
cd ~/checking-ledger-python
cp -a data "data-before-update-$(date +%F)"

nano .env                      # set LEDGER_IMAGE= to the new line
docker compose pull ledger
docker compose up -d --no-build
```

Open the app and check your balance and History look right.

**To go back:** put the previous `LEDGER_IMAGE` line back in `.env` and run
the last two commands again. If the data itself needs restoring, stop the
app with `docker compose down`, copy the files from the dated folder back
into `data`, and start it again.

Always run these commands from the same folder. Started from a different
folder, the app finds an empty `data` folder and looks like a fresh
install; your real data is still where it was.

If `LEDGER_IMAGE` is blank, `docker compose up --build -d` builds the app
on the server from the files there, exactly as before.

## The backup image

The optional backup service uses the official `restic/restic` image at a
fixed version, set in `docker-compose.yml`. It is published by the restic
project, not by this repository. To pin it by digest as well, look the
digest up once and add it to the `image:` line:

```
docker buildx imagetools inspect restic/restic:0.19.1
# then in docker-compose.yml:  image: restic/restic:0.19.1@sha256:...
```

## Checklist

- [ ] `.env`, `backup.env`, and everything in `data/` show as ignored in `git status`
- [ ] Tag ruleset for `v*` is on
- [ ] Two-factor sign-in is on
- [ ] No personal access tokens with package write access exist
- [ ] `.env` on the server uses `@sha256:`, not a tag
- [ ] A copy of `data` is taken before each update
