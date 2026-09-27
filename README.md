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
- `ReviewLog` — a record of each study attempt (correct/incorrect) used to drive spaced repetition

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

The dev container mounts the source tree and uses Django's auto-reloading `runserver`. PostgreSQL data and uploaded files are kept in the `postgres_data` and `media_data` volumes.

### Without Docker

Requires Python 3.11+ and a running PostgreSQL.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # point DATABASE_URL at your Postgres (host localhost, not db)
python manage.py migrate
python manage.py runserver
```

### Development workflow

```bash
python manage.py seed_flashcards <username>   # a demo course with 60 sample cards (--count, --reset)
pytest                        # run the test suite
ruff check . && ruff format . # lint and format
pre-commit install            # run lint/format on every commit
```

CI (`.github/workflows/ci.yml`) runs lint, `manage.py check`, a production `check --deploy`, and the tests against PostgreSQL.

### Project layout

| Path | Purpose |
| --- | --- |
| `parchment/settings/` | `base.py` (shared, reads env vars), `dev.py`, `test.py`, `prod.py` |
| `accounts/` | Users and authentication |
| `courses/` | `Course` model and course pages |
| `materials/` | Uploads and PDF text extraction |
| `flashcards/` | `Flashcard` model and the generation pipeline |
| `study/` | Spaced repetition, review logs and study sessions |
| `templates/` | Shared templates; `base.html` loads HTMX and Alpine.js |
| `static/` | CSS and other static assets |
| `docker/entrypoint.sh` | Runs migrations (and `collectstatic` outside dev) before starting the server |

### How text is extracted from PDFs

`materials/extraction.py` reads each page with pdfplumber, then `materials/text_cleaning.py` tidies the result:

- Running headers/footers (lines repeated at the top or bottom of most pages) and page numbers are removed.
- Lines wrapped at the page margin are joined back into paragraphs, words hyphenated across lines are rejoined, and list items stay on their own lines.
- Two-column pages (common in papers) are read one column at a time, with any full-width title block first.
- Scanned PDFs with no text layer, password-protected PDFs and damaged files are saved as **Failed** with a message explaining why.

Extraction currently runs during the upload request; it moves to a background worker in Phase 4.

### Configuration

All settings come from environment variables (see `.env.example`):

| Variable | Default | Notes |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | — | Required |
| `DATABASE_URL` | — | Required, e.g. `postgres://user:pass@host:5432/db` |
| `DJANGO_DEBUG` | `True` in dev, `False` in prod | |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,0.0.0.0` in dev | Comma-separated |
| `DJANGO_SETTINGS_MODULE` | `parchment.settings.dev` via `manage.py`, `.prod` in the Docker image | |
| `DJANGO_MEDIA_ROOT` | `./media` | Where uploaded PDFs are stored. Not served publicly: each PDF is served to its owner through the app |
| `MATERIAL_MAX_UPLOAD_MB` | `20` | Largest PDF that can be uploaded |
| `MATERIAL_MAX_PDF_PAGES` | `300` | Most pages a PDF can have |
| `MATERIAL_MAX_TEXT_CHARS` | `300000` | Longest pasted text |
| `EMAIL_URL` | `smtp://localhost:25` (prod) | Outgoing mail for password resets, e.g. `smtp+tls://user:pass@host:587`. Dev prints emails to the console |

## License

MIT
