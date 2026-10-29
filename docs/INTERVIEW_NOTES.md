# Interview notes: Taka Koi Gelo?

Short, honest answers you can say out loud. Each one points to the file to
open if the interviewer wants to see code.

---

## 30-second pitch

> "Taka Koi Gelo? means *where did the money go?* It's an expense manager
> for students in Bangladesh: pocket money, tuition income, small daily
> spending, all in taka. I built it with Django and PostgreSQL. The dashboard
> shows an all-time balance, this month's totals, a budget with warnings,
> and spending by category. The signature feature is a Three.js wallet that
> reflects the user's real data, while every figure is still plain
> server-rendered HTML. It has 147 tests at 98% coverage, strict per-user
> data isolation, and it's deployed on Vercel with Supabase."

---

## 1. Why Django?

- **It includes what this app needs:** authentication, sessions, CSRF protection, an ORM with migrations, forms with validation, an admin, and template rendering. With FastAPI I'd have assembled those myself (SQLAlchemy + Alembic, an auth library, a template engine, CSRF handling).
- **Server-rendered pages suit the product.** It's form-heavy CRUD plus a dashboard. One Django project serves the HTML and the static files, so there's no separate frontend, no API layer, and no CORS.
- **The Django 5.2 LTS release** is supported until 2028.
- *Trade-off:* for a public JSON API or a mobile app, I'd add Django REST Framework, or use FastAPI for a pure API.

## 2. How do the models relate?

*(`finance/models.py`)*

- **`User` 1→many `Transaction` and 1→many `MonthlyBudget`.** These are `ForeignKey`s with `on_delete=CASCADE`.
- **One `Transaction` table holds both income and expenses**, with a `kind` field. That keeps the balance, the recent list and the filters to single queries.
- **Categories are fixed choices that depend on the kind.** `clean()` rejects a "Food" income or a "Tuition" expense. Payment method is required for expenses and optional for income (tuition is often paid through bKash).
- **`MonthlyBudget` stores one row per user per calendar month.** The month is normalised to the 1st, and a `UniqueConstraint` covers (user, month). Changing this month's budget therefore never rewrites history.
- **Two layers of validation:** model validation gives friendly form errors, and **database constraints** (`CHECK amount > 0`, `UNIQUE`) are the last line of defence, because `save()` doesn't run validation.

## 3. How do authentication and ownership checks work?

*(`finance/views.py`, `accounts/`)*

- **Django's built-in auth:** hashed passwords (PBKDF2), password validators, session cookies (HttpOnly; Secure in production), and POST-only logout.
- **Login required everywhere:** every finance view has `@login_required`, which plays the role of `Depends(get_current_user)` in FastAPI.
- **All queries are scoped to the user.** Lists start from `request.user.transactions`. Single records only load through one helper:
  ```python
  get_object_or_404(Transaction, pk=pk, user=request.user)
  ```
  Another user's ID gives **404, not 403**, so an attacker can't even learn that it exists.
- **Server-trusted fields:** `user` and `kind` are never form fields. Kind comes from the URL and the owner from the session. A test posts a tampered form with someone else's user ID, and the record is still saved as the logged-in user's.
- **CSRF tokens on every POST.** Tests send each state-changing form without a token and expect 403.

## 4. How are financial calculations done?

*(`finance/services.py`)*

- **A service layer:** views only pass requests through, templates only display, and `services.py` does the math. That made it easy to unit-test with a fixed "today".
- **`Decimal` everywhere.** The database does the sums, and `money()` turns "no rows" (`None`) into `0.00` and rounds to 2 places. No floats are used for money. One test checks that 1,000 × ৳0.10 = exactly ৳100.00.
- **Four queries for the whole dashboard, at any data size:**
  1. one `aggregate()` with **conditional sums** for all-time income and expenses, this month's income and expenses, and the expense count;
  2. a `GROUP BY` category;
  3. the budget;
  4. the recent rows.

  A test locks the count at 4.
- **Definitions are written down and labelled in the UI.** The balance is all-time; "this month" is the calendar month in **Asia/Dhaka**, judged by each transaction's own date; budget remaining can be negative.
- **A bug I caught:** ৳3,999.99 of ৳5,000 is 79.9998%. It *displays* as 80.0%, but it hasn't really reached the warning. The warning now uses the exact comparison `spent × 100 ≥ limit × 80`, not the rounded number.

## 5. How does Three.js integrate with Django?

*(`templates/finance/dashboard.html`, `static/js/wallet.js`)*

- **Progressive enhancement:** Django renders all figures plus an SVG wallet. `wallet.js` replaces the SVG with a canvas only if WebGL works.
- **No build step:** an **import map** maps `import 'three'` to a self-hosted, version-pinned copy in `static/vendor/`. In production, hashed filenames (`ManifestStaticFilesStorage`) bust the cache.
- **Data handoff:** `services.wallet_visuals()` turns real figures into a few *visual-only* values: a coin count from the balance band, a stack count from this month's expenses, a budget-ring fraction (sent as a string, not a float) and a one-time event. These are embedded with `json_script`, then validated and clamped again in JS.
- **Animations can't lie about a save.** A session flag is set only after `form.save()` succeeds, and the dashboard reads it with `session.pop()`, so it plays once. Failed forms, edits and deletes never set it. Tests cover each case.
- **Performance and accessibility:**
  - procedural geometry, no model files;
  - pixel ratio capped at 2, low-power GPU hint;
  - the loop pauses off screen and in hidden tabs;
  - a still frame under `prefers-reduced-motion`;
  - falls back to the SVG if WebGL is unavailable or the context is lost.

## 6. How is it tested?

- **147 Django tests, 98% line coverage** (`coverage.py`). The uncovered lines are production-only settings, which `manage.py check --deploy` verifies.
- **What's covered:**
  - calculations: empty data, zero values, overspending, Decimal precision, month boundaries, leap years, the Dhaka-midnight case;
  - access control and CSRF;
  - form validation, filters, pagination;
  - output escaping (`<script>` in a note);
  - the wallet data and the "animate once, only on success" rule;
  - health checks, error pages and security headers.
- **Tests run against PostgreSQL** (Docker), the same engine as production.
- **Beyond automated tests:** browser checks at 375 px for overflow and console errors, WCAG contrast computed for every text and background pair, `pip-audit` for dependencies, and a local production simulation (`DEBUG=False` with hashed static files) before deploying.

## 7. How does deployment work?

*(`vercel.json`, `pyproject.toml`, `docs/DEPLOYMENT.md`)*

- **Push to `main` → Vercel builds:** it installs pinned dependencies with Python 3.13, runs `collectstatic` (hashed files go to the CDN), and runs a **build hook** that executes `manage.py migrate` against Supabase. Django runs as one Vercel Function in Singapore, next to the database.
- **Database connections suit serverless:** Supabase's **transaction pooler**, `CONN_MAX_AGE=0`, prepared statements and server-side cursors disabled, and SSL required.
- **Configuration is all environment variables;** `DEBUG` defaults to off. A daily **Vercel Cron**, authenticated with a Bearer secret, hits `/healthz/db/`.
- **What went wrong and how I fixed it:**
  1. Production 500s weren't visible, because Django only logs tracebacks when `DEBUG` is on. I added explicit logging.
  2. The logs then showed `relation "auth_user" does not exist`: the manual migration had gone to the local database. I moved migrations into the deploy pipeline, so code and schema can't drift apart and nobody copies the database password around.

## 8. What would you improve next?

1. **Security:** login rate limiting, password reset by email, and a CSP header with nonces.
2. **Product:** recurring transactions (monthly pocket money), custom categories, comparison with last month, CSV export.
3. **Data:** separate preview and production databases, so preview deploys can't migrate production; regular backups.
4. **Frontend:** a minified, tree-shaken Three.js bundle; an installable PWA for quick entry on phones.
5. **CI:** GitHub Actions running the tests and `check --deploy` on every push.

---

## Likely follow-up questions

- **"Why one table for income and expenses?"** Fewer queries and one set of access checks. The kind-specific rules live in `clean()` and the form.
- **"Why 404 instead of 403?"** A 403 confirms the record exists; a 404 reveals nothing.
- **"Why not compute totals in JavaScript?"** The client isn't trusted and floats aren't safe for money. The server is the single source of truth, and JS only draws.
- **"How do you stop the animation replaying on refresh?"** Post/Redirect/Get, plus `session.pop()` reading the flag exactly once.
- **"What happens if Supabase is down?"** Pages return the custom 500 page (no details leak), and `/healthz/db/` returns 503. The error is logged in Vercel.
- **"Did you use AI?"** Yes. I built it with Claude Code as a pair programmer, stage by stage. I made the architecture decisions, reviewed and ran every change, and can explain each part, as above.
