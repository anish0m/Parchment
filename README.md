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

## License

MIT
