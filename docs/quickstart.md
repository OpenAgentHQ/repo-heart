# RepoHeart Quickstart

This guide walks you through setting up RepoHeart in a GitHub repository.

RepoHeart runs AI-powered repository agents through GitHub Actions. It can help with issue triage, duplicate detection, pull-request review, code quality, security checks, CI repair, and conflict resolution.

## Prerequisites

Before setting up RepoHeart, make sure you have:

- A GitHub repository
- Permission to add GitHub Actions workflows and repository secrets
- GitHub Actions enabled
- An API key for the AI provider you want to use

## 1. Add the RepoHeart workflow

Create the following file in your repository:

`.github/workflows/repoheart.yml`

```yaml
name: RepoHeart

on:
  issues:
    types: [opened, edited]

  issue_comment:
    types: [created]

  pull_request:
    types: [opened, synchronize, reopened]

  pull_request_review:
    types: [submitted]

  push:

  workflow_run:
    workflows: ["*"]
    types: [completed]

  release:
    types: [published]

permissions:
  contents: write
  issues: write
  pull-requests: write
  checks: read
  actions: read

concurrency:
  group: repoheart-${{ github.event.issue.number || github.event.pull_request.number || github.ref }}
  cancel-in-progress: false

jobs:
  repoheart:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run RepoHeart
        uses: OpenAgentHQ/repoheart@main
        with:
          config: opencode.yml
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
