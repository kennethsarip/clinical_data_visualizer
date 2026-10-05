"""Drug rule and entity name normalization for network nodes and top-N bars (CLAUDE.md §6).

Names are free text as registered, so one drug arrives as "Pembrolizumab", "pembrolizumab 200 mg"
and "Pembrolizumab (MK-3475)". A node must be one real entity (§7.4), so names are reduced to a
key by a fixed, listed set of rules; anything the rules miss stays a separate node rather than
being merged by guesswork. Brand <-> generic merging is deliberately absent (§13.4).

A mention keeps the raw registered name, because that is the excerpt a citation quotes and the
excerpt check verifies against the record.
"""

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.normalize import Intervention, NormalizedTrial
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

# A key is the name's words, ignoring case, accents, punctuation and symbols: in
# 85,208 cached live records one drug or condition was registered as "Nab-paclitaxel" and "nab
# paclitaxel", "Docetaxel®", "5Fluorouracil", "Glargine Insulin", or MeSH's inverted "Carcinoma,
# Non-Small-Cell Lung" (CLAUDE.md §6). A word is a run of letters or of digits, so "type2" is
# "type 2". Every letter and digit is kept, so "Type 1" / "Type 2" and "IL-2" / "IL-12" stay apart.
# Drug and condition keys also ignore word order ("Glargine Insulin", MeSH inversions). Sponsor
# keys keep it: there it only merged person sponsors ("Yan Li" / "Li Yan"), who may be two people.
_WORD = re.compile(r"[^\W\d_]+|\d+")
# Legal-form words that end a sponsor's name: "Celgene" and "Celgene Corporation", "Eisai Inc."
# and "Eisai Co., Ltd." are one sponsor. Only these trail-end forms go; "Pharmaceuticals" stays,
# since "Novartis Pharmaceuticals" names a business unit.
_LEGAL_FORMS = (
    r"inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|ag|sa|s\.a"
    r"|plc|bv|b\.v|nv|n\.v|kg|spa|s\.p\.a|srl|s\.r\.l|sas|ab|as|a/s|oy|kk|k\.k|pty|ulc|lp|llp"
)
_TRAILING_LEGAL_FORMS = re.compile(rf"(?:[\s,&]+(?:{_LEGAL_FORMS})\.?)+$", re.IGNORECASE)


# Synonyms from each intervention's registered other names (CLAUDE.md §14 Phase 8 step 5). On
# 4,000 live trials a transitive merge joined 1,051 names (lenalidomide lists "dexamethasone";
# regimens list their drugs), so an alias merges one hop only, when enough trials agree, and never
# when it is a common drug in its own right unless the two names list each other.
MIN_ALIAS_SUPPORT = 2  # trials listing the alias under the drug
MIN_ALIAS_SHARE = 0.6  # of all the trials listing the alias, under any drug
# A biosimilar is another maker's product: an intervention that mentions one adds no links.
_BIOSIMILAR = re.compile(r"\bbiosimilars?\b", re.IGNORECASE)
# A drug class is not one drug, though sponsors register classes as other names ("Anti-PD-1" and
# "Checkpoint inhibitor" under pembrolizumab, "Anti-CD38 Monoclonal Antibody" under daratumumab,
# live 2026-10-05). A name with a class word neither merges nor takes merges. Matched on key words.
_CLASS_WORDS = frozenset(
    {
        "anti", "inhibitor", "inhibitors", "antibody", "antibodies", "monoclonal", "factor",
        "factors", "agonist", "agonists", "antagonist", "antagonists", "blocker", "blockers",
        "chemotherapy", "therapy", "therapies", "agent", "agents", "stimulating",
    }
)  # fmt: skip


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
class DrugMerge:
    """Names merged into one drug by the synonym rule, for `meta.name_merges`."""

    key: str  # the drug's key
    label: str  # its most common own spelling
    merged_names: tuple[str, ...]  # cleaned spellings registered as own names, now this drug
    evidence: tuple[tuple[str, str], ...]  # (nct_id, raw other name) listings, nct_id descending


@dataclass(frozen=True)
class DrugSelection:
    mentions: dict[str, tuple[Mention, ...]]  # nct_id -> drugs, one per key, registration order
    excluded: dict[str, int]  # the three rules above -> trial counts
    merges: tuple[DrugMerge, ...] = ()  # synonym merges applied to these trials, by key


@dataclass(frozen=True)
class _Aliases:
    canonical: dict[str, str]  # alias key -> drug key
    labels: dict[str, str]  # drug key -> its most common own spelling
    listings: dict[str, dict[str, dict[str, str]]]  # alias -> drug -> nct_id -> raw other name


def entity_key(entity_type: EntityType, raw: str) -> str:
    return _key(entity_type, _clean(entity_type, raw))


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


def drug_aliases(trials: Sequence[NormalizedTrial]) -> dict[str, str]:
    """Alias key -> drug key, from the other names registered in `trials`."""
    return _aliases(trials).canonical


def select_drugs(
    trials: Sequence[NormalizedTrial], universe: Sequence[NormalizedTrial] | None = None
) -> DrugSelection:
    """Apply the §6 drug rule to every trial and count, per trial, what it dropped. Synonyms are
    merged with evidence from `universe` (default: `trials`); a comparison passes every cohort."""
    aliases = _aliases(trials if universe is None else universe)
    applied: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
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
                if (drug := aliases.canonical.get(mention.key)) is not None:
                    applied[drug][mention.key].add(mention.label)
                    mention = Mention(drug, aliases.labels[drug], mention.raw)
                drugs.setdefault(mention.key, mention)
        mentions[trial.nct_id] = tuple(drugs.values())
        excluded[PLACEBO_RULE] += dropped_placebo
        excluded[NON_DRUG_RULE] += dropped_non_drug
        # No named intervention at all is already a normalize gap; don't count it twice.
        excluded[NO_DRUG_RULE] += bool(named) and not drugs
    return DrugSelection(mentions, excluded, _merges(aliases, applied))


def combine_merges(*groups: Iterable[DrugMerge]) -> tuple[DrugMerge, ...]:
    """One disclosure per drug from several selections (cohorts, network sides)."""
    by_key: dict[str, list[DrugMerge]] = defaultdict(list)
    for merge in (m for group in groups for m in group):
        by_key[merge.key].append(merge)
    return tuple(
        DrugMerge(
            key,
            merges[0].label,
            tuple(sorted({name for m in merges for name in m.merged_names})),
            tuple(sorted({e for m in merges for e in m.evidence}, reverse=True)),
        )
        for key, merges in sorted(by_key.items())
    )


def _drug_interventions(trial: NormalizedTrial) -> Iterator[tuple[Intervention, str]]:
    """The trial's interventions that count as drugs (§6), with their names."""
    for intervention in trial.interventions:
        name = intervention.name
        if name is not None and not is_placebo(name) and intervention.type in DRUG_TYPES:
            yield intervention, name


def _aliases(trials: Sequence[NormalizedTrial]) -> _Aliases:
    own: Counter[str] = Counter()  # drug key -> trials naming it as an intervention's own name
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    listings: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    # Once per trial: a comparison's trial set repeats a trial that matches two cohorts.
    for trial in {t.nct_id: t for t in trials}.values():
        named: set[str] = set()
        for intervention, name in _drug_interventions(trial):
            mention = _mention(EntityType.DRUG, name)
            named.add(mention.key)
            spellings[mention.key][mention.label] += 1
            if _is_class(mention.key) or any(
                _BIOSIMILAR.search(n) for n in (name, *intervention.other_names)
            ):
                continue
            for other in intervention.other_names:
                alias = drug_key(other)
                if alias != mention.key and not _is_class(alias):
                    listings[alias][mention.key].setdefault(trial.nct_id, other)
        own.update(named)
    canonical = _canonical(own, listings)
    labels = {key: most_common_spelling(counts.elements()) for key, counts in spellings.items()}
    return _Aliases(canonical, labels, listings)


def _is_class(key: str) -> bool:
    return not _CLASS_WORDS.isdisjoint(key.split())


def _canonical(own: Counter[str], listings: dict[str, dict[str, dict[str, str]]]) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for alias, by_drug in listings.items():
        support = {drug: len(trials) for drug, trials in by_drug.items()}
        drug = min(support, key=lambda d: (-support[d], -own[d], d))
        listed = support[drug]
        if listed < MIN_ALIAS_SUPPORT or listed < MIN_ALIAS_SHARE * sum(support.values()):
            continue
        mutual = alias in listings.get(drug, {})
        if own[alias] >= listed and not mutual:
            continue  # a common drug in its own right, misused as an other name
        candidates[alias] = drug
    # Two names listing each other: the one used more as an own name is the drug.
    for alias, drug in list(candidates.items()):
        if candidates.get(alias) == drug and candidates.get(drug) == alias:  # not yet resolved
            keep, drop = sorted((alias, drug), key=lambda k: (-own[k], k))
            candidates.pop(keep)
            candidates[drop] = keep
    # One hop: an alias whose drug is itself an alias stays unmerged.
    return {alias: drug for alias, drug in candidates.items() if drug not in candidates}


def _merges(aliases: _Aliases, applied: dict[str, dict[str, set[str]]]) -> tuple[DrugMerge, ...]:
    merges = []
    for drug in sorted(applied):
        evidence = {
            (nct_id, raw)
            for alias in applied[drug]
            for nct_id, raw in aliases.listings[alias][drug].items()
        }
        names = sorted({label for labels in applied[drug].values() for label in labels})
        merges.append(
            DrugMerge(
                drug, aliases.labels[drug], tuple(names), tuple(sorted(evidence, reverse=True))
            )
        )
    return tuple(merges)


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
    return Mention(key=_key(entity_type, label), label=label, raw=raw)


def _key(entity_type: EntityType, label: str) -> str:
    """The words of a cleaned name (sorted for drugs and conditions); the folded name itself if it
    has no words."""
    text = unicodedata.normalize("NFKD", label)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    if entity_type is EntityType.SPONSOR:
        words = _WORD.findall(_TRAILING_LEGAL_FORMS.sub("", text) or text)
    else:
        words = sorted(_WORD.findall(text))
    return " ".join(words) or label.casefold()


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
