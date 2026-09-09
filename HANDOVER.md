# Bubbl.ooo — Project Handover (Start Here)

> **Purpose:** the single "start here" reference for whoever takes ownership of Bubbl. It covers what the
> system is, what's live, how to set it up, how to run and maintain it day to day, what to hand over
> (access/accounts), reports, and known issues. For the exhaustive deep-dive (funnel, every route,
> psychology hooks, full schema), see **`PROJECT.md`**.
>
> **Outgoing owner:** Tushar Gautam (Drish Infotech)
> **Handover date:** _fill in_
> **New owner / maintainer:** _fill in_

---

## 0. Handover Checklist (tick these off on the KT call)

Access is not "handed over" until the new owner can log in **without** the previous owner's help.

- [ ] **GitHub repo access** — new maintainer added as a collaborator on the private repo (`kchecker/bubblooo`). A shared link is **not** access.
- [ ] **Deploy PAT** — the fine-grained GitHub Personal Access Token stored on the server for `git pull` deploys is reissued under the new owner and the old one revoked (see §6).
- [ ] **Server (DigitalOcean droplet)** — SSH access confirmed by the new owner (`root@168.144.123.62`); **root password rotated** after they're in (the old password was shared over chat → treat as compromised).
- [ ] **Database (NeonDB / PostgreSQL)** — new owner invited to the Neon project; not just handed the `DATABASE_URL`.
- [ ] **Domain / DNS** — control of `bubbl.ooo` (registrar + DNS) transferred.
- [ ] **Gemini (Google AI Studio)** — API key ownership + billing confirmed.
- [ ] **Firecrawl** — API key ownership + billing confirmed.
- [ ] **Gmail SMTP** — sender account + app password ownership confirmed.
- [ ] **Paddle (payments)** — account access, API key, webhook secret, and the production price IDs transferred.
- [ ] **Google OAuth** — client ID/secret + the Google Cloud project that owns them transferred.
- [ ] **Analytics** — GA4, Meta Pixel, Microsoft Clarity property/account access transferred.
- [ ] **Super Admin credentials** — `SUPER_ADMIN_MAIL` + `SUPER_ADMIN_HASH` handed over (and rotated).
- [ ] **Google Drive folder** — the folder with keys/envs/docs is shared with the **team**, not a single personal account.
- [ ] **Secrets rotated** — every key/password shared in chat or Drive is rotated once the new owner has access.
- [ ] **Walkthrough call done** — live screen-share covering deploy, logs, restart, scraping, payments webhook, and known issues.

> ⚠️ **Security note:** the server password was shared over chat. Rotate it, and rotate all API keys/secrets, as part of the handover. Treat anything shared in a chat/Drive as compromised.

> **Note on the marketing-site concern:** during the KT, Karan flagged that the marketing site and the app should be separate concerns (as they are for the HouseKraft site) but are currently mixed in Bubbl. In this codebase the public marketing pages (`/`, `/features`, `/pricing`, `/compare/*`, legal pages) and the app (dashboard, admin, embed API) are served by the **same Flask process** (see `routes/embed/views.py`). If separation is required, that's the item to plan for — split marketing into a static/standalone site and keep only the app + embed API on this server.

---

## 1. What Bubbl Is

Bubbl.ooo is a **no-code AI chatbot SaaS** aimed at Indian SMBs. A business signs up, trains a bot on its own data (file uploads, pasted text, Q&A, or by scraping a website), customizes the widget, and embeds it on their site. The bot answers customer questions and captures leads. Owners see leads and analytics in a dashboard.

- **Multi-tenant** by organization: each user belongs to an `organization`; users only see/edit bots within their org.
- **AI:** Google Gemini (`gemini-3.1-flash-lite`) for chat + Gemini File Search / vector stores for retrieval over the trained data.
- **Real-time chat** over WebSocket (Flask-SocketIO + gevent), with Redis as the cross-process message queue.
- **Background work** (website scraping, Gemini file uploads/indexing, subscription reminders) runs in a **separate Celery worker**, not in the web process.

---

## 2. Live Architecture (What Runs Where)

```
Internet (HTTPS)
       │
       ▼
   Nginx (reverse proxy + SSL)        ← sets X-Forwarded-* (app trusts it via ProxyFix)
       │
       ▼
   Gunicorn  (systemd service: `bubbl`)
   1 worker · GeventWebSocketWorker · timeout 120s · max_requests 1000
   → Flask app (app:app), Flask-SocketIO for real-time chat
       │
       ├────────────► NeonDB (PostgreSQL, serverless)     — app data
       ├────────────► Google Gemini API                    — chat + vector stores
       ├────────────► Firecrawl API                         — URL → markdown scraping
       ├────────────► Gmail SMTP                            — OTP / contact / invites
       ├────────────► Paddle                                — subscription billing + webhooks
       └────────────► Redis (localhost:6379)                — cache, rate limiter, Celery broker, SocketIO queue
                          │
                          ▼
              Celery worker (systemd service: `celery-bubbl`)
              gevent pool · 20 concurrent · MemoryMax 250M
              → website scraping, Gemini uploads/indexing (tasks/scrape_tasks.py)
              → subscription-expiry reminders every 6h (tasks/reminder_tasks.py, celery beat)
```

| Component | Technology | Where / Service |
|-----------|-----------|-----------------|
| Reverse proxy + SSL | Nginx + (Let's Encrypt) | system service |
| Web app | Flask + Gunicorn (gevent-websocket, 1 worker) | systemd `bubbl` |
| Background jobs | Celery (gevent pool, 20 concurrency) | systemd `celery-bubbl` |
| Broker / cache / queue | Redis (50MB cap, local) | systemd `redis` |
| Database | PostgreSQL | NeonDB (serverless, cloud) |
| AI chat + retrieval | Google Gemini + File Search stores | cloud |
| Web scraping | Firecrawl | cloud |
| Email | Gmail SMTP | cloud |
| Payments | Paddle | cloud |
| Analytics | GA4, Meta Pixel, Microsoft Clarity | cloud (env-gated) |

**Hosting:** DigitalOcean droplet, `root@168.144.123.62`, code at `/root/Bubbl`, virtualenv at `/root/Bubbl/myenv`.

> **Heads-up: `PROJECT.md` is partly out of date on ops.** The code now runs a **single gevent-websocket gunicorn worker** (not "2 workers × 12 threads"), Celery+Redis is **actually deployed** (not just a recommendation), and there are now **Paddle payments, Google OAuth, subscription reminders, and WebSocket chat**. When docs and code disagree, trust the code (`gunicorn.conf.py`, `celery_app.py`, `app.py`, `config.py`, `deploy/`).

---

## 3. Repository Layout

```
Bubbl/
├── HANDOVER.md          ← this document (start here)
├── PROJECT.md           ← full deep-dive: funnel, every route, schema, SEO, pain points
├── README.md            ← short overview + local setup
├── app.py               ← Flask app factory: gevent patch, blueprints, SocketIO, ProxyFix
├── config.py            ← all env config (DB pool, Gemini, Firecrawl, Paddle, OAuth, analytics)
├── extensions.py        ← Flask-Limiter + Flask-Caching
├── celery_app.py        ← Celery config (broker=Redis, beat schedule for reminders)
├── gunicorn.conf.py     ← production web server config (gevent-websocket worker)
├── Procfile             ← "web: gunicorn -c gunicorn.conf.py app:app"
├── schema.sql           ← manual DB backup (NOT a migration tool — see known issues)
├── check_schema.py      ← schema sanity check helper
├── load_test.js         ← k6 load-test script
├── requirements.txt     ← pinned Python deps
├── deploy/
│   ├── celery-bubbl.service   ← systemd unit for the Celery worker
│   └── setup_redis_celery.sh  ← one-command Redis + Celery install script
├── bot/          ← chat.py (Gemini chat + token tracking), cloud.py (vector store CRUD)
├── models/       ← models.py (SQLAlchemy: Organization, User, Bot, BotUI, Document, ScrapeJob, Lead, Feedback, + subscription/payment models)
├── routes/
│   ├── auth/     ← login, register/OTP, logout, @admin_required
│   ├── admin/    ← dashboard, bot management, doc upload, scrape start/status, text upload
│   ├── embed/    ← views.py (all public + app pages), api.py (/api/chat, /api/lead)
│   ├── payments.py    ← Paddle checkout + webhook handling
│   ├── super_admin.py ← platform-wide admin
│   └── profile.py
├── tasks/        ← scrape_tasks.py (Celery scraping), reminder_tasks.py (subscription reminders)
├── utils/        ← scraper.py (Firecrawl/sitemap/spider), mail_helper.py (SMTP)
├── static/       ← css/, js/ (analytics.js, chat.js), images, robots.txt, sitemap.xml
├── templates/    ← all HTML (landing, dashboard, admin, embed widget, legal, compare/*)
└── uploads/      ← scraped/uploaded knowledge files (.md etc.)
```

---

## 4. First-Time Setup (From Scratch)

### 4.1 App (local dev)
```bash
git clone https://github.com/kchecker/bubblooo   # (private — needs repo access)
cd Bubbl
python -m venv venv
source venv/bin/activate            # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                # then fill in real values (see §5)
python app.py                       # dev server on http://127.0.0.1:5000
```

### 4.2 Database (NeonDB / PostgreSQL)
1. Create a Postgres database (NeonDB free tier is what's in use).
2. Put its connection string in `DATABASE_URL`.
3. Create tables — either apply `schema.sql`, or from a Python shell:
   ```python
   from app import app
   from models.models import db
   with app.app_context():
       db.create_all()
   ```
4. Generate a super-admin password hash for the env vars:
   ```bash
   python -c "import bcrypt; print(bcrypt.hashpw('YourPassword'.encode(), bcrypt.gensalt()).decode())"
   ```

### 4.3 Production server (DigitalOcean)
Full path is a systemd + Nginx setup. The Redis + Celery half is scripted:
```bash
# On the droplet, as root, from /root/Bubbl:
chmod +x deploy/setup_redis_celery.sh
sudo ./deploy/setup_redis_celery.sh     # installs Redis (50MB cap), Celery deps, celery-bubbl service
```
The **web** side runs as a systemd service named `bubbl` executing gunicorn with `gunicorn.conf.py`, fronted by Nginx for SSL. (Confirm the exact `bubbl.service` unit on the droplet — it's referenced by the setup script but lives on the server, not in the repo.)

---

## 5. Environment Variables

> Real values live in the shared **Google Drive** folder for Bubbl. Never commit secrets. `SECRET_KEY` and `DATABASE_URL` have **no fallback** — the app crashes on startup if they're missing.

**Required:**
```env
SECRET_KEY=<flask session secret>
DATABASE_URL=postgresql://user:pass@host/db     # NeonDB connection string
GEMINI_API_KEY=<Google AI Studio key>
FIRECRAWL_API_KEY=<Firecrawl key>
EMAIL_ADDRESS=<gmail sender>
EMAIL_PASSWORD=<gmail app password>
HOST_URL=https://bubbl.ooo                       # base URL for embed scripts + CORS
```

**Payments (Paddle):**
```env
PADDLE_API_KEY=<...>
PADDLE_WEBHOOK_SECRET=<...>
PADDLE_ENVIRONMENT=production                    # 'sandbox' or 'production'
PADDLE_CLIENT_TOKEN=<for Paddle.js on the frontend>
PADDLE_PRICE_STARTER=<price id>
PADDLE_PRICE_GROWTH=<price id>
PADDLE_PRICE_PRO=<price id>
```

**Google OAuth:**
```env
GOOGLE_CLIENT_ID=<...>
GOOGLE_CLIENT_SECRET=<...>
```

**Optional / infra / branding:**
```env
REDIS_URL=redis://localhost:6379/0               # defaults to this if unset
PORT=5000                                         # gunicorn bind port
SUPPORT_EMAIL=<contact form recipient>
COMPANY_NAME_FRONT=Bubbl
COMPANY_NAME_BACK=ooo
OFFICE_LOCATION="Chandigarh, India"
SUPER_ADMIN_MAIL=<god-mode login email>
SUPER_ADMIN_HASH=<bcrypt hash>
GA4_MEASUREMENT_ID=G-XXXXXXXXXX
META_PIXEL_ID=<...>
CLARITY_ID=<...>
```

> Analytics scripts only load if their env var is set — leaving them blank disables that tracker with zero performance cost.

---

## 6. Day-to-Day Maintenance & Deployment

Everything runs under **systemd** on the droplet: `bubbl` (web), `celery-bubbl` (worker), `redis`.

### Deploy a code update (most common task)
```bash
ssh root@168.144.123.62
cd /root/Bubbl
git pull origin main                 # authenticated via the deploy PAT (private repo)
source myenv/bin/activate
pip install -r requirements.txt      # only if deps changed

sudo systemctl restart bubbl         # restart the web app
sudo systemctl restart celery-bubbl  # restart the worker (only needed if task code changed)
```

> **Deploy PAT:** the server pulls the private repo using a **fine-grained GitHub PAT**. During handover this must be **reissued under the new owner's GitHub account** and the old one revoked. Check the remote with `git -C /root/Bubbl remote -v`.

### Service management
| Command | Purpose |
|---------|---------|
| `sudo systemctl status bubbl` | Web app status |
| `sudo systemctl restart bubbl` | Restart web app |
| `sudo journalctl -u bubbl -f` | Live web app logs |
| `sudo systemctl status celery-bubbl` | Worker status |
| `sudo systemctl restart celery-bubbl` | Restart worker |
| `sudo journalctl -u celery-bubbl -f` | Live worker logs (scraping/uploads) |
| `sudo systemctl status redis` | Redis status |
| `redis-cli ping` | Should return `PONG` |
| `redis-cli info memory` | Check Redis memory (capped at 50MB) |

### Where things log
Both services log to **journald** (stdout/stderr, unbuffered). Use `journalctl -u <service> -f`. The app uses plain `print()`/logging in places (no structured logging yet — see known issues).

### SSL / Nginx
SSL is terminated at Nginx (the app trusts `X-Forwarded-*` via `ProxyFix`). Renew certs and reload Nginx as usual (`certbot renew && systemctl reload nginx`). Confirm the Nginx site config path on the droplet.

### Payments webhook
Paddle sends subscription events to a webhook handled in `routes/payments.py`, verified with `PADDLE_WEBHOOK_SECRET`. When moving Paddle from sandbox → production, update `PADDLE_ENVIRONMENT`, the API key/token, the webhook secret, **and** the three `PADDLE_PRICE_*` IDs (production has different price IDs — that's why they're env vars).

---

## 7. Reports & Analytics

**In-product reporting:**
- **Leads** (`/leads`) — filterable table with dynamic custom columns + AI priority scoring (High/Medium/Low); **CSV export** via `/export_leads`.
- **Super Admin** (`/super_admin`) — platform-wide analytics: all bots, all users, usage.
- **Per-bot usage** — `bot.tokens_used`, `bot.total_latency`, `bot.interaction_count` are tracked on the `bot` table (updated per chat message).
- **Revenue/MRR** — plan pricing is in `Config.PLAN_PRICE_INR` (`free`/`starter`/`growth`/`pro` = ₹0/499/1499/4999) and subscription state lives in the DB.

**External analytics (env-gated):**
- **GA4** — page views, funnel events (`sign_up`, `bot_created`, `embed_widget`, `lead_captured`, `plan_click`, `waitlist_signup`), UTM attribution.
- **Meta Pixel** — ad conversion events.
- **Microsoft Clarity** — heatmaps + session recordings.

Ad-hoc reporting can be done directly against NeonDB (tables: `lead`, `bot`, `feedback`, `scrape_job`, subscription/payment tables). Full event → file mapping is in `PROJECT.md` → "Analytics & Funnel Tracking".

---

## 8. Known Issues & Tech Debt (Hand These Over Honestly)

`PROJECT.md` has the full ranked list. The highest-signal items and current status:

- **Marketing site + app share one Flask process** — Karan's flagged separation concern (see §0 note).
- **Scaling / concurrency** — single gunicorn worker; each chat holds a slot during the Gemini call. Redis-backed cache + rate limiter across processes is in place, but rate-limiting effectiveness still depends on worker count. `PROJECT.md` documents load-test limits on the 1GB droplet.
- **`/api/lead` calls Gemini** just to validate a submitted form (burns a slot + credits for something regex could do).
- **DB write on every chat message** (token/latency/interaction counters) → row-lock contention on the `bot` table under load. Consider batching.
- **`schema.sql` is a manual backup, not a migration** — no Alembic. Schema changes are applied by hand; risk of drift between models and the live DB.
- **Avatars stored as base64 in Postgres** (`bot_ui.avatar_base64`) — scales poorly.
- **`delete_from_gemini()` lists ALL Gemini files** to find one by name — O(n), slows as files grow.
- **`print()`-based logging** in several modules — no structured logs / correlation IDs.
- **Security gaps** (documented in `PROJECT.md` → "Security"): no CSRF enforcement on API routes, no CAPTCHA on register/embed, no account lockout, no file magic-byte verification, PII stored plaintext, no password complexity rules. Review before scaling.
- **`send_invite_email()`** historically returned `True` without actually sending — verify it's wired to SMTP before relying on team invites.

---

## 9. Deeper Docs Index

| Doc | Read it when you need… |
|-----|------------------------|
| `PROJECT.md` | the full architecture, complete route/API/schema tables, SEO stack, funnel psychology, security matrix, ranked pain points, and load-test numbers |
| `README.md` | a quick overview + minimal local setup |
| `gunicorn.conf.py` | exactly how the web server runs in prod (and *why* preload is off) |
| `celery_app.py` | the worker/broker config + the beat schedule for subscription reminders |
| `deploy/setup_redis_celery.sh` + `deploy/celery-bubbl.service` | how Redis + Celery are installed and run |
| `config.py` | the authoritative list of every env var the app reads |
| `schema.sql` | the current database schema (manual backup) |

---

_Prepared as part of the Bubbl + SalesJi project handover._
