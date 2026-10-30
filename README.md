# Taka Koi Gelo? · টাকা কই গেলো?

> *"Where did the money go?"* Know where your money goes, before it disappears.

A full-stack expense manager for university students in Bangladesh. Track
income and spending in taka (৳), set a monthly budget, save towards goals, and
see where the money went, with an interactive **3D wallet** driven by your real
figures.

**Live demo:** <https://taka-koi-gelo.vercel.app> (free hosting, so the first
request after a quiet period can be slow)

## Why I built it

Students here often juggle pocket money, private tuition and part-time work,
then spend it in small amounts on food, rickshaws and recharge. By the end of
the month the question is always *taka koi gelo?* Generic trackers feel like
accounting software, so this one is built to be quick on a phone and honest
about the numbers.

## Key features

- **Income and expenses:** categories, payment methods including bKash, Nagad and Rocket, filters and pagination.
- **Dashboard:** total balance split into saved and spendable, safe-to-spend per day, budget progress and a spending pace chart.
- **Savings goals:** add or take out money, capped at what you actually have.
- **Insights:** month and year charts, a daily calendar view, day-by-day pages and a rule-based spending report.
- **3D wallet:** a Three.js scene that reflects your balance and budget, with an SVG fallback when WebGL isn't available.
- **Mobile first:** bottom tab bar, light and dark mode, WCAG AA contrast, and lakh-style number formatting (৳1,23,456.50).

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.13, Django 5.2 LTS |
| Database | PostgreSQL 17 (Supabase in production) |
| Frontend | Django templates, hand-written CSS, vanilla JavaScript |
| 3D | Three.js |
| Hosting | Vercel, Supabase |

Developed with help from Claude Code, an AI pair-programming assistant, used
for implementation and review under my direction at each stage.

## Engineering highlights

- **Accurate money:** `Decimal` from the database to the template. All calculations live in a service layer and run on the server; JavaScript never calculates money.
- **Efficient queries:** totals are computed in the database, so the cost of the main summary doesn't grow with the number of records.
- **Security:** every query is scoped to the signed-in user, so another user's record returns 404. CSRF protection on every form, with secrets kept in environment variables and hardened production settings.
- **Works without JavaScript:** figures and charts are rendered by the server. The 3D wallet and in-place switching are enhancements on top.
- **Tested:** 357 automated tests with 99% line coverage, including access control, date boundaries and Decimal precision.

## Run it locally

Requires Python 3.13, Git and Docker Desktop.

```powershell
git clone https://github.com/nowrinafrinn/Taka-Koi-Gelo-.git
cd Taka-Koi-Gelo-
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
docker compose up -d
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8010
```

Open <http://127.0.0.1:8010>. Run the tests with
`.venv\Scripts\python.exe manage.py test`.

Deployment notes are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Credits

[Three.js](https://threejs.org) (MIT licence). Fonts: Bricolage Grotesque, Hind Siliguri and Galada, via Google Fonts.
