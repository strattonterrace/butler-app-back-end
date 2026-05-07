# Butler — Backend (Phase 2)

Django 5 + DRF + JWT + PostgreSQL API powering the Butler concierge platform.

Frontend lives in a sibling repo (the existing `frontend/` Vite app on Vercel).
This service is deployed to **Render** (web service + managed Postgres).

---

## Milestone 1 scope

> Server setup · database architecture · authentication fully functional

Locked in:

- Django project + 6 apps (`accounts`, `territories`, `subscriptions`, `requests`, `drivers`, `notifications`)
- All database tables modelled with migrations
- UUID-based custom `User` model with role + status enums
- JWT auth via `djangorestframework-simplejwt` (15-min access, 7-day refresh, blacklist on logout)
- Endpoints live in M1: `register`, `login`, `token/refresh`, `logout`, `password-reset`, `password-reset/confirm`, `users/me`, admin user management, `users/create-operator`
- Role-based permission classes (Client / Operator / Driver / Admin / AdminOrOperator / etc.)
- Render-ready: `Procfile`, `runtime.txt`, gunicorn, whitenoise, dj-database-url

Stripe (M2), email automation + frontend wire-up (M3) are **not** built yet.
Their schema is in place — the hooks just aren't pulled.

---

## Local dev — quickstart

```bash
cd backend

# 1. Virtual env
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 2. Install
pip install -r requirements-dev.txt

# 3. Env file
cp .env.example .env
# Edit DATABASE_URL if you're not running Postgres on localhost:5432

# 4. Database (need a running Postgres)
createdb butler_dev               # or use pgAdmin / psql

# 5. Migrate + create a superuser
python manage.py migrate
python manage.py createsuperuser

# 6. Run
python manage.py runserver
# → http://localhost:8000/healthz/  → {"status": "ok"}
```

The Vite frontend's API base URL should point at `http://localhost:8000/api/v1`.

---

## Tests

```bash
pytest                          # all
pytest -m unit                  # fast, no DB
pytest -m integration           # API + DB
pytest -m edge_case             # error paths only
pytest --cov=apps --cov=utils   # with coverage
```

`tests/` is organised by app — `tests/accounts/`, `tests/integration/`, plus
a `test_models_smoke.py` that catches missing migrations.

---

## Project layout

```
backend/
├── manage.py
├── requirements.txt
├── requirements-dev.txt
├── runtime.txt
├── Procfile
├── pytest.ini
├── .env.example
│
├── butler_api/                # Django project
│   ├── settings/{base,development,production}.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── apps/
│   ├── accounts/              # User + JWT auth (M1 fully wired)
│   ├── territories/           # Territory model (M1 schema)
│   ├── subscriptions/         # Subscription model (M1 schema, Stripe in M2)
│   ├── requests/              # ServiceRequest + StatusHistory (M1 schema, lifecycle in M3)
│   ├── drivers/               # DriverProfile (M1 schema, app/approval in M3)
│   └── notifications/         # Email service stubs (real wire in M3)
│
├── utils/
│   ├── pagination.py          # StandardPagination (page=1..N)
│   ├── exceptions.py          # Uniform error envelope
│   └── helpers.py
│
└── tests/                     # Top-level — mirrors apps/
    ├── conftest.py
    ├── factories.py
    ├── accounts/
    ├── territories/
    ├── subscriptions/
    ├── requests/
    ├── drivers/
    └── integration/
```

---

## API — endpoints live in M1

```
GET  /healthz/                          → load-balancer probe

POST /api/v1/auth/register/             → 201 + { access, refresh, user }
POST /api/v1/auth/login/                → 200 + { access, refresh, user }
POST /api/v1/auth/token/refresh/        → 200 + { access }
POST /api/v1/auth/logout/               → 204 (blacklists refresh)
POST /api/v1/auth/password-reset/       → 200 (timing-safe)
POST /api/v1/auth/password-reset/confirm/ → 200

GET    /api/v1/users/me/                → current user
PATCH  /api/v1/users/me/                → update full_name, phone, avatar_url

GET    /api/v1/users/                   → admin: list users (filter: role, status, territory)
GET    /api/v1/users/<uuid>/            → admin: detail
PATCH  /api/v1/users/<uuid>/            → admin: update role/status/territory
POST   /api/v1/users/create-operator/   → admin: create operator account
```

Subscription, request lifecycle, driver application, and admin metrics
endpoints land in **M2/M3**.

---

## Deployment to Render (when Ryan sends login)

1. **Create services** in the Render dashboard:
   - PostgreSQL → `butler-db` (Starter plan, Oregon region)
   - Web Service → `butler-api`, point at this repo, build dir `backend/`

2. **Build command** (Render):
   ```
   pip install -r requirements.txt && python manage.py collectstatic --noinput
   ```

3. **Start command** (Render uses Procfile; equivalent below):
   ```
   gunicorn butler_api.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 60
   ```

4. **Environment variables** (set in Render dashboard):
   - `DJANGO_SETTINGS_MODULE` = `butler_api.settings.production`
   - `SECRET_KEY` = generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`
   - `DEBUG` = `False`
   - `ALLOWED_HOSTS` = `butler-api.onrender.com` (or custom domain when set)
   - `DATABASE_URL` = wire to the linked Postgres service
   - `CORS_ALLOWED_ORIGINS` = `https://<vercel-frontend-url>`
   - `JWT_ACCESS_TOKEN_LIFETIME_MINUTES` = `15`
   - `JWT_REFRESH_TOKEN_LIFETIME_DAYS` = `7`
   - `FRONTEND_URL` = `https://<vercel-frontend-url>`
   - Stripe + Resend + Cloudinary keys go in at M2 / M3.

5. **Release command** (auto-runs migrations on deploy):
   ```
   python manage.py migrate --noinput
   ```

6. After first deploy:
   ```
   python manage.py createsuperuser   # via Render Shell tab
   ```

---

## M1 verification checklist

Before signing off M1 with Ryan:

- [ ] `python manage.py migrate` runs cleanly against a fresh Postgres
- [ ] `pytest` is green (auth, permissions, models smoke)
- [ ] `GET /healthz/` returns `{"status": "ok"}`
- [ ] Register → Login → Refresh → Logout flow works end-to-end via curl
- [ ] An admin can create an operator via `/api/v1/users/create-operator/`
- [ ] Admin user cannot self-suspend (returns `ADMIN_CANNOT_SELF_SUSPEND`)
- [ ] Service deployed to Render with HTTPS
- [ ] Render database connection verified (`/api/v1/users/me/` after login)
- [ ] Suspended account cannot log in
- [ ] CORS allows the Vercel frontend origin only

Once those pass — M1 is delivered, M2 (Stripe) starts.
