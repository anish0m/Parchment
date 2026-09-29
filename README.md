# Parchment

Parchment is a course-based study platform that converts uploaded notes and PDFs into concept-organized flashcards using machine learning, and schedules review sessions through a spaced repetition system.

## Overview

Parchment allows users to organize study materials by course, upload content as plain text or PDF documents, and automatically generate flashcards from that content. Rather than extracting flashcards line by line, the system groups related material by underlying concept before generating question-answer pairs. Review sessions are prioritized using a Leitner-based spaced repetition system, which resurfaces frequently missed cards more often than mastered ones.

## Features

- **Course-based organization** — create separate courses and keep materials scoped to each one
- **Flexible uploads** — paste text directly or upload PDF notes
- **ML-generated flashcards** — materials are chunked, embedded, and clustered by concept before generating question/answer pairs, so cards reflect ideas rather than isolated sentences
- **Spaced repetition** — a Leitner-box system resurfaces missed cards more frequently and pushes mastered cards further out
- **Study sessions** — a simple flip-card interface per course, with progress tracked across sessions
- **REST API** — everything the web app does, with token auth and OpenAPI docs at `/api/docs/`

## Tech Stack

- **Backend:** Django + Django REST Framework
- **Database:** PostgreSQL
- **Frontend:** Django templates + HTMX + Alpine.js
- **PDF parsing:** pdfplumber
- **ML:** sentence-transformers for embeddings/clustering, lightweight generation step for Q&A pairs
- **Auth:** Django's built-in auth system
- **Containerization:** Docker / Docker Compose

## Data Model

- `Course` — belongs to a user, groups materials and flashcards
- `Material` — an uploaded text or PDF source, with extracted raw text
- `Flashcard` — a generated question/answer pair, tied to a course and source material, with a Leitner box level
- `ReviewLog` — a record of each study attempt (correct/incorrect, and the box move it caused) used to drive spaced repetition
- `StudySession` — one sitting of reviews in a course, with running counts of cards reviewed and answered correctly

## Architecture

```
browser ──HTTPS──▶ reverse proxy ──▶ web: gunicorn + Django ──────────▶ PostgreSQL
                                      ├─ HTML pages (HTMX, Alpine.js)    ├─ app data
                                      ├─ REST API (/api/v1/)             ├─ task queue (Django-Q2)
                                      └─ static files (WhiteNoise)       └─ rate-limit cache
                                                                            ▲
                          worker: Django-Q2 cluster ─── picks up tasks ─────┘
                            └─ PDF text extraction → chunk → embed → cluster → generate cards
```

- **One database does three jobs.** PostgreSQL holds the data, the background task queue and, in production, the cache that rate limits are counted in. There is no Redis to run.
- **The web process never does ML.** Saving a material queues a task after the transaction commits; the worker extracts the text and generates cards while the page polls for progress. The embedding model loads once per worker process.
- **Uploads live on a volume shared by web and worker**, and are never served publicly: each PDF is streamed to its owner by a view that checks ownership.
- **Every query is scoped to the signed-in user**, in the pages and the API alike, so another user's ids return 404.

## Getting started

### With Docker (recommended)

Requires Docker with Compose v2.

```bash
cp .env.example .env          # then set DJANGO_SECRET_KEY
docker compose up --build
```

The app is at http://localhost:8000. Migrations run automatically when the container starts. To create an admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

Compose runs three services: `web` (Django's auto-reloading `runserver`, with the source tree mounted), `worker` (processes uploads in the background) and `db` (PostgreSQL). PostgreSQL data and uploaded files are kept in the `postgres_data` and `media_data` volumes. The worker doesn't auto-reload: after changing generation code, run `docker compose restart worker`.

To have an LLM write the flashcards, set `GEMINI_API_KEY` (free at aistudio.google.com) or `ANTHROPIC_API_KEY` (paid) in `.env`. Without either, the built-in rules write them.

### Without Docker

Requires Python 3.11+ and a running PostgreSQL.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # point DATABASE_URL at your Postgres (host localhost, not db)
python manage.py migrate
python manage.py runserver
python manage.py qcluster     # in a second terminal: the background worker
```

To skip the worker, set `Q_SYNC=True` in `.env`; uploads are then processed during the request.

`requirements.txt` installs PyTorch's CPU-only build for sentence-transformers. If `sentence-transformers` isn't installed, or its model can't be downloaded, generation falls back to TF-IDF embeddings.

### Development workflow

```bash
python manage.py seed_flashcards <username>   # a demo course with 60 sample cards (--count, --reset)
python manage.py simulate_reviews <username>  # play out a week of reviews, then roll back (--days, --accuracy)
pytest                        # run the test suite (pytest --cov for coverage)
ruff check . && ruff format . # lint and format
pre-commit install            # run lint/format on every commit
```

CI (`.github/workflows/ci.yml`) runs lint and formatting, `manage.py check`, a check for missing migrations, OpenAPI schema validation, a production `check --deploy`, and the tests against PostgreSQL with coverage (the build fails below 90%).

### Project layout

| Path | Purpose |
| --- | --- |
| `parchment/settings/` | `base.py` (shared, reads env vars), `dev.py`, `test.py`, `prod.py` |
| `accounts/` | Users and authentication |
| `courses/` | `Course` model and course pages |
| `materials/` | Uploads, PDF text extraction, and the background tasks (`materials/tasks.py`) |
| `flashcards/` | `Flashcard` model, card pages, and the generation pipeline (`flashcards/generation/`) |
| `study/` | Spaced repetition, review logs and study sessions |
| `api/` | The REST API: serializers, viewsets and URLs under `/api/` |
| `templates/` | Shared templates: `_skeleton.html` (loads the theme, HTMX and Alpine.js), `base.html` (header and user menu), `registration/_auth_page.html` (sign-in pages) |
| `static/` | `css/app.css` (the periwinkle theme, light and dark), `js/theme.js` and `js/parchment.js` (theme toggle, user menu, modals, confirmations), images |
| `docker/entrypoint.sh` | Runs migrations and `createcachetable` (and `collectstatic` outside dev) before starting the server |
| `docker/gunicorn.conf.py` | Gunicorn settings for production |
| `docker/backup.sh` | Scheduled database and upload backups |
| `docker-compose.prod.yml` | The production stack: web, worker, PostgreSQL and backups |

### How text is extracted from PDFs

`materials/extraction.py` reads each page with pdfplumber, then `materials/text_cleaning.py` tidies the result:

- Running headers/footers (lines repeated at the top or bottom of most pages) and page numbers are removed.
- Lines wrapped at the page margin are joined back into paragraphs, words hyphenated across lines are rejoined, and list items stay on their own lines.
- Two-column pages (common in papers) are read one column at a time, with any full-width title block first.
- Scanned PDFs with no text layer, password-protected PDFs and damaged files are saved as **Failed** with a message explaining why.

### How flashcards are generated

After an upload, a background worker (Django-Q2, using PostgreSQL as its queue) extracts the text and then runs `flashcards/generation/`:

1. **Chunking** (`chunking.py`): the text is split into sentences and grouped into chunks of about 110 words. Chunks end at headings and paragraph breaks so they rarely mix topics, and otherwise overlap by one sentence. Reference lists and number-heavy fragments are dropped.
2. **Embeddings** (`embeddings.py`): each chunk is embedded with sentence-transformers (`all-MiniLM-L6-v2`), or TF-IDF + LSA when that isn't available.
3. **Concept clustering** (`clustering.py`): KMeans groups the chunks into concepts. The number of concepts is aimed at the document's length (about one per 700 words, at most 12) and fine-tuned by silhouette score. Each concept keeps its most central chunks and its distinctive keywords.
4. **Question generation** (`generators.py`): an LLM (Gemini or Claude) writes up to 5 cards per concept from those chunks, using structured output so every card is a validated question, answer and source quote. The LLM also names each concept. If there's no API key, or the request fails, built-in rules write the cards instead: definition sentences become "What is X?" cards and key terms become fill-in-the-blanks.
5. **Quality checks** (`quality.py`): empty, overlong and self-answering cards are dropped, along with exact and near duplicates, including duplicates of cards already in the course.

The material's page shows each stage live and says which generator wrote the cards. **Regenerate cards** replaces only generated cards you haven't edited or reviewed; your own cards and edits are kept.

### How reviews are scheduled

`study/scheduler.py` runs a Leitner system with 5 boxes. Each answer goes through `record_answer(card, correct)`:

| Box | Due again after |
| --- | --- |
| 1 | 1 day |
| 2 | 2 days |
| 3 | 4 days |
| 4 | 8 days |
| 5 | 16 days |

A correct answer moves the card up one box (box 5 stays in box 5); a wrong one sends it back to box 1. Intervals count whole days from midnight on the day of the review, in `DJANGO_TIME_ZONE`: a card answered at any time today in box 2 is due from midnight the day after tomorrow. The box change, the new due date and a `ReviewLog` row are saved together in one transaction. The intervals live in the `LEITNER_INTERVAL_DAYS` setting, and a system check rejects a list that doesn't have one interval per box.

`due_cards(course)` returns the cards due now, lowest box first and then the longest overdue. New cards are due as soon as they're made.

### Studying

Each course page has a **Study** panel with the number of cards due; the dashboard shows it on every course. **Study now** starts a session that goes through the due cards one at a time:

- Click the card or press **Space** to flip it, then answer **Missed it** (**1** or **←**) or **Got it** (**2** or **→**). Each answer is posted with HTMX and the next card slides in without a page reload.
- Each card appears once per session. A missed card goes back to box 1 and comes back tomorrow.
- When nothing is due, **Study anyway** starts an extra-practice session of up to 20 cards, soonest due first. These answers move cards between boxes like any other.
- The session ends by itself when the cards run out, or with **End session**, and shows a summary: cards reviewed, % correct, cards moved up or back to box 1, and when the next card is due.

The **Progress** page shows cards per box, accuracy over the last 10 sessions, the study streak and the last study date.

## REST API

The API lives under `/api/v1/`. Interactive docs are at **`/api/docs/`** and the OpenAPI schema at `/api/schema/`. Every endpoint only sees the signed-in user's data.

| Endpoint | What it does |
| --- | --- |
| `POST /api/v1/auth/token/` | Exchange a username and password for an API token |
| `GET/POST /api/v1/courses/`, `GET/PATCH/DELETE /api/v1/courses/{id}/` | Courses, with material, card and due counts |
| `GET /api/v1/courses/{id}/due/` | Cards due now, in study order |
| `GET/POST /api/v1/materials/`, `GET/DELETE /api/v1/materials/{id}/` | Materials (`?course=`); POST pasted text as JSON or a PDF as multipart |
| `POST /api/v1/materials/{id}/regenerate/` | Regenerate a material's cards (409 while it's processing) |
| `GET/POST /api/v1/flashcards/`, `GET/PATCH/DELETE /api/v1/flashcards/{id}/` | Cards (`?course=`, `?material=`, `?box=`, `?due=true`) |
| `POST /api/v1/flashcards/{id}/review/` | Answer a card: `{"correct": true}`, optionally with a `session` id |
| `GET /api/v1/reviews/` | Review history (`?course=`, `?flashcard=`, `?session=`) |

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/token/ -d username=me -d password=secret | jq -r .token)
curl -H "Authorization: Token $TOKEN" localhost:8000/api/v1/courses/1/due/
curl -H "Authorization: Token $TOKEN" -F course=1 -F source_type=pdf -F file=@notes.pdf localhost:8000/api/v1/materials/
curl -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" -d '{"correct": true}' localhost:8000/api/v1/flashcards/42/review/
```

Lists are paginated (`?page=`, `?page_size=` up to 100). The browser's session cookie works too; with it, write requests need the CSRF token like any form. Uploads and card generation are rate limited per user (shared with the web pages) and answer `429` with a `Retry-After` header when the limit is reached.

## Deployment

`docker-compose.prod.yml` runs the production stack: **web** (gunicorn with WhiteNoise for static files), **worker** (the background task cluster), **db** (PostgreSQL 16) and **backup** (scheduled dumps).

1. On a server with Docker, clone the repository and create `.env` from `.env.example`. At minimum set:
   - `DJANGO_SECRET_KEY`: a long random string (`python -c "import secrets; print(secrets.token_urlsafe(50))"`)
   - `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`, e.g. `parchment.example.com` and `https://parchment.example.com`
   - `POSTGRES_PASSWORD`, and `DATABASE_URL` with the same password and host `db`
   - `EMAIL_URL` so password reset emails can be sent (the production settings always turn `DEBUG` off)
   - optionally `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`
2. Start it: `docker compose -f docker-compose.prod.yml up -d --build`. The web container migrates the database and collects static files on start; the worker waits until web is healthy.
3. Put a TLS-terminating reverse proxy (Caddy, nginx or a cloud load balancer) in front of port 8000 (`WEB_PORT` changes it) that sets `X-Forwarded-Proto`. Plain HTTP requests are redirected to HTTPS. Once HTTPS works, consider `DJANGO_SECURE_HSTS_SECONDS=31536000`.
4. Create an admin account: `docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser`.

To update, `git pull` and run the `up -d --build` command again.

**Health.** `GET /healthz/` answers `{"status": "ok", "database": "ok"}`, or `503` when the database is unreachable. It skips the host and HTTPS checks so Docker can call it from inside the container; the web service's health check uses it.

**Logs.** In production every log line is a JSON object (time, level, logger, message and, for request errors, method, path and user id), ready for a log collector; gunicorn writes access logs to stdout too. `DJANGO_LOG_FORMAT=text` switches to plain lines. `docker compose -f docker-compose.prod.yml logs -f web worker` follows them.

**Sizing.** The worker loads the embedding model (about 1 GB of memory, capped by `WORKER_MEMORY`, default `2g`). Gunicorn runs `WEB_CONCURRENCY` workers (default 3).

**Backups.** The backup service writes `parchment-db-<time>.dump` (a `pg_dump` custom-format dump) and `parchment-media-<time>.tar.gz` (the uploaded PDFs) to `./backups` every 24 hours (`BACKUP_INTERVAL_SECONDS`), keeping 7 days (`BACKUP_KEEP_DAYS`). Copy that folder off the server regularly. To take a backup now, or to restore one:

```bash
docker compose -f docker-compose.prod.yml run --rm backup once
docker compose -f docker-compose.prod.yml exec -T db pg_restore -U parchment -d parchment --clean --if-exists --no-owner < backups/parchment-db-<time>.dump
docker compose -f docker-compose.prod.yml run --rm --no-deps -v ./backups:/backups:ro --entrypoint tar web \
  -xzf /backups/parchment-media-<time>.tar.gz -C /app/media
```

### Free hosting (Hugging Face Spaces)

For a free demo with no payment method, the app runs on a [Hugging Face Space](https://huggingface.co/docs/hub/spaces-sdks-docker) (Docker, 16 GB of memory on the free CPU tier, so the embedding model fits) and the database on [Supabase](https://supabase.com)'s free PostgreSQL. The web server and the background worker share the Space's one container (`RUN_WORKER=1`). Every push to the `deployment` branch runs `.github/workflows/deploy.yml`, which uploads the code to the Space and copies the secrets over; the Space then rebuilds and restarts.

1. **Database.** Create a free Supabase project. Under **Connect**, copy the **Session pooler** connection string (the direct one needs IPv6, which Spaces lack) and fill in the database password.
2. **Hugging Face.** Create a free account, then an access token with **Write** permission (Settings → Access Tokens).
3. **GitHub secrets.** In this repository's Settings → Secrets and variables → Actions, add:
   - `HF_TOKEN`: the Hugging Face token
   - `DATABASE_URL`: the Supabase connection string
   - `DJANGO_SECRET_KEY`: a long random string (`python -c "import secrets; print(secrets.token_urlsafe(50))"`)
   - optionally `GEMINI_API_KEY` (free at aistudio.google.com), `ANTHROPIC_API_KEY`, and `EMAIL_URL` for password reset emails, e.g. `smtp+tls://you@gmail.com:<app password>@smtp.gmail.com:587`
   - optionally a *variable* `HF_SPACE` (e.g. `username/parchment`); by default the Space is `<your Hugging Face user>/parchment`
4. **Deploy.** Push to `deployment`, or run the Deploy workflow from the Actions tab. The first build takes about 10 minutes. The app is at `https://<user>-parchment.hf.space` and is also shown on the Space's page.

The Space finds its own address (`SPACE_HOST`), so `DJANGO_ALLOWED_HOSTS` isn't needed, and it lets `huggingface.co` show the app in a frame. Limits of the free tier:

- The Space sleeps after 48 hours without visitors; the next visit wakes it in a minute or two. Supabase pauses a project after a week of inactivity (resume it from its dashboard).
- The container's disk is wiped on every restart, so uploaded PDFs disappear. Courses, extracted text and flashcards are in the database and stay; only the link to the original PDF breaks.
- The Space has no shell. To create an admin account, run `python manage.py createsuperuser` on your own machine with `DATABASE_URL` pointed at Supabase.

## Security

- Every page, API endpoint and file download checks that the object belongs to the signed-in user; a test visits every URL that takes an id as another user and expects a 404.
- CSRF protection covers forms, HTMX requests (the token is sent as a header) and session-authenticated API calls. Token-authenticated API calls don't use cookies.
- Uploads are checked for type (`.pdf` and a `%PDF-` header), size and page count, and requests bigger than the upload limit are refused before they're read.
- Uploads, card generation and failed sign-ins are rate limited.
- A Content-Security-Policy header limits scripts to this site and jsDelivr, and the CDN scripts are pinned with subresource integrity hashes.
- Production settings: `DEBUG` off, HTTPS redirect, secure and HttpOnly cookies, `nosniff`, `X-Frame-Options: DENY`, same-origin referrers (on a Hugging Face Space, only `huggingface.co` may frame the app). CI runs `manage.py check --deploy`.

### Configuration

All settings come from environment variables (see `.env.example`):

| Variable | Default | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | — | Required |
| `DATABASE_URL` | — | Required, e.g. `postgres://user:pass@host:5432/db` |
| `DJANGO_DEBUG` | `True` in dev, `False` in prod | |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,0.0.0.0` in dev | Comma-separated |
| `DJANGO_SETTINGS_MODULE` | `parchment.settings.dev` via `manage.py`, `.prod` in the Docker image | |
| `DJANGO_TIME_ZONE` | `UTC` | Time zone for due dates: cards come due at midnight here, e.g. `Asia/Dhaka` |
| `DJANGO_MEDIA_ROOT` | `./media` | Where uploaded PDFs are stored. Not served publicly: each PDF is served to its owner through the app |
| `MATERIAL_MAX_UPLOAD_MB` | `20` | Largest PDF that can be uploaded |
| `MATERIAL_MAX_PDF_PAGES` | `300` | Most pages a PDF can have |
| `MATERIAL_MAX_TEXT_CHARS` | `300000` | Longest pasted text |
| `EMAIL_URL` | `smtp://localhost:25` (prod) | Outgoing mail for password resets, e.g. `smtp+tls://user:pass@host:587`. Dev prints emails to the console |
| `GEMINI_API_KEY` | — | Free; lets Gemini write the flashcards |
| `ANTHROPIC_API_KEY` | — | Paid; lets Claude write the flashcards |
| `CARD_GENERATOR` | `auto` | `auto` (Gemini if key set, else Claude, else rules), `gemini`, `claude` or `rules` |
| `CARD_GENERATION_GEMINI_MODEL` | `gemini-flash-latest` | Gemini model for card writing |
| `CARD_GENERATION_MODEL` | `claude-opus-5` | Claude model for card writing |
| `CARD_GENERATION_EFFORT` | `medium` | `low`, `medium` or `high`: how much Claude thinks per request |
| `EMBEDDING_BACKEND` | `auto` | `auto`, `sentence-transformers` or `tfidf` |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | |
| `MAX_CONCEPTS_PER_MATERIAL` / `MAX_CARDS_PER_CONCEPT` / `MAX_CARDS_PER_MATERIAL` | `12` / `5` / `60` | Limits on how many concepts and cards are made |
| `Q_WORKERS` / `Q_TIMEOUT` / `Q_SYNC` | `2` / `900` / `False` | Worker processes, seconds a task may run, and whether to run tasks inline without a worker |
| `RATE_LIMIT_UPLOADS` / `RATE_LIMIT_GENERATION` | `30/hour` / `20/hour` | Per user, web and API together |
| `RATE_LIMIT_LOGIN` | `30/hour` | Failed sign-ins per IP address |
| `RATE_LIMIT_USER` / `RATE_LIMIT_ANON` | `2000/hour` / `60/hour` | All API requests |
| `CACHE_URL` | memory (dev), `dbcache://parchment_cache` (prod) | Where rate-limit counts are kept |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | Comma-separated, e.g. `https://parchment.example.com` |
| `DJANGO_SECURE_SSL_REDIRECT` / `DJANGO_SECURE_HSTS_SECONDS` | `True` / `0` | Production HTTPS redirect and HSTS |
| `DJANGO_CSP` | see `settings/base.py` | Content-Security-Policy header; empty turns it off |
| `DJANGO_LOG_FORMAT` / `DJANGO_LOG_LEVEL` | `text` (dev), `json` (prod) / `INFO` | |
| `WEB_CONCURRENCY` / `GUNICORN_TIMEOUT` | `3` / `120` | Gunicorn workers and request timeout (seconds) |
| `WEB_PORT` / `WORKER_MEMORY` | `8000` / `2g` | Production Compose: published port and worker memory cap |
| `BACKUP_INTERVAL_SECONDS` / `BACKUP_KEEP_DAYS` / `BACKUP_DIR` | `86400` / `7` / `./backups` | Production backups |

## License

MIT: see [LICENSE](LICENSE).
