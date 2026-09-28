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
- `ReviewLog` — a record of each study attempt (correct/incorrect, and the box move it caused) used to drive spaced repetition
- `StudySession` — one sitting of reviews in a course, with running counts of cards reviewed and answered correctly

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
| `materials/` | Uploads, PDF text extraction, and the background tasks (`materials/tasks.py`) |
| `flashcards/` | `Flashcard` model, card pages, and the generation pipeline (`flashcards/generation/`) |
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

## License

MIT
