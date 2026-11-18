# Railway setup (easy mode)

**You need 4 things in Railway:**

1. Postgres (database)  
2. Redis (job queue)  
3. **Backend** — API + backtest worker in **one** service  
4. **Frontend** — the website  

No separate worker service. No beat service.

Use the GitHub branch that has this repo’s Railway files (e.g. `cursor/prop-edge-ai-foundation-3c6d` or `main` after merge).

---

## Part A — Project and databases

### Step 1 — Connect GitHub

1. Go to [railway.com](https://railway.com) and log in.  
2. **New Project** → **Deploy from GitHub repo**.  
3. Choose your **Backtest** repo.  

### Step 2 — Add Postgres

1. In the project, click **+ New**.  
2. Choose **Database** → **PostgreSQL**.  
3. Wait until it shows as running.

### Step 3 — Add Redis

1. Click **+ New** again.  
2. Choose **Database** → **Redis**.  
3. Wait until it shows as running.

You already linked `DATABASE_URL` and `REDIS_URL` — good. The names below are what the app expects.

---

## Part B — Backend (one service)

### Step 4 — Create the backend service

1. Click **+ New** → **GitHub Repo** → same **Backtest** repo.  
2. Click the new service to open it.  
3. Open **Settings**.

Set exactly:

| Setting | Value |
|---------|--------|
| **Root Directory** | `backend` |
| **Config file** | `railway.toml` |

If there is no “Config file” box, set **Custom Start Command** to:

```bash
bash scripts/railway-start-simple.sh
```

4. Under **Source** (or **Deploy**), pick the branch that contains `backend/railway.toml`.

### Step 5 — Backend variables

Open **Variables** on this **backend** service.

**Link from plugins (recommended):**

1. Click **+ New Variable** → **Add reference** (or “Variable from service”).  
2. From **Postgres**, add `DATABASE_URL`.  
3. From **Redis**, add `REDIS_URL`.

**Type these yourself:**

| Variable name (copy exactly) | What to enter |
|--------------------------------|---------------|
| `SECRET_KEY` | Any long random string (32+ characters) |
| `INITIAL_ADMIN_EMAIL` | Your login email |
| `INITIAL_ADMIN_PASSWORD` | Your login password |
| `ENVIRONMENT` | `production` |

Important:

- The password variable must be named **`INITIAL_ADMIN_PASSWORD`**.  
- Names like `pass-word` or `password` will **not** work.

5. Click **Deploy** / wait for deploy to finish.

### Step 6 — Backend public URL

1. Open **Networking** on the backend service.  
2. Click **Generate Domain**.  
3. Copy the URL, e.g. `https://backtest-production-xxxx.up.railway.app`.

**Test it:** open `https://YOUR-BACKEND-URL/health` in a browser.  
You should see JSON with `"status":"ok"`.

**Write this down — call it your API URL.**

---

## Part C — Frontend (website)

### Step 7 — Create the frontend service

1. **+ New** → **GitHub Repo** → same repo again.  
2. Open **Settings**:

| Setting | Value |
|---------|--------|
| **Root Directory** | `frontend` |
| **Config file** | `railway.toml` |

Same branch as backend.

### Step 8 — Frontend variable (required)

On the **frontend** service → **Variables**:

| Variable name | Value |
|---------------|--------|
| `BACKEND_INTERNAL_URL` | Your **API URL** from Step 6 (must start with `https://`) — preferred |
| `NEXT_PUBLIC_API_URL` | Same URL (optional if `BACKEND_INTERNAL_URL` is set) |

Example: `https://backtest-production-xxxx.up.railway.app`

Deploy the frontend. It may take a few minutes to build.

### Step 9 — Frontend public URL

1. **Networking** → **Generate Domain**.  
2. Copy the URL — this is what you open in the browser daily.

### Step 10 — Allow the website to talk to the API

Browsers block the site unless the API allows your frontend URL.

1. Go back to the **backend** service → **Variables**.  
2. Add:

| Variable name | Value |
|---------------|--------|
| `ALLOWED_ORIGINS` | Your **frontend URL** from Step 9 (exactly, with `https://`) |

3. **Redeploy** the backend (Deployments → Redeploy).

---

## Part D — Use the app

1. Open your **frontend URL**.  
2. Log in with:  
   - Email = `INITIAL_ADMIN_EMAIL`  
   - Password = what you put in `INITIAL_ADMIN_PASSWORD`  
3. **Market Data** → upload a CSV of OHLCV data.  
4. **Backtest Laboratory** → pick a strategy and dataset → queue a backtest.

---

## Quick checklist

- [ ] Postgres + Redis in project  
- [ ] Backend: root `backend`, config `railway.toml`  
- [ ] `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD`  
- [ ] Backend domain works: `/health`  
- [ ] Frontend: root `frontend`, `NEXT_PUBLIC_API_URL` = backend domain  
- [ ] Backend: `ALLOWED_ORIGINS` = frontend domain, backend redeployed  
- [ ] Login works  

---

## If something breaks

| Problem | What to do |
|---------|------------|
| `/health` does not load | Backend **Deploy Logs** — usually wrong root directory or branch without `railway.toml` |
| Login fails | Check `INITIAL_ADMIN_PASSWORD` spelling; redeploy backend |
| Login says **recovery mode** / API 502 | Postgres crash-recovered after DiskFull. Open the **Postgres** plugin → **Restart**. Wait until Running. Increase the volume. Then sign in again. |
| “CORS” / network error in browser | `ALLOWED_ORIGINS` must match frontend URL exactly; redeploy backend |
| Backtest stuck on “queued” | Redeploy backend — worker runs inside the same service (check logs for “celery”) |
| Build fails on frontend | `NEXT_PUBLIC_API_URL` must be set **before** or redeploy after adding it |

---

## Optional later

- **OHLCV volume (recommended):** bars live as parquet files, not Postgres rows. On the backend service add a volume mounted at `/data` and set `OHLCV_STORE_DIR=/data/ohlcv` so history survives deploys. Without it, search re-downloads after a rebuild — that is still better than filling the Postgres disk.  
- **FinzData:** add `FINZDATA_API_KEY` on the backend. Free plan is daily bars; 1m/5m search needs a paid market, otherwise Yahoo is used.  
- **Databento:** add `DATABENTO_API_KEY` on the backend.  
- **Full split deploy** (separate worker): see [DEPLOY_RAILWAY.md](./DEPLOY_RAILWAY.md).

This easy guide is the default in [README.md](../README.md).