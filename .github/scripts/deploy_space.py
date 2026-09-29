"""Deploy this repository to a Hugging Face Space (Docker SDK).

Run by .github/workflows/deploy.yml. Reads from the environment:
  HF_TOKEN            a Hugging Face access token with write permission (required)
  HF_SPACE            the Space id, e.g. "username/parchment" (default: <your user>/parchment)
  DJANGO_SECRET_KEY, DATABASE_URL                  copied to the Space's secrets (required)
  GEMINI_API_KEY, ANTHROPIC_API_KEY, EMAIL_URL,
  DJANGO_DEFAULT_FROM_EMAIL                        copied to the Space's secrets when set
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_SECRETS = ["DJANGO_SECRET_KEY", "DATABASE_URL"]
OPTIONAL_SECRETS = ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "EMAIL_URL", "DJANGO_DEFAULT_FROM_EMAIL"]

# Plain settings for the Space. The web server and the background worker share one
# container, and the worker checks the queue once a second to spare the database.
VARIABLES = {"RUN_WORKER": "1", "Q_POLL": "1", "WEB_CONCURRENCY": "2"}

# Files the Space doesn't need.
IGNORE = shutil.ignore_patterns(
    ".git",
    ".github",
    ".venv",
    "venv",
    "__pycache__",
    "*.pyc",
    ".env",
    "media",
    "staticfiles",
    "parchment-ui",
    "tests",
    "backups",
    ".coverage",
    ".pytest_cache",
    ".ruff_cache",
)

# Hugging Face reads the Space's settings from the front matter of its README.
SPACE_HEADER = """---
title: Parchment
emoji: 📜
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
short_description: Turn notes and PDFs into spaced-repetition flashcards
---

"""


def fail(message):
    print(f"::error::{message}")
    sys.exit(1)


def main():
    token = os.environ.get("HF_TOKEN")
    if not token:
        fail("Add a Hugging Face write token as the HF_TOKEN secret (see README, Free hosting).")
    missing = [name for name in REQUIRED_SECRETS if not os.environ.get(name)]
    if missing:
        fail(f"Add these repository secrets: {', '.join(missing)} (see README, Free hosting).")

    api = HfApi(token=token)
    space = os.environ.get("HF_SPACE") or f"{api.whoami()['name']}/parchment"
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)

    for name in REQUIRED_SECRETS + OPTIONAL_SECRETS:
        if value := os.environ.get(name):
            api.add_space_secret(space, name, value)
    for name, value in VARIABLES.items():
        api.add_space_variable(space, name, value)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "space"
        shutil.copytree(ROOT, staging, ignore=IGNORE)
        readme = staging / "README.md"
        readme.write_text(SPACE_HEADER + readme.read_text(encoding="utf-8"), encoding="utf-8")
        api.upload_folder(
            folder_path=staging,
            repo_id=space,
            repo_type="space",
            delete_patterns="*",  # remove files that are gone from the repository
            commit_message=f"Deploy {os.environ.get('GITHUB_SHA', 'local')[:7]}",
        )

    owner, name = space.split("/")
    host = f"{owner}-{name}".lower().replace("_", "-").replace(".", "-")
    print(f"Deployed to https://huggingface.co/spaces/{space}")
    print(f"The app will be at https://{host}.hf.space once the Space finishes building.")


if __name__ == "__main__":
    main()
