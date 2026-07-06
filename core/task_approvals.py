"""Cross-surface approval round-trip for autonomous tasks (§6.3).

When a running task wants a protected tool (shell command on the denylist,
git write, delete), it no longer gets a flat refusal: the task pauses as
``blocked`` with a pending-approval record, the owner is pinged on whatever
surface they use, and they can approve or deny from Telegram (/approve N,
/deny N) or the web UI. Approval mints a one-shot grant for that exact
action; the task resumes and re-runs it.
"""

from __future__ import annotations

import json
from datetime import datetime

from core import task_store
from core.approval_policy import command_text_from_inputs

# A grant is only valid for this long after approval (safety: a stale grant
# shouldn't authorize an action days later).
GRANT_TTL_MINUTES = 60


def _constraints(task: dict) -> dict:
    constraints = task.get("constraints")
    if isinstance(constraints, str):
        try:
            constraints = json.loads(constraints)
        except (json.JSONDecodeError, TypeError):
            constraints = {}
    return dict(constraints or {})


def _save_constraints(task_id: int, constraints: dict, **fields) -> None:
    task_store.update_task(task_id, constraints=json.dumps(constraints), **fields)


def action_summary(tool: str, inputs: dict) -> str:
    command = command_text_from_inputs(inputs or {})
    if command:
        return command[:300]
    path = (inputs or {}).get("path") or (inputs or {}).get("source_path")
    if path:
        return str(path)[:300]
    try:
        return json.dumps(inputs or {}, default=str)[:300]
    except Exception:
        return str(inputs)[:300]


def pending_approval(task: dict) -> dict | None:
    pending = _constraints(task).get("_pending_approval")
    return pending if isinstance(pending, dict) else None


def request_approval(task: dict, tool: str, inputs: dict) -> dict:
    """Record a pending approval and block the task. Returns the record."""
    task_id = task["id"]
    record = {
        "tool": tool,
        "summary": action_summary(tool, inputs),
        "requested_at": datetime.now().isoformat(),
    }
    constraints = _constraints(task)
    constraints["_pending_approval"] = record
    _save_constraints(task_id, constraints, status="blocked")
    task_store.append_history(task_id, {
        "type": "approval_requested",
        "tool": tool,
        "detail": record["summary"],
    })
    return record


def _resume_with_guidance(task_id: int, guidance: str) -> None:
    task = task_store.get_task(task_id)
    if not task:
        return
    messages = list(task.get("messages") or [])
    if messages:
        messages.append({"role": "user", "content": guidance})
        task_store.save_session(task_id, messages)
    task_store.update_task(
        task_id, status="active", next_run_at=datetime.now().isoformat()
    )


def approve(task_id: int) -> tuple[bool, str]:
    """Grant the pending action once and resume the task."""
    task = task_store.get_task(task_id)
    if not task:
        return False, f"Task {task_id} not found."
    pending = pending_approval(task)
    if not pending:
        return False, f"Task {task_id} has no pending approval."

    constraints = _constraints(task)
    constraints.pop("_pending_approval", None)
    grants = constraints.get("_approved_grants")
    grants = list(grants) if isinstance(grants, list) else []
    grants.append({
        "tool": pending.get("tool"),
        "summary": pending.get("summary"),
        "granted_at": datetime.now().isoformat(),
    })
    constraints["_approved_grants"] = grants
    _save_constraints(task_id, constraints)
    task_store.append_history(task_id, {
        "type": "approval_granted",
        "tool": pending.get("tool"),
        "detail": pending.get("summary"),
    })
    _resume_with_guidance(
        task_id,
        f"The owner APPROVED running {pending.get('tool')} "
        f"({pending.get('summary')}). This is a one-time approval — run that "
        "exact action again now and continue the task.",
    )
    return True, (
        f"Approved. Task {task_id} will run {pending.get('tool')} and continue."
    )


def deny(task_id: int) -> tuple[bool, str]:
    """Refuse the pending action and resume the task without it."""
    task = task_store.get_task(task_id)
    if not task:
        return False, f"Task {task_id} not found."
    pending = pending_approval(task)
    if not pending:
        return False, f"Task {task_id} has no pending approval."

    constraints = _constraints(task)
    constraints.pop("_pending_approval", None)
    _save_constraints(task_id, constraints)
    task_store.append_history(task_id, {
        "type": "approval_denied",
        "tool": pending.get("tool"),
        "detail": pending.get("summary"),
    })
    _resume_with_guidance(
        task_id,
        f"The owner DENIED running {pending.get('tool')} "
        f"({pending.get('summary')}). Do NOT retry it or work around it with a "
        "different tool. Adjust the plan, or finish honestly and report what "
        "was blocked.",
    )
    return True, f"Denied. Task {task_id} will continue without that action."


def consume_grant(task: dict, tool: str, inputs: dict) -> bool:
    """One-shot grant check: True if this exact action was approved recently.

    Matching is strict: same tool, and for command tools the same command
    string (compared via the summary). Consumed grants are removed.
    """
    constraints = _constraints(task)
    grants = constraints.get("_approved_grants")
    if not isinstance(grants, list) or not grants:
        return False

    now = datetime.now()
    summary = action_summary(tool, inputs)
    remaining: list = []
    matched = False
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        try:
            granted_at = datetime.fromisoformat(str(grant.get("granted_at")))
            expired = (now - granted_at).total_seconds() > GRANT_TTL_MINUTES * 60
        except (ValueError, TypeError):
            expired = True
        if expired:
            continue  # drop silently
        if not matched and grant.get("tool") == tool and grant.get("summary") == summary:
            matched = True
            continue  # consume
        remaining.append(grant)

    if matched or len(remaining) != len(grants):
        constraints["_approved_grants"] = remaining
        _save_constraints(task["id"], constraints)
        task["constraints"] = constraints
    return matched
