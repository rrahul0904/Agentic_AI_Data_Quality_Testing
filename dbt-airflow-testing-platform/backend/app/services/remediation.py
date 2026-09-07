"""Controlled remediation (Architecture spec §34 / Master Prompt §31-32).

Remediation level implemented here: LEVEL 3 (Generate Patch) with LEVEL 4
(Human-Approved Execution) -- a proposal is recorded, a human approves it
via the API, and only then is a literal, narrowly-scoped find/replace
applied to one file inside the target dbt project's own directory. No
LLM authors the patch in this phase (see docs/IMPLEMENTATION_STATUS.md) --
the proposal's `find`/`replace` text is supplied by whoever calls the API
(a human today; an agent's structured output later, unchanged shape).
Nothing here executes arbitrary code or touches any path outside the
project directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import DbtProject
from ..models_quality import RemediationProposal


class RemediationError(ValueError):
    pass


def build_proposed_change(find_text: str, replace_text: str) -> str:
    return json.dumps({"find": find_text, "replace": replace_text})


def apply_remediation(proposal: RemediationProposal, project: DbtProject) -> None:
    if proposal.status != "APPROVED":
        raise RemediationError(f"proposal {proposal.id} must be APPROVED before it can be applied")
    if not proposal.target_file:
        raise RemediationError("proposal has no target_file")

    project_root = Path(project.project_dir).resolve()
    target_path = (project_root / proposal.target_file).resolve()
    if project_root not in target_path.parents and target_path != project_root:
        raise RemediationError(f"target_file escapes the project directory: {proposal.target_file}")
    if not target_path.exists():
        raise RemediationError(f"target file does not exist: {target_path}")

    change = json.loads(proposal.proposed_change)
    find_text, replace_text = change["find"], change["replace"]

    content = target_path.read_text()
    if find_text not in content:
        raise RemediationError("find_text not found in target_file -- file may have already changed")
    if content.count(find_text) > 1:
        raise RemediationError("find_text is not unique in target_file -- refusing an ambiguous patch")

    target_path.write_text(content.replace(find_text, replace_text, 1))
