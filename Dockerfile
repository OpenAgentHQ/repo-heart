# RepoHeart runtime image for the GitHub Action.
# Kept intentionally small: Python + git + ripgrep are the core needs.
FROM python:3.11-slim

# git is required for git_ops / repo_access; ripgrep for lexical retrieval.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repoheart

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY repoheart ./repoheart
RUN pip install --no-cache-dir .

# The action entrypoint. GitHub passes `--config <path>` via action.yml args.
ENTRYPOINT ["python", "-m", "repoheart.main"]
