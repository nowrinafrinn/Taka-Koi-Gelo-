# Deploying Taka Koi Gelo? (Vercel + Supabase)

One Django project serves both the pages and the static files (CSS, JS,
Three.js). Vercel runs Django as a single Python function and serves static
files from its CDN. Supabase provides the PostgreSQL database.

```
Browser ──HTTPS──> Vercel CDN ── /static/* (hashed files from collectstatic)
                        │
                        └──> Vercel Function (Django, region sin1)
                                   │  transaction pooler, port 6543, SSL
                                   ▼
                          Supabase PostgreSQL (Singapore)
```

## Free-tier facts to know (checked October 2026)

| Service | Limit that matters here |
|---|---|
| Vercel Hobby | Personal, non-commercial use only. One function region. Cron jobs at most once a day, run any time within the scheduled hour. |
| Supabase Free | 500 MB database. **Paused after 1 week of inactivity** (data kept; unpause in the dashboard). **No automatic backups.** Max 2 active projects. |

A daily Vercel cron calls `/healthz/db/`, which runs `SELECT 1`. This is
meant to keep the database active, but Supabase does not promise that it
counts as activity. If the demo stops working, check whether the project
was paused.

## 1. Supabase

1. Create a project at <https://supabase.com/dashboard>.
   - Region: **Southeast Asia (Singapore)**. It must match `"regions": ["sin1"]` in `vercel.json`.
   - Save the database password in a password manager. Never paste it into a file in this repo.
2. Turn off the auto-generated REST API (Django is the only way in):
   Project Settings → Data API → disable it. The menu names may differ slightly.
3. Open **Connect** and copy two connection strings:
   - **Transaction pooler** (port **6543**): for Vercel.
   - **Session pooler** (port **5432**): for running migrations from your laptop.
     The direct connection is IPv6-only on the free plan, so use the pooler.

## 2. GitHub

Create an empty repository (no README or .gitignore) under your account, then:

```bash
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

## 3. Vercel

1. Sign in at <https://vercel.com> with GitHub and **Import** the repository.
   Vercel detects Django from `manage.py`.
2. Before the first deploy, add **Environment Variables** (Production):

| Name | Value |
|---|---|
| `DJANGO_DEBUG` | `False` |
| `DJANGO_SECRET_KEY` | a new random value (see below) |
| `DATABASE_URL` | Supabase **transaction pooler** URL (port 6543) |
| `DB_SSL_REQUIRE` | `True` |
| `CRON_SECRET` | another new random value |

   Generate random values locally, one per variable:

   ```bash
   .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

   `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are filled automatically from
   Vercel's `VERCEL_*` system variables. Only set `DJANGO_ALLOWED_HOSTS`
   if you add a custom domain.

3. Deploy. During the build Vercel installs `requirements.txt` with Python
   3.13 (`.python-version`) and runs `collectstatic` automatically.

## 4. Create the tables (run once, and after every new migration)

From your laptop, in PowerShell, with the **session pooler** URL. These
variables last only for this terminal window, and real environment
variables override `.env`:

```powershell
$env:DATABASE_URL = "<session pooler URL>"
$env:DB_SSL_REQUIRE = "True"
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py createsuperuser   # optional, for /admin/
```

Close the terminal afterwards so the production URL isn't reused by accident.

## 5. Verify

- `https://<project>.vercel.app/healthz/` returns `ok` (the app is running).
- `https://<project>.vercel.app/healthz/db/` returns `unauthorized`. That's
  correct: only Vercel Cron, which sends the secret, gets `ok`.
- Sign up, add income and an expense, set a budget, check the dashboard and the 3D wallet.
- In Vercel → Project → Settings → Cron Jobs, run the job once and check its log shows `200`.

After a few days with no problems, raise `DJANGO_HSTS_SECONDS` (e.g. to
`31536000`, one year).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `DisallowedHost` / 400 | Custom domain not in `DJANGO_ALLOWED_HOSTS` |
| 403 CSRF on forms | Custom domain not in `DJANGO_CSRF_TRUSTED_ORIGINS` (with `https://`) |
| 500 on every page, logs mention the database | Wrong `DATABASE_URL`, missing `DB_SSL_REQUIRE=True`, or the Supabase project is paused |
| `relation "auth_user" does not exist` | Migrations not run against Supabase (step 4) |
| `prepared statement ... does not exist` | Should not happen: prepared statements are disabled in settings |
