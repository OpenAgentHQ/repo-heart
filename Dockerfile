# RepoHeart runtime image for the GitHub Action.
# Kept intentionally small: Python + git + ripgrep are the core needs.
FROM python:3.11-slim

# OCI image labels — populated at build time by docker-publish.yml.
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.title="RepoHeart" \
      org.opencontainers.image.description="The autonomous, event-driven, multi-agent heart of your GitHub repository." \
      org.opencontainers.image.url="https://github.com/OpenAgentHQ/repo-heart" \
      org.opencontainers.image.source="https://github.com/OpenAgentHQ/repo-heart" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}"

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
