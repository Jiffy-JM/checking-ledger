# Checking Ledger

Projects your checking balance 2 weeks to 1 year out from your paycheck,
bills, card payments, and transfers, and tracks your net worth over time.
Python (Flask) does all the math. Your data is two CSV files you can
download, edit in Numbers or Excel, and upload again.

It runs entirely on your own server and never contacts the internet.

**Try it first:** the `preview` folder is a copy that runs in a web browser
on made-up data, with nothing to install. See [preview/README.md](preview/README.md).

## Set it up on your server

1. Get the code onto the server and open a terminal in its folder:
   ```
   git clone https://github.com/Jiffy-JM/checking-ledger.git
   cd checking-ledger
   ```
2. Create your settings file from the template, then edit it:
   ```
   cp .env.example .env
   nano .env
   ```
   * `HOST_IP`: the server's address on your home network, like
     `192.168.1.50`. The app answers only on this address.
   * `PUID` and `PGID`: run `id -u` and `id -g` on the server and use those
     numbers. The app runs as that user, never as root.
   * `APP_PASSWORD`: set a long one. Anyone on your network can reach the app.
   * `ALLOWED_HOSTS` (recommended): the addresses you open the app at, like
     `192.168.1.50`. The app then refuses requests for any other address.
3. Start it:
   ```
   docker compose up --build -d
   ```
4. Open `http://HOST_IP:3000` (your address) on your computer or iPhone.
   The first screen asks for your current balance and paycheck.

On your iPhone, tap **Share > Add to Home Screen** and it opens like an app.

**Help** at the top of every page explains each feature inside the app
itself, from balances and credit cards to backups and updating.

Stop it with `docker compose down`. After replacing any files with a newer
version, run step 3 again. Your data stays in the `data` folder.

**On a Mac:** keep the folder out of Desktop, Documents, and Downloads
(for example `~/checking-ledger`). macOS blocks Docker from those.

## Cloud backup (optional)

A second, separate container can send encrypted copies of your data to
cloud storage every night. It is off unless you turn it on. The app itself
still never connects to the internet and never sees the storage keys; the
backup container can read your data but cannot change it.

Everything is encrypted on your server, with a password only you have,
before it is uploaded. The storage provider receives only scrambled data.

**Set it up with Cloudflare R2:**

1. In the Cloudflare dashboard, open R2 and create a bucket, for example
   `ledger-backups`. Leave public access off.
2. In R2, open **Manage API tokens** and create a token with **Object Read
   & Write**, limited to that one bucket. Copy the Access Key ID and Secret
   Access Key. Note your Account ID from the R2 overview page.
3. On the server:
   ```
   cp backup.env.example backup.env
   chmod 600 backup.env
   nano backup.env
   ```
   Fill in the address (`s3:https://ACCOUNT_ID.r2.cloudflarestorage.com/ledger-backups/checking-ledger`),
   the two keys, and a `RESTIC_PASSWORD` of at least 20 characters.
   Keep the `s3:` at the front of the address; Cloudflare shows the
   endpoint without it. If you created the bucket in a jurisdiction (EU or
   FedRAMP), use that jurisdiction's endpoint, such as
   `https://ACCOUNT_ID.eu.r2.cloudflarestorage.com`.
4. **Save that password somewhere off the server**, such as a password
   manager. Without it, nobody can open the backups, including you.
5. Start it:
   ```
   docker compose --profile backup up -d
   ```
   To have it start with the app from now on, add `COMPOSE_PROFILES=backup`
   to `.env`.

It backs up once right away, then every day at `BACKUP_TIME`. The History
page shows when the last backup ran, and Overview shows a warning if
backups stop working.

### Backup commands

Run every command from the folder the app was set up in. Each one starts
with `docker compose --profile backup`, because the backup service is
optional and Compose ignores it without that flag. None of them can change
or delete your live `data` folder: the backup container can only read it.

**Day to day**

| Command | What it does |
|---|---|
| `docker compose --profile backup up -d` | Starts the backup service in the background. It makes one backup now, then one every day at `BACKUP_TIME`. |
| `docker compose logs backup` | Shows what the backup service has done: each backup, whether it worked, and when the next one is due. Add `-f` to keep watching; press Ctrl+C to stop watching. |
| `docker compose --profile backup run --rm backup once` | Makes one extra backup right now and exits. Useful before an update. The daily schedule carries on as before. |
| `docker compose --profile backup up -d --force-recreate backup` | Replaces the backup container so it reads a changed `backup.env` or a newer backup script. The app's container is left alone. Makes one backup straight away. |
| `docker compose --profile backup stop backup` | Stops the daily backups. Backups already in storage stay there. Start again with the first command. |

**Checking your backups**

| Command | What it does |
|---|---|
| `docker compose --profile backup run --rm backup snapshots` | Lists every backup in storage with its ID, date, and time. Changes nothing. |
| `docker compose --profile backup run --rm backup check` | Asks restic to verify that the stored backups are complete and undamaged. Changes nothing. Worth running every few months. |

**Getting data back**

| Command | What it does |
|---|---|
| `docker compose --profile backup run --rm backup restore` | Downloads and decrypts the latest backup into `restore/data/`. Your live data is not touched. |
| `docker compose --profile backup run --rm backup restore 4e0292ae` | The same, for one particular backup. Use an ID from the `snapshots` list in place of `4e0292ae`. |

In those commands, `run --rm` means "start a temporary container for this
one job and remove it afterwards". It doesn't disturb the backup service
that is already running.

A restore only fills the `restore` folder. Files already in `restore/data`
with the same names are replaced. Look at what came back
(`ls restore/data`), then put it in place yourself:

| Command | What it does |
|---|---|
| `docker compose stop ledger` | Stops the app so nothing is written while you swap files. |
| `cp -a data data-before-restore` | Keeps a copy of what you have now, in case you chose the wrong backup. |
| `cp -a restore/data/. data/` | Copies the restored files over the live ones. This is the step that changes your data. |
| `docker compose start ledger` | Starts the app again, now showing the restored ledger. |

Delete `data-before-restore` once you're happy. Do a test restore after
setting this up, so you know it works before you need it.

**On a brand-new server:** clone the repository, create `.env`, and
recreate `backup.env` with the same storage address and the same
`RESTIC_PASSWORD`. The storage keys can be new ones for the same bucket;
the password cannot be replaced. Then run the restore command and the four
copy steps above.

Any S3-compatible storage works the same way: change the address and keys.

## Updating

Your ledger (`data/`), your settings (`.env`, `backup.env`), and your cloud
backups all live outside the containers, so an update never touches them.
Run these from the folder the app was set up in:

```
git pull                          # fetch the newer files
docker compose up -d --build      # rebuild and restart the app
```

The app is unavailable for a few seconds while its container is replaced.

If you use cloud backup, restart that service too, so it runs the newer
backup script:

```
docker compose --profile backup up -d --force-recreate backup
```

What that command does: `--profile backup` includes the optional backup
service, `--force-recreate` replaces its container even if nothing looks
changed, and the final `backup` leaves the app's container alone. Nothing is
deleted. The new container makes one backup straight away, which shows the
storage settings still work. Check it with `docker compose logs backup`.

To be extra careful, make a backup before updating:
`docker compose --profile backup run --rm backup once`.

To update from a published image without building on the server, see
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## Themes

The app starts in Ember Violet, dark. Tap **Theme** at the top of any page
to pick from 14 color themes and choose light, dark, or match your device. The choice is kept in that browser, so
your phone and your computer can differ.

To change what every new browser starts with, set `THEME` (for example
`THEME=indigo`) and `THEME_MODE` (`auto`, `light`, or `dark`) in `.env` and
restart. The theme names are listed in `.env.example`.

To change a color or add a theme, edit the theme blocks at the top of
`tailwind/input.css`, list any new theme in `themes.py`, and run
`./tailwind/build.sh`. Money in stays green and money out stays red in every
theme; the theme's accent colors the buttons, links, and chart.

## Why the app listens on 0.0.0.0 inside the container

Inside the container, `0.0.0.0` means the container's own private network,
which only Docker can reach. What your network can reach is decided by
the `ports` line in `docker-compose.yml`, which publishes the app only on
`HOST_IP`. With no `.env` file it's published on `127.0.0.1`, so only the
server itself can open it.

## Privacy and security

* **Nothing leaves your network.** The app makes no outbound requests.
  Fonts, styles, and scripts are all served from the container, and the
  browser is told (Content-Security-Policy) to talk only to this server.
  The only internet use is when you build the image: Docker downloads
  Python, and pip downloads the pinned packages in `requirements.txt`.
* **Tested.** `tests/test_privacy.py` runs every page and action with
  network access blocked, scans every file the browser loads for outside
  addresses, and checks the server code has no networking calls.
* **Locked-down container.** Read-only filesystem except `data`, runs as
  your user, no Linux capabilities, no privilege escalation.
* **Password.** Sessions last 30 days; tap **Lock** to sign out of that
  browser. Changing `APP_PASSWORD` signs out every browser. Wrong passwords
  are slowed down. Every form is protected against cross-site requests.
* **Always set a password.** Without one, anything that can reach the app
  can read your ledger: another device on your network, or a web page that
  points its own domain name at your server (DNS rebinding). Setting
  `ALLOWED_HOSTS` closes the second route as well.
* **Plain HTTP.** Traffic on your Wi-Fi isn't encrypted, so someone already
  on your network could in theory read it. Don't expose port 3000 through
  your router.

## Your data

Both files live in `data/`.

**ledger.csv**, one row per entry:

| column      | meaning |
|-------------|---------|
| type        | `balance`, `recurring`, or `onetime` |
| date        | for a balance: the balance at the **start** of that day |
| amount      | negative is money out, positive is money in |
| category    | `income`, `bill`, `creditcard`, `transfer`, `investment` |
| frequency   | `weekly`, `biweekly`, `monthly`, `annually` (recurring only) |
| status      | `active` or `paused` |
| card        | on a one-time row: the id of the card this statement is for |
| close_day, due_day | on a card row: the days of the month its statement closes and payment is due |
| estimate    | on a card row: `average` (recent statements) or `fixed` (the row's amount); on a one-time row: `assumed` if it was an estimate saved by a balance update |
| pay         | on a one-time row: the id of the hourly pay this paycheck is for |
| hours, rate, percent | on a pay row: hours in a usual week, hourly rate, and starting take-home percent; `hours` on a paycheck row is the hours worked |

The `type` column can also be `card` or `pay`. A card row uses `description`
for the card's name and `amount` for its set amount. A pay row uses
`description` for its name, `date` for any one payday, and `frequency`
(`weekly`, `biweekly`, or `monthly`). Files made before these existed load
unchanged.

**networth.csv**: rows with type `account` (name, and kind `asset` or
`debt`) and rows with type `value` (date, account name, amount). Debts are
entered as the amount owed.

### Editing in Numbers or Excel

Download the file (History for the ledger, Net worth for net worth), add
or change rows, export as CSV, and upload it on the same page. The upload
**replaces everything**. Before it does, the current file is copied to
`data/backups/` (the newest 20 are kept). If any row has a problem, nothing
changes and the page lists each row number and what to fix. Dates like
`10/6/2026` and amounts like `$1,450.00` or `(25.00)` are fine.

### How balances work

A balance is what your account held at the **start** of its date.
Anything dated that same day counts on top of it, so a card payment you
add today shows on the chart and in credit card spending right away.

**Update your balance** (on Overview) records what your bank shows.
History compares it to what the ledger expected. Updating on the first day
of each quarter turns the credit card section into quarter-by-quarter
spending.

### Hourly pay

For paychecks that vary. On Transactions, add your hourly rate, the hours in
a usual week, how often you are paid, and any one payday. That is your base
pay: usual hours times rate for one pay period.

Each payday, enter your take-home (and the hours worked, if they differed).
From the last six paychecks the ledger works out what share of your earnings
you keep, and estimates every future payday as base pay times that share.
Before any paycheck is entered it uses the starting percent you gave.

### Credit cards and what-ifs

Add each card once on Transactions with the day its statement closes and
the day payment is due. Every future due date then has a payment in the
projection: the statement amount you entered, or an estimate until you
enter it. The estimate is the average of the card's last six statements or
an amount you set. Estimates appear on Overview marked "estimate".

Estimates for cards and paychecks count from your latest balance onward, so
a due date or payday you never got around to entering is still accounted
for. When you update your balance, the estimates dated before it are saved
as ordinary rows marked `assumed`. That freezes history: later changes to an
average can't alter past figures. Saved estimates are left out of future
averages.

**What if** on Overview tries a one-off amount without saving it. The chart
redraws with a dashed line showing the projection without it. "Keep it"
opens the add-transaction form filled in; "Clear" discards it.

### Coming from the earlier versions

Copy your old `data/state.json` into this `data` folder before the first
start. It's imported into `ledger.csv` once and left untouched.

## For later changes

* **Styling**: `static/app.css` is prebuilt with Tailwind. After editing
  templates, rebuild it with `./tailwind/build.sh` (needs Node, only for
  that step).
* **Tests**: `pip install -r requirements.txt pytest` then `python -m pytest`.
* **Preview**: `preview/` has its own copy of the math in JavaScript. The
  tests compare it with the Python code when Node is installed, so they tell
  you when the two drift apart. After changing styles, icons, or the Help
  text, run `python3 preview/sync.py` to copy them across.
* **Help text**: edit `templates/_help_body.html`. It is plain HTML shared
  by the app and the preview.
* **Security**: see [SECURITY.md](SECURITY.md) for what was reviewed and the
  known limits.
* **Publishing**: [docs/PUBLISHING.md](docs/PUBLISHING.md) covers releasing
  an image to a container registry.

## License

Checking Ledger is free software, licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later).
You may use, study, change and share it. If you change it and let other people
use it over a network, you must offer them your changed source code.

Copyright (C) 2026 Joseph Mennillo
