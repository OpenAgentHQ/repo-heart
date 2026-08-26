# Security Policy

## Supported Versions

RepoHeart v1.0 — fully implemented. All 7 roadmap phases complete with safety invariants verified. Security fixes follow the same v1.0 release process.
the latest commit on `main` only.

| Version | Supported |
|---------|-----------|
| `main` (latest) | Yes |
| Older commits | No |

## Reporting a Vulnerability

**Do NOT report security vulnerabilities through public GitHub issues.**

Security issues in RepoHeart have potentially high impact because the tool
executes writes inside user repositories via the Safety Gate. This includes
classes of vulnerability such as:

- A way to bypass the Safety Gate and trigger an unauthorized write
- Prompt injection via issue/PR text that causes an unsafe action
- An agent that can escalate its own risk level at runtime
- Credentials or tokens exposed in logs or comments
- Unsafe merge, force-push, or history-rewrite paths

To report a vulnerability, send an email to **himanshu231204@gmail.com** with
the subject line `[SECURITY] RepoHeart vulnerability report`.

### What to Include

- Description of the vulnerability and the affected component
- Steps to reproduce (a minimal event payload or crafted issue/PR body if applicable)
- Potential impact (what an attacker could achieve)
- Suggested fix (if any)

### Response Timeline

| Milestone | Target |
|-----------|--------|
| Acknowledgment | Within 48 hours |
| Initial assessment | Within 5 business days |
| Fix released (critical issues) | Within 30 days |
| Public disclosure | After fix is released |

## Security Architecture Notes

RepoHeart is designed with safety as the first principle. The following
invariants are enforced in code (not configuration) and are the most
security-relevant parts of the system:

- **Safety Gate**: every write requires a `Decision.ALLOW` token from
  `SafetyGate.authorize()`. There is no write path that bypasses it.
- **No self-escalation**: an agent's risk level is a static ceiling; no
  runtime mechanism can raise it.
- **No `MERGE` action**: the `MERGE` kind does not exist in `ActionKind`.
  It cannot be expressed, authorized, or triggered by any prompt.
- **No force-push**: not present in `ActionKind`; no git primitive wraps it.
- **Stateless between runs**: no persistent database; state lives in GitHub.
  A compromised run cannot persist malicious state across invocations.

If you believe any of these invariants can be violated, that is a critical
vulnerability — please report it immediately.

## Security Best Practices for Operators

- Grant only the permissions listed in the workflow template (`contents: write`,
  `issues: write`, `pull-requests: write`). Do not add broader scopes.
- Never store provider API keys anywhere except repository secrets.
- Review the `opencode.yml` config before enabling high-risk agents (CI Repair,
  Conflict Resolution).
- Monitor the Actions run log — it is the audit trail for every proposed action
  and its Safety Gate decision.

## Acknowledgments

We thank all researchers who responsibly disclose vulnerabilities. Confirmed
disclosures will be credited in the release notes (with the reporter's consent).
