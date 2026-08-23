# Support

Thank you for using RepoHeart. This document explains how to get help.

## Documentation

Start here before opening an issue:

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Overview and quick start |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and conventions |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture reference |
| [ROADMAP.md](ROADMAP.md) | Phased build plan and current status |
| [PROJECT.md](PROJECT.md) | Orientation for new contributors |
| [docs/repoheart-final-system-design.md](docs/repoheart-final-system-design.md) | Authoritative system design |
| [CLAUDE.md](CLAUDE.md) | Architecture invariants (also applies to human contributors) |

## Getting Help

### GitHub Discussions

Use [GitHub Discussions](https://github.com/OpenAgentHQ/repoheart/discussions) for:
- Questions about configuration (`opencode.yml`, agent setup)
- Questions about how RepoHeart works
- Ideas and proposals before filing a feature request
- General conversation about the project

### GitHub Issues

Use [GitHub Issues](https://github.com/OpenAgentHQ/repoheart/issues) for:
- Bug reports (use the Bug Report template)
- Feature requests (use the Feature Request template)
- Architecture discussions (open before writing code that might conflict with invariants)

**Search existing issues first** — your question may already be answered.

## Reporting Bugs

Before filing a bug report:

1. Search open and closed issues for a duplicate.
2. Check the [ROADMAP.md](ROADMAP.md) — the behavior may be intentionally
   not yet implemented (RepoHeart is in Phase 0–1).
3. Reproduce the issue on the latest `main` commit.

When filing, use the Bug Report template and include:
- The GitHub event type that triggered the run (e.g., `issues.opened`)
- The relevant section of the Actions run log (structured `key=value` output)
- Your `opencode.yml` config (redact provider API keys)
- Expected vs. actual behavior

## Requesting Features

Before filing a feature request:

1. Read [CLAUDE.md](CLAUDE.md) — the non-negotiable architecture rules apply
   to requested features too. A feature that requires a database, an agent
   writing directly, or a merge action will be declined.
2. Check [ROADMAP.md](ROADMAP.md) — it may already be planned.
3. Open a Discussion to gauge interest before writing a detailed request.

## Security Issues

**Do not open public issues for security vulnerabilities.**
See [SECURITY.md](SECURITY.md) for the responsible disclosure process.

## Frequently Asked Questions

**Q: Do I need to host anything?**  
A: No. RepoHeart runs entirely inside your own GitHub Actions workflow. No
hosted server, no database, no external infrastructure required.

**Q: Which AI providers are supported?**  
A: OpenCode, Claude (Anthropic), and OpenAI are planned for Phase 2. The
provider interface is designed so adding new providers is straightforward.

**Q: Is RepoHeart production-ready?**  
A: Not yet. It is in Phase 0–1 (project setup and deterministic core). See
[ROADMAP.md](ROADMAP.md) for the current status and exit criteria for each phase.

**Q: Can I run RepoHeart on a private repository?**  
A: Yes. RepoHeart uses the standard `GITHUB_TOKEN` provided by Actions and
respects the permissions you grant. No data leaves your Actions runner except
calls to your chosen AI provider.

**Q: RepoHeart did something unexpected in my repo — what do I do?**  
A: Check the Actions run log first (every write decision is logged). Then file
a bug report with the log output. If you believe it was a safety bypass, follow
the [SECURITY.md](SECURITY.md) process instead.

**Q: How can I contribute?**  
A: See [CONTRIBUTING.md](CONTRIBUTING.md). The architecture invariants in
[CLAUDE.md](CLAUDE.md) are non-negotiable — read them before writing code.

---

Thank you for being part of the RepoHeart community.
