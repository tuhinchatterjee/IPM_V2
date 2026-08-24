# Setting up the CreditProbe Tool on a new Windows PC

A complete, start-to-finish guide for someone who has never run this project
before. Every command is typed into **Windows Terminal**. You do not need to
understand the code to get it running.

When you are done, the app is at **http://localhost:8050** and you sign in with a
username and password you create in step 5.

---

## First: open Windows Terminal

1. Press the **Windows key**, type `Terminal`, press **Enter**.
2. You get a blue-ish window with a prompt like `PS C:\Users\yourname>`. That is
   PowerShell — every command below goes there.
3. Copy a command from this page, right-click in the terminal to paste, press
   **Enter**.

> A command that prints nothing usually means it worked. Windows only speaks up
> when something goes wrong.

---

## Choose one of two routes

| | **Route A — Docker** | **Route B — Python + PostgreSQL** |
|---|---|---|
| Best for | just running the app | editing the code, running tests |
| You install | Docker Desktop, Git | Python 3.14, PostgreSQL 16, Git |
| Database | included, set up automatically | you install and configure it |
| Time | ~20 minutes | ~40 minutes |

**If you are not sure, pick Route A.** It has fewer moving parts and sets up its
own database. You can always add Route B later.

---

# Route A — Docker (recommended)

## A1. Install Docker Desktop and Git

```powershell
winget install -e --id Docker.DockerDesktop
winget install -e --id Git.Git
```

Then **restart the PC** (Docker needs it), and after logging back in, start
**Docker Desktop** from the Start menu. Wait until the whale icon in the bottom
status bar says *Engine running*. Leave it running.

Open a **new** Windows Terminal and check both tools are ready:

```powershell
docker version
git --version
```

If `docker version` says *error during connect*, Docker Desktop is not started
yet — open it and wait for the whale.

## A2. Download the code

```powershell
cd $HOME\Documents
git clone https://github.com/AFS-Advisory/IPM_V2.git
cd IPM_V2
```

Everything from here on is run **from inside this folder**. If you open a fresh
terminal later, `cd $HOME\Documents\IPM_V2` first.

## A3. Create your configuration file

```powershell
Copy-Item .env.example .env
```

Now add the two values Docker needs. These commands generate a random password
and a random session key and append them to the file:

```powershell
Add-Content .env "POSTGRES_PASSWORD=$(-join ((1..24) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }))"
Add-Content .env "SECRET_KEY=$(-join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) }))"
```

You never need to read or remember these. `SECRET_KEY` keeps people signed in
across restarts; without it everyone is logged out every time the app restarts.

**Optional — the AI assistant.** Open `.env` in Notepad (`notepad .env`) and put a
real key on the `ANTHROPIC_API_KEY=` line. The app runs perfectly well without
one; only the AI chat panel is unavailable.

## A4. Start everything

```powershell
docker compose up -d --build
```

The first run takes about 5 minutes — it downloads a Python image and a
PostgreSQL image and installs all the libraries. Later runs take seconds.

This one command builds the app, starts PostgreSQL, creates the database tables,
loads the bundled portfolio workbook, and starts the app.

Watch it come up:

```powershell
docker compose ps
```

Wait until the `app` line shows **(healthy)**. That can take about 30 seconds
after the build finishes.

## A5. Create your login

```powershell
docker compose exec app python scripts/manage_users.py add admin --role admin
```

It asks you to type a password twice (nothing appears as you type — that is
normal). Remember this one; it is how you sign in.

## A6. Open the app

Go to **http://localhost:8050** and sign in.

## Route A — everyday use

```powershell
cd $HOME\Documents\IPM_V2

docker compose up -d        # start
docker compose down         # stop
docker compose logs -f app  # watch what it is doing (Ctrl+C to stop watching)
```

After pulling new code (`git pull`), rebuild with
`docker compose up -d --build`.

---

# Route B — Python + PostgreSQL

Use this if you intend to edit the code or run the tests.

## B1. Install Python, PostgreSQL and Git

```powershell
winget install -e --id Python.Python.3.14
winget install -e --id PostgreSQL.PostgreSQL.16
winget install -e --id Git.Git
```

The PostgreSQL installer asks you to **set a password for the `postgres`
superuser** — write it down, you need it in step B4. Accept the default port
(5432) and skip Stack Builder at the end.

**Close Windows Terminal and open a new one** so it picks up the new programs,
then check:

```powershell
python --version    # must say 3.14.x
git --version
```

> The project requires Python **3.14**. An older Python will fail to install the
> dependencies.

## B2. Download the code

```powershell
cd $HOME\Documents
git clone https://github.com/AFS-Advisory/IPM_V2.git
cd IPM_V2
```

## B3. Install the libraries

Into a private folder (`.venv`) so this project cannot disturb anything else on
your PC:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Takes a few minutes. Note the `.\.venv\Scripts\python.exe` form — using it
directly avoids Windows' script-blocking policy, so you never have to "activate"
anything.

## B4. Create the database

`psql` is not on the PATH after installing PostgreSQL, so point at it for this
session:

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\16\bin"
```

Create a login and a database — replace `PICK-A-PASSWORD` with something of your
own, and keep it:

```powershell
psql -U postgres -c "CREATE ROLE ipm_app WITH LOGIN PASSWORD 'PICK-A-PASSWORD';"
psql -U postgres -c "CREATE DATABASE ipm OWNER ipm_app;"
```

Both prompt for the **postgres superuser password** from step B1.

## B5. Create your configuration file

```powershell
Copy-Item .env.example .env
notepad .env
```

In Notepad, make sure these two lines exist, are **not** commented out with `#`,
and use the password you chose in B4:

```
DATABASE_URL=postgresql+psycopg://ipm_app:PICK-A-PASSWORD@localhost:5432/ipm
SECRET_KEY=paste-the-value-printed-below
```

Save and close. Generate the secret key with:

```powershell
-join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
```

`ANTHROPIC_API_KEY` is optional — see the note in A3.

## B6. Create the tables and load the data

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\migrate_xlsx_to_pg.py
```

The second command should end with something like
`Seeded active dataset version 1: 10 quarters, 6,988 rows across 11 sheets.`
Both are safe to run again; they do nothing if already done.

## B7. Create your login

```powershell
.\.venv\Scripts\python.exe scripts\manage_users.py add admin --role admin
```

## B8. Start the app

```powershell
.\.venv\Scripts\python.exe app.py
```

Leave this window open — closing it stops the app. Open
**http://localhost:8050** and sign in.

Stop the app with **Ctrl+C** in that window.

## Route B — everyday use

```powershell
cd $HOME\Documents\IPM_V2

.\.venv\Scripts\python.exe app.py              # run the app
.\.venv\Scripts\python.exe -m pytest           # run the tests
.\.venv\Scripts\python.exe -m ruff check .     # lint

git pull                                                     # after new code:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
```

---

## Signing in

The first page is always a **login screen** — that is not an error, every page is
behind authentication. Use the username and password you created.

Add more people later:

```powershell
# Route A
docker compose exec app python scripts/manage_users.py add jane --role analyst
# Route B
.\.venv\Scripts\python.exe scripts\manage_users.py add jane --role analyst
```

Roles are `admin` or `analyst`. Other commands: `list`, `reset-password`,
`set-role`, `disable`, `enable`.

---

## When something goes wrong

**`RuntimeError: DATABASE_URL is not configured`**
The app cannot find its database setting. Route B: check `.env` has a
`DATABASE_URL=` line that is not commented out with a `#`. Route A: run
`docker compose up -d`, not a bare `docker run` — a plain `docker run` passes no
settings at all.

**A container fails to reach the database even though `.env` looks right**
Inside a container, `localhost` means *the container itself*, not your PC. The
database host has to be `host.docker.internal`. `docker compose` and
`scripts\app-start.ps1` both handle this for you; a hand-written `docker run`
does not.

**`Bind for 0.0.0.0:8050 failed: port is already allocated`**
Something is already using port 8050 — usually the app already running. Stop it
(`docker compose down`, or Ctrl+C in the window running `app.py`), or publish
elsewhere with `docker compose up -d` after setting `PORT=8060` in `.env`.

**`psql : The term 'psql' is not recognized`**
PostgreSQL's tools are not on the PATH. Run the `$env:Path += ...` line from
step B4 again — it only lasts for the current terminal window.

**`... cannot be loaded because running scripts is disabled on this system`**
Windows is blocking a PowerShell script. Either use the
`.\.venv\Scripts\python.exe` form shown throughout Route B, or prefix the
command: `powershell -ExecutionPolicy Bypass -File scripts\app-start.ps1`.

**`ModuleNotFoundError: No module named ...`**
The libraries are missing or you used the wrong Python. Re-run
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and make sure you
are calling `.\.venv\Scripts\python.exe`, not a bare `python`.

**`password authentication failed for user "ipm_app"`**
The password in `.env`'s `DATABASE_URL` does not match the one used in step B4.

**`error during connect` from any docker command**
Docker Desktop is not running. Start it and wait for *Engine running*.

**The page just shows a login box**
That is correct behaviour. If you have no account, create one (A5 / B7).

---

## What lives where

| | |
|---|---|
| Your settings and secrets | `.env` (never committed to git) |
| Portfolio data, users | PostgreSQL — not in the project folder |
| Application log | `logs/ipm.log` (Route A: `docker compose logs app`) |
| Uploaded workbooks | `uploads/`, or the `uploads` Docker volume |
| Bundled starter dataset | `Portfolio_Monitoring_Dataset.xlsx` (synthetic) |

`docker compose down` and `app-stop.ps1` never delete your data. Only
`docker compose down -v` does — the `-v` wipes the database volume.

---

## Going further

- **[README.md](README.md)** — what the app does and how the code is organised.
- **[docs/deploy.md](docs/deploy.md)** — production: running as a Windows service,
  LAN access, backups, secret rotation, and the Docker options in §11.
