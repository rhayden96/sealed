"""Closed, validated draft contract shared by manual and planner proposals.

Drafts may describe a well-formed denied environment or duration above 20s so
operators can inspect policy denials. Injection must apply the stricter policy
bounds independently. A draft constructor never evaluates or unseals policy.
"""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FaultId = Literal["redis_down", "handler_latency", "worker_drop"]
TargetId = Literal["api", "redis", "worker"]
PositiveNumber = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
MAX_DELAY_MS = 1000.0
FAULT_TARGETS = {"redis_down": "redis", "handler_latency": "api", "worker_drop": "worker"}
REQUIRED_ASSERTIONS = {
    "redis_down": "fail_closed_on_redis_loss",
    "handler_latency": "latency_recovers_after_reseal",
    "worker_drop": "dropped_jobs_do_not_corrupt_queue",
}
AssertionId = Literal[
    "fail_closed_on_redis_loss",
    "latency_recovers_after_reseal",
    "dropped_jobs_do_not_corrupt_queue",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SLO(StrictModel):
    p95_ms: float = Field(ge=0, le=60000)
    error_rate: float = Field(ge=0, le=1)


class Hypothesis(StrictModel):
    slo: SLO
    must: list[AssertionId] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_assertions(self) -> Hypothesis:
        if len(set(self.must)) != len(self.must):
            raise ValueError("duplicate_assertion")
        return self


class LatencyParams(StrictModel):
    delay_ms: float = Field(ge=0, le=MAX_DELAY_MS)


class DropParams(StrictModel):
    drop_rate: float = Field(ge=0, le=1)


def validate_params(catalog_id: str, params: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    models: dict[str, type[StrictModel]] = {"redis_down": StrictModel, "handler_latency": LatencyParams, "worker_drop": DropParams}
    model = models.get(catalog_id)
    if model is None:
        raise ValueError("unknown_catalog_id")
    if partial and params == {}:
        return {}
    return model.model_validate(params).model_dump()


def validate_hypothesis(catalog_id: str, hypothesis: dict[str, Any]) -> dict[str, Any]:
    result = Hypothesis.model_validate(hypothesis).model_dump()
    if REQUIRED_ASSERTIONS[catalog_id] not in result["must"]:
        raise ValueError("required_catalog_assertion_missing")
    return result


class DraftIn(StrictModel):
    catalog_id: FaultId
    environment: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")
    target: TargetId
    duration_s: PositiveNumber | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    hypothesis: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_fault(self) -> DraftIn:
        if self.target != FAULT_TARGETS[self.catalog_id]:
            raise ValueError("target_catalog_mismatch")
        self.params = validate_params(self.catalog_id, self.params, partial=True)
        if self.hypothesis is not None:
            self.hypothesis = validate_hypothesis(self.catalog_id, self.hypothesis)
        return self


class Experiment(StrictModel):
    id: FaultId
    action: FaultId
    description: str = Field(min_length=1, max_length=1000)
    default_duration_s: PositiveNumber = Field(le=20)
    allowed_targets: list[TargetId] = Field(min_length=1, max_length=1)
    params: dict[str, Any]
    auto_unseal_eligible: bool
    hypothesis: dict[str, Any]

    @model_validator(mode="after")
    def closed_contract(self) -> Experiment:
        if self.action != self.id or self.allowed_targets != [FAULT_TARGETS[self.id]]:
            raise ValueError("catalog_action_or_target_mismatch")
        if self.auto_unseal_eligible != (self.id == "handler_latency"):
            raise ValueError("catalog_auto_unseal_mismatch")
        self.params = validate_params(self.id, self.params)
        self.hypothesis = validate_hypothesis(self.id, self.hypothesis)
        return self


class Catalog(StrictModel):
    version: int = Field(ge=1)
    experiments: list[Experiment] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def exactly_three(self) -> Catalog:
        ids = [item.id for item in self.experiments]
        if len(set(ids)) != 3 or set(ids) != set(FAULT_TARGETS):
            raise ValueError("catalog_requires_three_unique_faults")
        return self


class AutoUnseal(StrictModel):
    enabled: bool
    environment: Literal["demo"]
    catalog_ids: list[FaultId] = Field(min_length=1, max_length=1)
    max_duration_s: PositiveNumber = Field(le=5)

    @model_validator(mode="after")
    def latency_only(self) -> AutoUnseal:
        if self.catalog_ids != ["handler_latency"]:
            raise ValueError("auto_unseal_latency_only")
        return self


class DenyRule(StrictModel):
    environment: Literal["prod"]


class Policy(StrictModel):
    version: int = Field(ge=1)
    environment_allowlist: list[Literal["demo"]] = Field(min_length=1, max_length=1)
    environment_denylist: list[Literal["prod"]] = Field(min_length=1, max_length=1)
    target_allowlist: list[TargetId] = Field(min_length=3, max_length=3)
    max_duration_s: PositiveNumber = Field(le=20)
    max_concurrent_unsealed: int = Field(ge=1, le=1)
    catalog_id_required: bool
    auto_unseal: AutoUnseal
    deny: list[DenyRule] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def fixed_safety_bounds(self) -> Policy:
        if set(self.target_allowlist) != set(FAULT_TARGETS.values()):
            raise ValueError("policy_target_allowlist_mismatch")
        if not self.catalog_id_required:
            raise ValueError("catalog_id_required")
        if self.auto_unseal.max_duration_s > self.max_duration_s:
            raise ValueError("auto_duration_exceeds_policy")
        return self


def validate_catalog(catalog: Any) -> dict[str, Any]:
    return Catalog.model_validate(catalog).model_dump()


def validate_policy(policy: Any) -> dict[str, Any]:
    return Policy.model_validate(policy).model_dump()


def construct_draft(
    store: Any,
    catalog: dict[str, Any],
    *,
    catalog_id: str,
    environment: str,
    target: str,
    duration_s: float | None = None,
    params: dict[str, Any] | None = None,
    hypothesis: dict[str, Any] | None = None,
    source: str = "manual",
    proposal_id: str | None = None,
) -> dict[str, Any]:
    specs = {item["id"]: item for item in catalog["experiments"]}
    spec = specs.get(catalog_id)
    if spec is None:
        raise ValueError("unknown_catalog_id")
    body = DraftIn.model_validate({
        "catalog_id": catalog_id, "environment": environment, "target": target,
        "duration_s": duration_s if duration_s is not None else spec["default_duration_s"],
        "params": {**spec["params"], **(params if params is not None else {})},
        "hypothesis": hypothesis if hypothesis is not None else spec["hypothesis"],
    }).model_dump()
    if proposal_id:
        for existing in store.list_drafts():
            if existing.get("proposal_id") == proposal_id:
                if all(existing.get(key) == value for key, value in body.items()):
                    return existing
                raise ValueError("proposal_identity_conflict")
    draft = {
        **deepcopy(body), "id": store.new_id("d"), "approved": False,
        "status": "draft", "source": source, "created_at": time.time(),
        "catalog_version": catalog["version"],
    }
    if proposal_id:
        draft["proposal_id"] = proposal_id
    return store.put_draft(draft)
