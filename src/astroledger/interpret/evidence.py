"""Statements with evidence levels, enforced when a statement is created (roadmap §14.3).

- **L1 observation** needs at least one measurement or metadata entity.
- **L2 inference** needs L1-type evidence *and* a rule or catalogue record linking it to a
  physical interpretation.
- **L3 hypothesis** must say what observation or analysis would test it.

A statement can be downgraded but never upgraded.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import IntEnum

__all__ = ["EvidenceError", "EvidenceRef", "Level", "Statement"]


class Level(IntEnum):
    """Evidence level; a higher value is weaker."""

    L1_OBSERVATION = 1
    L2_INFERENCE = 2
    L3_HYPOTHESIS = 3


class EvidenceError(ValueError):
    """A statement does not carry the evidence its level requires."""


#: Evidence kinds that count as observations (L1 support).
OBSERVATION_KINDS = frozenset({"measurement", "metadata"})
#: Evidence kinds that link observations to an interpretation (L2 support).
LINK_KINDS = frozenset({"rule", "catalogue_record"})


@dataclass(frozen=True)
class EvidenceRef:
    """A pointer to the evidence behind a statement.

    Attributes
    ----------
    kind : str
        ``measurement``, ``metadata``, ``rule`` or ``catalogue_record``.
    ref : str
        Identifier: measurement name, header keyword, rule ID, or catalogue + record ID exactly
        as retrieved (e.g. ``Gaia DR3 5420219663514042368``).
    value : str
        The value it contributes, as text with units.
    """

    kind: str
    ref: str
    value: str = ""

    def __post_init__(self) -> None:
        if self.kind not in OBSERVATION_KINDS | LINK_KINDS:
            raise EvidenceError(f"unknown evidence kind {self.kind!r}")


@dataclass(frozen=True)
class Statement:
    """One claim, its level and its evidence."""

    id: str
    text: str
    level: Level
    evidence: tuple[EvidenceRef, ...] = field(default_factory=tuple)
    uncertainty: str | None = None
    caveats: tuple[str, ...] = field(default_factory=tuple)
    test: str | None = None

    def __post_init__(self) -> None:
        kinds = {e.kind for e in self.evidence}
        if self.level is Level.L1_OBSERVATION and not kinds & OBSERVATION_KINDS:
            raise EvidenceError(f"{self.id}: L1 needs a measurement or metadata entity")
        if self.level is Level.L2_INFERENCE and not (
            kinds & OBSERVATION_KINDS and kinds & LINK_KINDS
        ):
            raise EvidenceError(
                f"{self.id}: L2 needs observational evidence and a rule or catalogue record"
            )
        if self.level is Level.L3_HYPOTHESIS and not self.test:
            raise EvidenceError(f"{self.id}: L3 must state what would test it")

    def downgrade(self, level: Level, test: str | None = None) -> Statement:
        """A copy at a weaker (or equal) level; upgrading is refused."""
        if level < self.level:
            raise EvidenceError(f"{self.id}: cannot upgrade {self.level.name} to {level.name}")
        return replace(self, level=level, test=test or self.test)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level.name,
            "text": self.text,
            "evidence": [vars(e) for e in self.evidence],
            "uncertainty": self.uncertainty,
            "caveats": list(self.caveats),
            "test": self.test,
        }
