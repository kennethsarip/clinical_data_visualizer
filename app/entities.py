"""Drug rule and entity name normalization for network nodes and top-N bars (CLAUDE.md §6).

Names are free text as registered, so one drug arrives as "Pembrolizumab", "pembrolizumab 200 mg"
and "Pembrolizumab (MK-3475)". A node must be one real entity (§7.4), so names are reduced to a
key by a fixed, listed set of rules; anything the rules miss stays a separate node rather than
being merged by guesswork. Brand <-> generic merging is deliberately absent (§13.4).

A mention keeps the raw registered name, because that is the excerpt a citation quotes and the
excerpt check verifies against the record.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.normalize import NormalizedTrial
from app.vocab import InterventionType

# `meta.excluded` rule names. Counts are trials, so they read on the same scale as the chart.
PLACEBO_RULE = "placebo"  # trials with at least one placebo-like intervention dropped
NON_DRUG_RULE = "non-drug intervention"  # trials with at least one non-drug intervention dropped
NO_DRUG_RULE = "no drug intervention"  # trials left with no drug, so absent from drug charts

# Type alone splits one drug: pembrolizumab is registered 617x as DRUG and 243x as BIOLOGICAL (§6).
DRUG_TYPES = frozenset(
    {InterventionType.DRUG, InterventionType.BIOLOGICAL, InterventionType.COMBINATION_PRODUCT}
)

_PLACEBO = re.compile(r"\b(?:placebos?|sham|vehicle|saline)\b", re.IGNORECASE)

# Trailing pieces that vary between registrations of the same drug. Each is stripped only from
# the end, and only while something is left, so a name is never reduced to nothing.
_TRAILING_BRACKET = re.compile(r"\s*[(\[][^()\[\]]*[)\]]$")
_TRAILING_DOSE = re.compile(
    r"\s+\d+(?:[.,]\d+)?(?:\s*-\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:mg|mcg|µg|ug|g|iu|units?|ml|%)(?:\s*/\s*[a-z0-9²]+)*$",
    re.IGNORECASE,
)
# Salt and counter-ion words that never name a drug on their own.
_SALTS = (
    "hydrochloride|dihydrochloride|hcl|mesylate|dimesylate|maleate|sulfate|besylate|tosylate"
    "|fumarate|succinate|tartrate|citrate|acetate|phosphate|sodium|potassium"
)
_TRAILING_SALT = re.compile(rf"\s+(?:{_SALTS})$", re.IGNORECASE)
_DRUG_SUFFIXES = (_TRAILING_BRACKET, _TRAILING_DOSE, _TRAILING_SALT)

_WHITESPACE = re.compile(r"\s+")


class EntityType(StrEnum):
    """Network node types; values match SCHEMAS.md §3.6 `entity_type`."""

    DRUG = "drug"
    SPONSOR = "sponsor"
    CONDITION = "condition"


@dataclass(frozen=True)
class Mention:
    """One entity in one trial."""

    key: str  # normalized: what nodes and bars group on
    label: str  # the cleaned spelling, case kept: a vote for the node's display label
    raw: str  # verbatim registered name: the citation excerpt


@dataclass(frozen=True)
class DrugSelection:
    mentions: dict[str, tuple[Mention, ...]]  # nct_id -> drugs, one per key, registration order
    excluded: dict[str, int]  # the three rules above -> trial counts


def entity_key(entity_type: EntityType, raw: str) -> str:
    return _clean(entity_type, raw).casefold()


def drug_key(raw: str) -> str:
    return entity_key(EntityType.DRUG, raw)


def label_for(entity_type: EntityType, raws: Iterable[str]) -> str:
    """The most common cleaned spelling of an entity's raw names."""
    return most_common_spelling(_clean(entity_type, raw) for raw in raws)


def most_common_spelling(spellings: Iterable[str]) -> str:
    """The most frequent spelling; ties go to the alphabetically first, so output is stable."""
    counts = Counter(spellings)
    return min(counts, key=lambda spelling: (-counts[spelling], spelling))


def is_placebo(name: str) -> bool:
    return _PLACEBO.search(name) is not None


def select_drugs(trials: Sequence[NormalizedTrial]) -> DrugSelection:
    """Apply the §6 drug rule to every trial and count, per trial, what it dropped."""
    mentions: dict[str, tuple[Mention, ...]] = {}
    excluded = {PLACEBO_RULE: 0, NON_DRUG_RULE: 0, NO_DRUG_RULE: 0}
    for trial in trials:
        drugs: dict[str, Mention] = {}
        dropped_placebo = dropped_non_drug = False
        named = [i for i in trial.interventions if i.name is not None]
        for intervention in named:
            name = intervention.name or ""
            if is_placebo(name):
                dropped_placebo = True
            elif intervention.type not in DRUG_TYPES:
                dropped_non_drug = True
            else:
                mention = _mention(EntityType.DRUG, name)
                drugs.setdefault(mention.key, mention)
        mentions[trial.nct_id] = tuple(drugs.values())
        excluded[PLACEBO_RULE] += dropped_placebo
        excluded[NON_DRUG_RULE] += dropped_non_drug
        # No named intervention at all is already a normalize gap; don't count it twice.
        excluded[NO_DRUG_RULE] += bool(named) and not drugs
    return DrugSelection(mentions, excluded)


def sponsor_mention(trial: NormalizedTrial) -> Mention:
    return _mention(EntityType.SPONSOR, trial.sponsor_name)


def condition_mentions(trial: NormalizedTrial) -> tuple[Mention, ...]:
    found: dict[str, Mention] = {}
    for condition in trial.conditions:
        mention = _mention(EntityType.CONDITION, condition)
        found.setdefault(mention.key, mention)
    return tuple(found.values())


def _mention(entity_type: EntityType, raw: str) -> Mention:
    label = _clean(entity_type, raw)
    return Mention(key=label.casefold(), label=label, raw=raw)


def _clean(entity_type: EntityType, raw: str) -> str:
    name = _WHITESPACE.sub(" ", raw).strip()
    if entity_type is not EntityType.DRUG:
        return name
    # Repeat, because suffixes stack: "Erlotinib Hydrochloride 150 mg (OSI-774)".
    changed = True
    while changed:
        changed = False
        for suffix in _DRUG_SUFFIXES:
            stripped = suffix.sub("", name).strip()
            if stripped and stripped != name:
                name, changed = stripped, True
    return name
