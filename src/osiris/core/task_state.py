"""Etat type de la tache (`TaskState`).

Structure deterministe et adressable : pas de vecteurs, pas de similarite.
Une tache = un OBJECTIF + un PLAN + des CONTRAINTES + des DECISIONS epinglees
+ un etat de FICHIERS / RESULTATS / ECHECS / LECONS / HANDOFFS + un BUDGET.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from osiris.core.ids import new_id


@dataclass
class Plan:
    """Plan d'etapes de la tache."""

    steps: list[str] = field(default_factory=list)
    current: int = 0
    done: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Plan:
        return cls(
            steps=list(data.get("steps", [])),
            current=int(data.get("current", 0)),
            done=list(data.get("done", [])),
        )


@dataclass
class FileEntry:
    """Etat d'un fichier vu par la tache."""

    path: str
    content_hash: str | None = None
    mtime: float | None = None
    last_read_at: float | None = None
    ref: str | None = None
    size_bytes: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FileEntry:
        return cls(
            path=data["path"],
            content_hash=data.get("content_hash"),
            mtime=data.get("mtime"),
            last_read_at=data.get("last_read_at"),
            ref=data.get("ref"),
            size_bytes=int(data.get("size_bytes", 0)),
        )


@dataclass
class ToolResultEntry:
    """Reference vers un resultat d'outil externalise."""

    cache_key: str
    ref: str | None = None
    size_bytes: int = 0
    tokens: int = 0
    cost: float = 0.0
    ttl: float = 0.0
    reusable: bool = True
    created_at: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ToolResultEntry:
        return cls(
            cache_key=data["cache_key"],
            ref=data.get("ref"),
            size_bytes=int(data.get("size_bytes", 0)),
            tokens=int(data.get("tokens", 0)),
            cost=float(data.get("cost", 0.0)),
            ttl=float(data.get("ttl", 0.0)),
            reusable=bool(data.get("reusable", True)),
            created_at=float(data.get("created_at", 0.0)),
        )


@dataclass
class FailureEntry:
    """Signature d'echec et nombre d'essais."""

    signature: str
    tool: str = ""
    args_hash: str = ""
    count: int = 1
    first_at: float = 0.0
    last_at: float = 0.0
    lesson: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FailureEntry:
        return cls(
            signature=data["signature"],
            tool=data.get("tool", ""),
            args_hash=data.get("args_hash", ""),
            count=int(data.get("count", 1)),
            first_at=float(data.get("first_at", 0.0)),
            last_at=float(data.get("last_at", 0.0)),
            lesson=data.get("lesson", ""),
        )


@dataclass
class BudgetState:
    """Suivi du budget de la tache."""

    max_tokens: int = 200_000
    max_cost_usd: float = 5.0
    max_tool_calls: int = 120
    #: Cumul des tokens **observes** par l'agent (historique, pas fenetre).
    tokens_estimated: int = 0
    #: Tokens **prouves** comme ayant quitte le contexte du modele
    #: (l'agent a accuse reception de la suppression).
    tokens_saved: int = 0
    #: Tokens **deplaces** vers un ref : ils sont stockes, mais leur presence
    #: dans la fenetre du modele n'est pas etablie. Ne pas les confondre avec
    #: `tokens_saved`.
    tokens_moved: int = 0
    #: Estimation de la taille **courante** de la fenetre de contexte.
    #: C'est cette valeur qui est comparee aux seuils (prune, pression) :
    #: un cumul de tokens traites ne dit rien de la taille du contexte.
    context_tokens_current: int = 0
    #: Phase courante du cycle agent + consommation par phase.
    phase: str = ""
    phase_tokens: dict[str, int] = field(default_factory=dict)
    cost_estimated: float = 0.0
    tool_calls: int = 0

    @property
    def tokens_remaining(self) -> int:
        used = self.context_tokens_current or self.tokens_estimated
        return max(0, self.max_tokens - used)

    @property
    def cost_remaining(self) -> float:
        return max(0.0, round(self.max_cost_usd - self.cost_estimated, 6))

    @property
    def ok(self) -> bool:
        used = self.context_tokens_current or self.tokens_estimated
        return (
            used < self.max_tokens
            and self.cost_estimated < self.max_cost_usd
            and self.tool_calls < self.max_tool_calls
        )

    def phase_used(self, phase: str) -> int:
        """Tokens consommes par une phase donnee."""
        return int(self.phase_tokens.get(phase, 0))

    def phase_ok(self, limits: dict[str, int] | None = None) -> bool:
        """Vrai si aucune phase n'a depasse son budget.

        Un budget de phase est un garde-fou d'arbitrage : la phase
        d'observation (qui encaisse les resultats d'outils) ne doit pas
        affamer la phase de generation.
        """
        if not limits:
            return True
        for phase, limit in limits.items():
            if self.phase_used(phase) > int(limit):
                return False
        return True

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["tokens_remaining"] = self.tokens_remaining
        data["cost_remaining"] = self.cost_remaining
        data["ok"] = self.ok
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BudgetState:
        return cls(
            max_tokens=int(data.get("max_tokens", 200_000)),
            max_cost_usd=float(data.get("max_cost_usd", 5.0)),
            max_tool_calls=int(data.get("max_tool_calls", 120)),
            tokens_estimated=int(data.get("tokens_estimated", 0)),
            tokens_saved=int(data.get("tokens_saved", 0)),
            tokens_moved=int(data.get("tokens_moved", 0)),
            context_tokens_current=int(data.get("context_tokens_current", 0)),
            phase=str(data.get("phase", "")),
            phase_tokens={
                str(k): int(v) for k, v in (data.get("phase_tokens") or {}).items()
            },
            cost_estimated=float(data.get("cost_estimated", 0.0)),
            tool_calls=int(data.get("tool_calls", 0)),
        )


@dataclass
class TaskState:
    """Etat complet et serialisable d'une tache."""

    task_id: str = field(default_factory=lambda: new_id("t"))
    objective: str = ""
    plan: Plan = field(default_factory=Plan)
    constraints: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    files: dict[str, FileEntry] = field(default_factory=dict)
    tool_results: dict[str, ToolResultEntry] = field(default_factory=dict)
    failures: dict[str, FailureEntry] = field(default_factory=dict)
    lessons: list[str] = field(default_factory=list)
    handoffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    budget: BudgetState = field(default_factory=BudgetState)
    flags: dict[str, bool] = field(default_factory=dict)
    #: Derniers hashes de zones connus (head / zoneB / tail / prefix).
    hashes: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "plan": self.plan.to_json(),
            "constraints": list(self.constraints),
            "decisions": list(self.decisions),
            "files": {k: v.to_json() for k, v in self.files.items()},
            "tool_results": {k: v.to_json() for k, v in self.tool_results.items()},
            "failures": {k: v.to_json() for k, v in self.failures.items()},
            "lessons": list(self.lessons),
            "handoffs": dict(self.handoffs),
            "budget": self.budget.to_json(),
            "flags": dict(self.flags),
            "hashes": dict(self.hashes),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TaskState:
        return cls(
            task_id=data.get("task_id", new_id("t")),
            objective=data.get("objective", ""),
            plan=Plan.from_json(data.get("plan", {})),
            constraints=list(data.get("constraints", [])),
            decisions=list(data.get("decisions", [])),
            files={k: FileEntry.from_json(v) for k, v in (data.get("files") or {}).items()},
            tool_results={
                k: ToolResultEntry.from_json(v) for k, v in (data.get("tool_results") or {}).items()
            },
            failures={
                k: FailureEntry.from_json(v) for k, v in (data.get("failures") or {}).items()
            },
            lessons=list(data.get("lessons", [])),
            handoffs=dict(data.get("handoffs") or {}),
            budget=BudgetState.from_json(data.get("budget", {})),
            flags=dict(data.get("flags") or {}),
            hashes=dict(data.get("hashes") or {}),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def loads(cls, raw: str) -> TaskState:
        return cls.from_json(json.loads(raw))

    # -- helpers ------------------------------------------------------------

    @property
    def total_steps(self) -> int:
        return len(self.plan.steps)

    @property
    def current_step(self) -> str:
        if 0 <= self.plan.current < len(self.plan.steps):
            return self.plan.steps[self.plan.current]
        return ""

    def set_flag(self, name: str, value: bool = True) -> None:
        self.flags[name] = value
        self.updated_at = time.time()

    def flag(self, name: str) -> bool:
        return bool(self.flags.get(name, False))

    def add_decision(self, body: str) -> None:
        """Append-only : une decision deja presentee n'est jamais reecrite."""
        body = body.strip()
        if body and body not in self.decisions:
            self.decisions.append(body)
            self.updated_at = time.time()

    def add_constraint(self, body: str) -> None:
        body = body.strip()
        if body and body not in self.constraints:
            self.constraints.append(body)
            self.updated_at = time.time()
