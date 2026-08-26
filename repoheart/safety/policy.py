"""Risk levels, action kinds, and the permission table.

These enums are load-bearing safety primitives. Two invariants are enforced
structurally here rather than by configuration:

  * There is no ``MERGE`` member in ``ActionKind``. Merge is not "denied by
    policy" in the MVP — it is unreachable because it does not exist. This
    closes prompt-injection-via-issue-text as a path to an unsafe merge.
  * Risk levels are ordered, so an agent's static ceiling can be compared
    against a proposed action's risk without any config lookup.
"""

from __future__ import annotations

from enum import Enum, IntEnum


class RiskLevel(IntEnum):
    """Ordered risk levels. Higher is more dangerous."""

    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class ActionKind(Enum):
    """The complete set of actions RepoHeart can propose in the MVP.

    Note the deliberate absence of any merge/force-push member. If it is not
    in this enum, an agent cannot express it, the Safety Gate cannot authorize
    it, and no prompt content can conjure it.
    """

    # SAFE
    READ_REPO = "read_repo"
    ADD_LABEL = "add_label"
    REMOVE_LABEL = "remove_label"
    POST_COMMENT = "post_comment"
    CREATE_PR_REVIEW = "create_pr_review"
    # LOW
    CREATE_BRANCH = "create_branch"
    # MEDIUM
    MODIFY_CODE = "modify_code"
    COMMIT = "commit"
    PUSH_BRANCH = "push_branch"
    # HIGH (mostly unreachable in the MVP; present only for completeness)
    DELETE_BRANCH = "delete_branch"


# Baseline risk of each action kind. An agent may never propose an action at a
# risk lower than its intrinsic level here.
ACTION_RISK: dict[ActionKind, RiskLevel] = {
    ActionKind.READ_REPO: RiskLevel.SAFE,
    ActionKind.ADD_LABEL: RiskLevel.SAFE,
    ActionKind.REMOVE_LABEL: RiskLevel.SAFE,
    ActionKind.POST_COMMENT: RiskLevel.SAFE,
    ActionKind.CREATE_PR_REVIEW: RiskLevel.SAFE,
    ActionKind.CREATE_BRANCH: RiskLevel.LOW,
    ActionKind.MODIFY_CODE: RiskLevel.MEDIUM,
    ActionKind.COMMIT: RiskLevel.MEDIUM,
    ActionKind.PUSH_BRANCH: RiskLevel.MEDIUM,
    ActionKind.DELETE_BRANCH: RiskLevel.HIGH,
}


class Decision(Enum):
    """The Safety Gate's verdict on a single proposed action."""

    ALLOW = "allow"
    ESCALATE = "escalate"
    DENY = "deny"
