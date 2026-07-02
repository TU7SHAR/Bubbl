# Bubbl.ooo — Full Project Documentation

> **AI Chatbot Platform for Indian SMBs**
> Train on your data. Deploy on WhatsApp & Web. Capture leads. No code.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   CLIENT (Browser / Embed)                    │
│                                                              │
│  Landing → Register → Dashboard → Create Bot → Embed/Chat   │
│     ↓          ↓          ↓           ↓            ↓        │
│  Static     SMTP OTP   Session     FormData     iframe+JS    │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTPS
┌───────────────────────────▼──────────────────────────────────┐
│                   GUNICORN (gthread)                           │
│  2 workers × 4 threads = 8 concurrent slots                   │
│  preload_app=True · timeout=120s · max_requests=1000          │
└───────┬──────────────────┬──────────────────┬────────────────┘
        │                  │                  │
┌───────▼──────┐  ┌───────▼──────┐  ┌───────▼──────────┐
│  PostgreSQL  │  │  Gemini AI   │  │  Firecrawl API   │
│  (Supabase/  │  │  • Chat      │  │  • URL Scraping  │
│   DO Managed │  │  • FileSearch│  │  • Markdown Out   │
│   or Local)  │  │  • VectorDB  │  │                   │
└──────────────┘  └──────────────┘  └───────────────────┘
```

### Request Flow — Chat (Embed Widget)

```
User types message in iframe widget
  → embed.js posts to /api/chat
    → Flask rate limiter check (20/min per IP)
    → Bot config fetched from cache (SimpleCache, 60s TTL)
    → System prompt assembled (guardrails + custom instructions + lead capture logic)
    → Gemini API call (gemini-3.1-flash-lite-preview) — BLOCKS 1-5 sec
    → Response parsed for [[LEAD:...]] tags or [SHOW_FORM]
    → If lead extracted → DB write (Lead table)
    → Bot token/latency stats updated → DB commit
    → JSON response returned to iframe
```


### Request Flow — Scraping (Admin Dashboard)

```
Admin clicks "Start Scrape" with URL + options
  → POST /admin/api/scrape/start
    → ScrapeJob created in DB (status=pending)
    → threading.Thread spawned inside gunicorn worker
    → Immediate JSON response: {job_id}
  → Thread runs async_scrape_task():
    → Spider/Sitemap/Single URL resolution
    → For each URL:
      → Firecrawl API → markdown content
      → Save .md file to /uploads/
      → Document record in DB
      → upload_to_gemini() → polls until indexed (time.sleep(5) loop)
    → Job status updated to completed/failed
  → Frontend polls /admin/api/scrape/status/{job_id} every 2-3s
```

---

## User Funnel (Complete Flow)

```
AWARENESS (SEO / Compare Pages / Organic)
  ↓
LANDING PAGE (/)
  Hero → "The AI chatbot your customers will love"
  Social proof → 2,400+ teams
  Features grid (6 cards: WhatsApp, Train on Data, Leads, Analytics, Multilingual, Deploy)
  How It Works → 3 steps
  CTA → "Start Building Free"
  ↓
REGISTER (/register) — Email + Password + OTP Verification
  → Organization auto-created ("{Name}'s Organization")
  → OTP sent via Gmail SMTP
  → /verify_otp → account confirmed
  ↓
DASHBOARD (/dashboard)
  Shows: My Agents (bot cards) + Org Agents
  Actions: Create New Agent / Edit / Leads / Embed & Integrate
  ↓
CREATE PIPELINE (/admin/create_pipeline)
  4-tab wizard:
    Tab 1: Quick Start (name, type, visibility, prompt)
    Tab 2: Knowledge Base (file upload + text snippets + Q&A)
    Tab 3: User Interface (theme color, avatar, dark/light mode, glassmorphism)
    Tab 4: Lead Conventions (timing + custom form fields)
  → Bot created with Gemini Vector Store
  → Files uploaded + indexed
  → Optional: scrape URL in background thread
  ↓
EMBED & INTEGRATE (/bot/{id}/integrate)
  Step 1: Copy embed code (HTML or React/Next.js)
  Step 2: Domain lock (CSP frame-ancestors)
  Live preview on page
  ↓
END USER INTERACTS (on client's website)
  → embed.js injects iframe → embed_chat.html
  → Chat widget with sprite animation
  → Lead capture (gatekeeper overlay / in-chat form / conversational)
  → Feedback collection (1-5 stars)
  ↓
ADMIN VIEWS LEADS (/leads)
  Filterable table with dynamic custom columns
  Priority scoring (High/Medium/Low via AI)
  Export to CSV
```

---

## Conversion Hooks (Psychology)

| Hook | Where | Psychology |
|------|-------|-----------|
| No login to see landing page | Homepage | Zero friction discovery |
| "2,400+ teams" social proof | Hero section | Bandwagon effect |
| Free tier (no credit card) | Pricing page | Remove purchase anxiety |
| OTP verification (not paywall) | Register | Low-commitment signup |
| Instant bot creation wizard | Create Pipeline | Immediate value delivery |
| Live widget preview on embed page | Integrate page | "It actually works" moment |
| Gatekeeper form before chat | Embed widget | Forces lead capture before value |
| AI lead scoring (High/Medium/Low) | Leads dashboard | Prioritization = perceived intelligence |
| Compare pages (vs Chatbase, Tidio, etc.) | SEO pages | Captures "alternative to X" searches |
| Domain lock as "security feature" | Integrate page | Makes embed feel enterprise-grade |


---

## Pages

| Route | File | Auth | Purpose |
|-------|------|------|---------|
| `/` | `templates/index.html` | None | Landing page with hero, features, how-it-works, CTA |
| `/features` | `templates/features.html` | None | Full feature list |
| `/pricing` | `templates/pricing.html` | None | 4-tier pricing (Free/Starter/Growth/Pro) |
| `/compare` | `templates/compare.html` | None | Competitor comparison hub |
| `/compare/<name>` | `templates/compare_*.html` | None | Individual competitor pages |
| `/how-to` | `templates/how_to.html` | None | User guides |
| `/contact` | `templates/contact.html` | None | Contact form (SMTP) |
| `/login` | `templates/login.html` | None | Login + Super Admin bypass |
| `/register` | `templates/register.html` | None | Signup + OTP flow |
| `/dashboard` | `templates/dashboard.html` | Session | Bot cards + team management |
| `/admin/` | `templates/admin.html` | Admin | File management dashboard |
| `/admin/create_pipeline` | `templates/create_pipeline.html` | Admin | 4-tab bot creation wizard |
| `/admin/edit_bot/<id>` | `templates/edit_bot.html` | Admin | Knowledge base + scraper + UI + leads config |
| `/bot/<id>/integrate` | `templates/integrate.html` | Session | Embed code + domain lock |
| `/embed/<id>` | `templates/embed_chat.html` | None | Iframe-loaded chat widget (public) |
| `/leads` | `templates/leads.html` | Session | Filterable lead table + CSV export |
| `/profile` | `templates/profile.html` | Session | User profile + team member removal |
| `/super_admin` | `templates/super_admin.html` | Super Admin | Platform-wide analytics + all bots/users |
| `/legal/privacy` | `templates/legal/privacy.html` | None | Privacy policy |
| `/legal/terms` | `templates/legal/terms.html` | None | Terms of service |
| `/legal/refunds` | `templates/legal/refunds.html` | None | Refund policy |

---

## API Routes

| Route | Method | Auth | Rate Limit | Purpose |
|-------|--------|------|-----------|---------|
| `/api/chat` | POST | None (bot_id in payload) | 20/min per IP | Send message → Gemini → parse lead → respond |
| `/api/lead` | POST | None | 10/min per IP | Form-based lead capture + AI validation |
| `/api/bot_avatar/<id>` | GET | None | None | Cached avatar (base64) for embed widget |
| `/api/waitlist` | POST | None | None | Waitlist signup (Formspree + SMTP) |
| `/bot/<id>/widget/feedback` | POST | None | None | Star rating + comment from widget |
| `/admin/api/scrape/start` | POST | Session | None | Start background scrape job |
| `/admin/api/scrape/status/<id>` | GET | Session | None | Poll scrape job progress/logs |
| `/admin/upload` | POST | Session | None | Upload file → Gemini vector store |
| `/admin/upload_text` | POST | Session | None | Raw text → .md file → Gemini |
| `/admin/delete/<filename>` | GET | Session | None | Delete file from Gemini + DB |
| `/admin/create_pipeline` | POST | Session | None | Full bot creation (multi-file + scrape) |
| `/admin/update_bot/<id>` | POST | Session | None | Update bot settings + UI |
| `/admin/delete_bot/<id>` | POST | Session | None | Delete bot + all Gemini files |
| `/admin/invite_member` | POST | Admin | None | Add team member to org |
| `/export_leads` | GET | Session | None | CSV download of all org leads |
| `/login` | POST | None | 5/min | Email/password auth |
| `/register` | POST | None | 5/min | Account creation + OTP |
| `/forgot_password` | POST | None | 3/min | OTP-based password reset |
| `/resend_otp` | GET | None | 3/min | Re-send verification code |


---

## Database Schema (PostgreSQL)

### `organization`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| name | VARCHAR(100) | e.g. "John's Organization" |

### `user`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| org_id | INTEGER | FK → organization |
| name | VARCHAR(100) | |
| email | VARCHAR(120) | UNIQUE |
| password_hash | VARCHAR(255) | bcrypt |
| otp | VARCHAR(6) | Temporary verification code |
| is_verified | BOOLEAN | Email confirmed |
| role | VARCHAR(20) | 'admin' or 'member' |

### `bot`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| org_id | INTEGER | FK → organization |
| created_by | INTEGER | FK → user |
| bot_name | VARCHAR(100) | |
| store_id | VARCHAR(255) | Gemini vector store ID |
| visibility | VARCHAR(10) | 'public' or 'private' |
| access_key | VARCHAR(4) | 4-char decryption key for private bots |
| bot_type | VARCHAR(50) | 'sales', 'support', 'general', 'custom' |
| system_prompt | TEXT | Custom AI instructions |
| lead_capture_timing | VARCHAR(20) | 'disabled', 'gatekeeper', 'conv_start', 'form_middle', etc. |
| custom_form_fields | VARCHAR(500) | JSON array of {name, type, required} |
| tokens_used | INTEGER | Cumulative Gemini tokens |
| total_latency | FLOAT | Cumulative response time (seconds) |
| interaction_count | INTEGER | Total messages processed |
| allowed_domains | VARCHAR(255) | CSP frame-ancestors whitelist |
| theme_color | VARCHAR(20) | Legacy (moved to bot_ui) |

### `bot_ui`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| bot_id | INTEGER | FK → bot (UNIQUE) |
| theme_color | VARCHAR(20) | Hex color for widget accent |
| header_color | VARCHAR(20) | Widget header text color |
| theme_mode | VARCHAR(10) | 'light' or 'dark' |
| avatar_base64 | TEXT | Full data URI (image/jpeg;base64,...) |
| glass_opacity | INTEGER | Glassmorphism opacity (0-100) |
| glass_blur | INTEGER | Glassmorphism blur (px) |

### `document`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| bot_id | INTEGER | FK → bot |
| filename | VARCHAR(255) | Stored in /uploads/ |

### `scrape_job`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| bot_id | INTEGER | FK → bot |
| url | VARCHAR(2048) | Target URL |
| status | VARCHAR(20) | pending/completed/failed |
| limit | INTEGER | Max pages to crawl |
| error_message | TEXT | Failure details |
| logs | TEXT | Real-time progress logs |
| created_at | TIMESTAMP | |
| completed_at | TIMESTAMP | |

### `lead`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| bot_id | INTEGER | FK → bot |
| name | VARCHAR(100) | |
| email | VARCHAR(120) | |
| phone | VARCHAR(20) | Optional |
| custom_data | JSONB | Dynamic fields + Priority score |
| captured_at | TIMESTAMP | |

### `feedback`
| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL | PK |
| bot_id | INTEGER | FK → bot |
| lead_id | INTEGER | FK → lead (nullable) |
| rating | INTEGER | 1-5 stars |
| comment | TEXT | Optional |
| created_at | TIMESTAMP | |


---

## SEO / AEO / LLM Discovery Stack

### SEO (Search Engine Optimization)
- `robots.txt` served from `/static/robots.txt`
- `sitemap.xml` served from `/static/sitemap.xml`
- Canonical URLs via `<link rel="canonical" href="{{ request.url }}">`
- Open Graph + Twitter Card meta tags on every page (via `base.html`)
- Targeted keywords: "AI chatbot", "WhatsApp bot", "no-code chatbot", "Indian SMB", "lead generation"
- 4 competitor comparison pages (`/compare/chatbase`, `/compare/tidio`, `/compare/intercom`, `/compare/gupshup`)
- Each page has unique `<meta name="description">` via `{% block meta_description %}`
- Legal pages (privacy, terms, refunds) for E-E-A-T signals
- Semantic HTML: `<header>`, `<section>`, `<article>`, `<footer>`, `<nav>`

### AEO (Answer Engine Optimization)
- Landing page structured with clear "How It Works" 3-step section (targets featured snippets)
- Pricing comparison table (targets "Bubbl vs X" queries)
- FAQ-style content on feature pages
- Schema.org JSON-LD markup:
  - `Organization` schema (name, url, logo, sameAs)
  - `WebSite` schema with `SearchAction` (site search targeting)
- Compare pages target "best alternative to Chatbase/Tidio/Intercom" queries

### GEO (Generative Engine Optimization)
- Clean heading hierarchy (H1 → H2 → H3) on all pages
- Feature descriptions are factual and extractable (not marketing fluff in code)
- Pricing clearly stated with INR + USD in structured table
- Content organized for LLM extraction: lists, tables, step-by-step

### LLM Discovery
- No `robots.txt` restrictions on AI crawlers (allows GPTBot, etc.)
- Organization schema provides entity context for LLMs
- Product descriptions use plain language parseable by AI assistants
- Compare pages provide factual feature-by-feature data LLMs can cite

---

## Environment Variables

| Variable | Required | Free? | Purpose |
|----------|----------|-------|---------|
| `SECRET_KEY` | Yes | — | Flask session encryption |
| `DATABASE_URL` | Yes | Yes (Supabase free) | PostgreSQL connection string |
| `GEMINI_API_KEY` | Yes | Yes (free tier) | Google Gemini AI (chat + vector stores) |
| `FIRECRAWL_API_KEY` | Yes | Yes (500 credits free) | URL scraping to markdown |
| `EMAIL_ADDRESS` | Yes | Yes (Gmail) | SMTP sender for OTP/contact/invites |
| `EMAIL_PASSWORD` | Yes | Yes (App Password) | Gmail SMTP authentication |
| `HOST_URL` | Yes | — | Base URL for embed scripts and CORS |
| `SUPPORT_EMAIL` | No | — | Contact form recipient |
| `COMPANY_NAME_FRONT` | No | — | "Bubbl" (branding) |
| `COMPANY_NAME_BACK` | No | — | "ooo" (branding) |
| `OFFICE_LOCATION` | No | — | Legal pages |
| `SUPER_ADMIN_MAIL` | No | — | God-mode login email |
| `SUPER_ADMIN_HASH` | No | — | bcrypt hash for super admin |
| `PORT` | No | — | Gunicorn bind port (default 5000) |
| `WEB_CONCURRENCY` | No | — | Gunicorn worker count (default 2) |
| `GUNICORN_THREADS` | No | — | Threads per worker (default 4) |

### Zero-Cost Stack

| Service | Provider | Free Tier |
|---------|----------|-----------|
| Database | Supabase / DO Managed | 500MB free (Supabase) |
| AI Chat + Vector Store | Google Gemini | Free tier (rate-limited) |
| Web Scraping | Firecrawl | 500 credits free |
| Email (OTP + Contact) | Gmail SMTP | 500 emails/day |
| Hosting | DigitalOcean Droplet | $6/mo (1GB RAM) |
| **Total recurring** | | **$6/mo** |


---

## Pricing Model + Revenue

| Plan | Price | Target | What They Get |
|------|-------|--------|---------------|
| Free | ₹0 | Hobbyists / Tryout | 1 bot, 200 msgs/month, basic training |
| Starter | ₹499/mo ($9) | Small businesses | 2 bots, 2K msgs, Hindi+English, lead capture |
| Growth | ₹1,499/mo ($29) | Growing businesses | 5 bots, 10K msgs, all Indian languages, CRM lite |
| Pro | ₹4,999/mo ($79) | Agencies | Unlimited bots, 50K msgs, white-label, API |

### Cost Per Chat Message
- Gemini 3.1 Flash-Lite: ~4,000 tokens input + ~2,000 output ≈ ₹0.10-0.50 per message
- At Growth tier (10K msgs): cost ≈ ₹1,000-5,000 → margin depends on actual usage

### Revenue Per Customer (LTV Estimate)
- **Minimum (Starter):** ₹499 × 6 months = ₹2,994
- **Growth convert:** ₹1,499 × 12 months = ₹17,988
- **Pro (agency):** ₹4,999 × 12 months = ₹59,988

---

## Security: What IS vs ISN'T Implemented

### Implemented
- [x] bcrypt password hashing (cost factor: default 12)
- [x] Flask-Limiter rate limiting on login (5/min), register (5/min), chat (20/min), OTP (3/min)
- [x] CORS whitelist (only bubbl.ooo + HOST_URL allowed on /api/*)
- [x] Session-based auth with `SESSION_COOKIE_SAMESITE=None` + `Secure=True`
- [x] OTP email verification before account activation
- [x] CSP `frame-ancestors` per bot (domain lock for embed widget)
- [x] X-Frame-Options stripped and replaced with CSP (intentional for embed)
- [x] `secure_filename()` on all uploads (path traversal prevention)
- [x] File size validation (10MB max via `MAX_CONTENT_LENGTH`)
- [x] File type whitelist (txt, doc, docx, xls, xlsx, md, html, pdf)
- [x] Input sanitization on lead data (coerce numbers, strip nulls, title-case keys)
- [x] Bot visibility: private bots require 4-char access key
- [x] Org-level isolation: users can only see/edit bots in their org
- [x] Admin-required decorator on sensitive routes
- [x] Super Admin env-based auth (bypasses DB entirely)
- [x] `preload_app=True` + `max_requests=1000` (memory leak prevention)
- [x] `pool_pre_ping=True` on SQLAlchemy (stale connection detection)
- [x] Bot config caching to reduce DB hits (invalidated on edit/delete)

### NOT Implemented (Known Gaps)
- [ ] CSRF protection (Flask-WTF imported but not enforced on API routes)
- [ ] CAPTCHA/hCaptcha on register or embed chat (bot spam risk)
- [ ] Account lockout after N failed login attempts
- [ ] File content verification (magic bytes check — can upload renamed malicious files)
- [ ] EXIF stripping on avatar uploads (potential GPS data leak)
- [ ] Session invalidation on password change
- [ ] Audit logging (who did what, when)
- [ ] Encrypted PII at rest (emails, names stored plaintext in DB)
- [ ] DDoS protection beyond rate limiting (no Cloudflare/WAF)
- [ ] HTTPS enforcement in app code (relies on reverse proxy)
- [ ] Content-Security-Policy on non-embed pages (no CSP header)
- [ ] Webhook signatures for incoming requests (no server-to-server auth)
- [ ] Rate limiting storage is per-process (memory://) — inconsistent across workers
- [ ] Cache is per-process (SimpleCache) — inconsistent across workers
- [ ] Two-factor authentication
- [ ] GDPR data deletion endpoint
- [ ] Password complexity requirements (any password accepted)
- [ ] `send_invite_email()` has no actual SMTP sending logic (function returns True without sending)


---

## Technical Pain Points (Ranked by Severity)

### Critical (Will break under real load)

1. **Threading inside gunicorn workers** — Scrape jobs run as `threading.Thread` inside the web process. 4 concurrent scrapes = RAM spike + potential OOM on 1GB droplet. No crash recovery, no retry. If thread dies, job stays "pending" forever.

2. **Only 8 concurrent request slots** — 2 workers × 4 threads. Each chat request holds a slot for 1-5 seconds (Gemini wait). At 8+ concurrent chatters, requests queue → 503 errors. Load test confirmed failure at 7 continuous users.

3. **DB write on EVERY chat message** — `bot.tokens_used`, `bot.total_latency`, `bot.interaction_count` committed on every single `/api/chat` call. Under load, this creates row-level lock contention on the `bot` table.

4. **`/api/lead` calls Gemini for validation** — Every form submission triggers a full Gemini API call just to check if "asdf" is fake. Burns a 2-5 second slot + API credits for a task regex could handle.

5. **Rate limiter uses `memory://` storage** — Each gunicorn worker tracks limits independently. User hitting worker 1 and worker 2 gets 2× the allowed rate. Completely ineffective for abuse prevention.

### Medium (Causes degraded experience)

6. **SimpleCache is per-process** — Worker 1's cached bot config ≠ Worker 2's. Same bot gets fetched from DB twice, doubling cache-miss DB load.

7. **`upload_to_gemini()` blocks with `time.sleep(5)` polling** — Inside scrape threads, this holds resources for 5-30+ seconds per file while checking if indexing completed. No timeout cap.

8. **DB connection pool oversized for 1GB droplet** — `pool_size=20` + `max_overflow=30` = up to 50 connections. PostgreSQL on a small instance can't handle this. Wastes RAM on idle connections.

9. **No job deduplication** — User can click "Start Scrape" multiple times, spawning parallel threads scraping the same URL. No check for existing pending jobs.

10. **Global Gemini client singleton is not thread-safe** — `_client` in `bot/chat.py` is a module-level global assigned without locking. Under concurrent access, could get partially initialized.

### Low (Technical debt, not immediate risk)

11. **`delete_from_gemini()` iterates ALL files** — `for g_file in client.files.list()` scans Google's entire file storage to find one file by display_name. O(n) on every delete. Will slow dramatically as files grow.

12. **Debugging `print()` statements everywhere** — `scrape_managment.py`, `cloud.py`, `chat.py` all use `print()` for logging. No structured logging, no log levels, no correlation IDs.

13. **`schema.sql` is a manual backup, not a migration** — No Alembic or migration tool. Schema changes require manual SQL execution. Risk of drift between code models and actual DB.

14. **Avatar stored as base64 in DB** — Full image data URIs stored in `bot_ui.avatar_base64`. A 200KB avatar = 270KB base64 string in PostgreSQL. Scales poorly.

15. **`add_log()` inside scrape thread commits DB on every log line** — Each progress message = separate `db.session.commit()`. A 50-URL scrape = 100+ commits just for logging.

---

## Performance Profile (1GB DigitalOcean Droplet)

### Current Resource Usage (Idle)
| Resource | Used | Total |
|----------|------|-------|
| RAM | ~273MB (gunicorn 4 workers) | 962MB |
| Swap | 12.1MB | 2GB |
| CPU | 1.3% | 1 vCPU |
| Disk | 18.9% | 23.17GB |

### Concurrent User Capacity (Measured)
| Scenario | Max concurrent | Bottleneck |
|----------|---------------|------------|
| Chat only (different IPs) | ~8-12 | 8 gunicorn slots × 2-5s Gemini wait |
| Chat only (same IP, like load test) | ~7 before 429s | Rate limiter: 20/min per IP |
| Chat + 1-2 small scrapes | ~6-8 chatters | Threads share worker RAM |
| Chat + 4 scrapes (20+ URLs each) | Crash in 1-3 min | RAM spike → OOM |

### What Would Fix It (Priority Order)
| Fix | Effort | Impact |
|-----|--------|--------|
| Bump `GUNICORN_THREADS=8` (16 slots) | 1 env var | 2× chat capacity |
| Add Celery + Redis for scraping | Medium | Scraping isolated, no more OOM |
| Remove Gemini call from `/api/lead` validation | Small | Free 1 slot per form submit |
| Batch token stats (don't commit every message) | Small | Reduce DB contention |
| Switch to Redis for cache + rate limiter | Small | Consistent across workers |


---

## Known Limitations + Workarounds

| Limitation | Current Workaround |
|-----------|-------------------|
| Gemini may return markdown despite guardrails | `BASE_GUARDRAILS` explicitly forbids markdown formatting |
| Rate limiter inconsistent across workers | Acceptable at current scale (1-2 workers) |
| Embed widget CSP allows `frame-ancestors *` when no domains set | Default = open; admin must manually lock domains |
| `send_invite_email()` doesn't actually send | Function returns `True` without SMTP logic (incomplete) |
| Flask sessions stored server-side cookies (not DB) | Restarting app clears all sessions |
| No WebSocket — chat is request/response | Each message is a separate HTTP POST (acceptable for AI chat latency) |
| Spritesheet animation requires GSAP CDN | Falls back gracefully if CDN unavailable |
| Super Admin uses env-var credentials (not DB) | Intentional: can't be locked out by DB failure |
| `gunicorn preload_app=True` shares memory but not process state | Bot config cache diverges between workers after invalidation |

---

## Code Structure

```
Bubbl/
├── app.py                         # Flask app factory, blueprint registration, CORS, init
├── config.py                      # Config class (env vars, DB pool, upload paths)
├── extensions.py                  # Flask-Limiter (memory://) + Flask-Caching (SimpleCache)
├── gunicorn.conf.py               # Production server config (workers, threads, timeouts)
├── Procfile                       # "web: gunicorn -c gunicorn.conf.py app:app"
├── requirements.txt               # 70+ pinned dependencies
├── schema.sql                     # Backup SQL for table recreation
├── load_test.js                   # k6 load testing script
│
├── bot/
│   ├── chat.py                    # Gemini chat: prompt assembly, API call, token tracking
│   └── cloud.py                   # Gemini vector store: create, upload (polling), delete
│
├── models/
│   └── models.py                  # SQLAlchemy models (Organization, User, Bot, BotUI, Document, ScrapeJob, Lead, Feedback)
│
├── utils/
│   ├── scraper.py                 # Firecrawl single URL, sitemap parser, spider crawler
│   └── mail_helper.py            # OTP email, contact form, auto-reply, invite (broken), validation
│
├── routes/
│   ├── profile.py                 # /profile, /remove_member
│   ├── auth/
│   │   ├── __init__.py            # Blueprint 'auth'
│   │   ├── login.py              # Login, forgot_password, reset_password
│   │   ├── register.py           # Register, verify_otp, resend_otp
│   │   ├── logout.py            # Session clear
│   │   └── decorators.py        # @admin_required
│   ├── admin/
│   │   ├── __init__.py           # Blueprint 'admin_bp' (url_prefix=/admin)
│   │   ├── dashboard.py         # Admin file view, bot selection, invite member
│   │   ├── bot_management.py    # Create/rename/edit/delete bot, add knowledge, cache invalidation
│   │   ├── doc_management.py    # Upload/delete files to Gemini
│   │   ├── scrape_managment.py  # Start scrape, poll status, background thread
│   │   └── upload_text.py       # Raw text → .md → Gemini upload
│   └── embed/
│       ├── views.py              # All public views: index, dashboard, embed, leads, super_admin, compare, contact, pricing, etc.
│       └── api.py                # /api/chat, /api/lead (the core AI endpoints)
│
├── static/
│   ├── css/                       # 11 stylesheets (admin, auth, chat, dashboard, index, mobile, profile, super_admin, etc.)
│   ├── js/
│   │   ├── chat.js               # Chat widget logic (send, receive, lead forms, typing indicator)
│   │   ├── embed.js              # Embed script (creates iframe, auto-detects host)
│   │   ├── script.js             # Global: form disabling, scrape polling, copy-to-clipboard
│   │   ├── sprite.js             # GSAP spritesheet animation (5 states: idle/hover/thinking/talking/rolling)
│   │   └── dashboard.js         # GSAP animations for dashboard cards + invite modal
│   ├── images/                    # favicon.svg, og-banner.png, spritesheets
│   ├── robots.txt
│   └── sitemap.xml
│
└── templates/
    ├── base.html                  # Master layout: nav, footer, SEO meta, JSON-LD, mobile menu, GSAP
    ├── chat.html                  # Chat widget partial (included in base + embed)
    ├── partials/
    │   ├── _chatbot_tabs.html    # Create pipeline tab content
    │   ├── _chatbot_styles.html  # Create pipeline CSS
    │   ├── _chatbot_scripts.html # Create pipeline JS
    │   └── _chatbot_modals.html  # Create pipeline modals
    └── ... (20+ page templates)
```

---

## Quick Commands

```bash
# Development (local)
python app.py                      # Flask dev server (localhost:5000)

# Production (VPS)
gunicorn -c gunicorn.conf.py app:app   # Or via systemd service

# Database
# Run schema.sql manually in PostgreSQL if starting fresh
# No migration tool — models.py is source of truth

# Load Testing
k6 run load_test.js               # Requires k6 installed locally

# Dependencies
pip install -r requirements.txt    # All pinned versions
```

---

## Infrastructure (Current Production)

| Component | Details |
|-----------|---------|
| **Server** | DigitalOcean Droplet, 1GB RAM, 1 vCPU, 25GB SSD |
| **OS** | Ubuntu (latest LTS) |
| **Process Manager** | systemd (gunicorn as service) |
| **Web Server** | Gunicorn 25.1.0 (gthread worker class) |
| **Database** | PostgreSQL (psycopg2-binary) |
| **AI Model** | Google Gemini 3.1 Flash-Lite Preview |
| **Vector Store** | Google Gemini File Search Stores |
| **Scraping** | Firecrawl API (markdown extraction) |
| **Email** | Gmail SMTP (500/day free) |
| **Domain** | bubbl.ooo |
| **SSL** | Let's Encrypt (via DO or nginx) |
| **Monitoring** | None (print statements to stdout) |
| **CI/CD** | None (manual git pull + restart) |
| **Backups** | None configured |

---

## What's NOT Built Yet (Roadmap Items)

| Feature | Status | Notes |
|---------|--------|-------|
| Celery + Redis (background tasks) | Planned | Move scraping out of gunicorn threads |
| WhatsApp Business API integration | Marketing only | Landing page mentions it, not implemented |
| Payment / Billing (Razorpay) | Not started | Pricing page exists but no checkout |
| Flow builder | Not started | Mentioned in Starter tier |
| Human handoff | Not started | Mentioned in Growth tier |
| CRM integration | Not started | Mentioned in Growth tier |
| White-label | Not started | Mentioned in Pro tier |
| API access | Not started | Mentioned in Pro tier |
| Multi-language detection | Not started | Gemini handles natively, no explicit routing |
| 30-day challenge / retention | Not started | No retention loop beyond dashboard |
| Analytics beyond super_admin | Not started | No per-bot analytics for regular users |
| File search in embed (user-facing) | Not started | Vector search is internal to Gemini |

---

## Business Context

**Target:** Indian SMBs (10-500 employees) needing 24/7 customer support without hiring agents.

**Differentiation:** Not just another chatbot builder. Focused on:
1. India-first pricing (₹499-₹4,999 vs $50-$500 for Western competitors)
2. WhatsApp-native positioning (even if not yet implemented)
3. Zero-code: Upload PDF → bot is live
4. Gemini-powered vector search (not basic keyword matching)

**Acquisition Strategy:**
- SEO: Compare pages targeting "Chatbase alternative India", "Tidio alternative", etc.
- Organic: Landing page optimized for "AI chatbot for business"
- Waitlist: Email capture for pre-launch leads

**Moat:**
1. Custom lead capture engine (conversational + form + gatekeeper modes)
2. AI-powered lead scoring (High/Medium/Low priority)
3. India pricing (10x cheaper than Western competitors)
4. Gemini vector store integration (better retrieval than basic RAG)

---

*Last updated: July 2026*
*Total routes: 35+ (20 page routes + 15 API endpoints)*
*Total models: 7 (Organization, User, Bot, BotUI, Document, ScrapeJob, Lead, Feedback)*
*Total JS files: 5 (chat, embed, script, sprite, dashboard)*
*Deployed on: DigitalOcean 1GB Droplet*
