"""Drug rule and entity name normalization (CLAUDE.md §6).

Fixture names are shaped like the §6 live evidence (pembrolizumab registered as DRUG and as
BIOLOGICAL, placebo, "laboratory biomarker analysis", dose and code-name variants). Expected keys
and labels are derived by hand from the §6 rules, not from output.
"""

from typing import Any

import pytest

from app.entities import (
    NO_DRUG_RULE,
    NON_DRUG_RULE,
    PLACEBO_RULE,
    DrugMerge,
    EntityType,
    condition_mentions,
    drug_aliases,
    drug_key,
    entity_key,
    is_placebo,
    label_for,
    select_drugs,
    sponsor_mention,
)
from app.normalize import NormalizedTrial
from tests.factories import Interventions, make_trial


def _trial(nct_id: str, interventions: Interventions, **extra: Any) -> NormalizedTrial:
    return make_trial(nct_id, interventions, **extra)


# --- name normalization ---


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("Pembrolizumab", "pembrolizumab"),
        ("PEMBROLIZUMAB", "pembrolizumab"),
        ("  Pembrolizumab \n", "pembrolizumab"),
        ("Pembrolizumab (MK-3475)", "pembrolizumab"),
        ("Pembrolizumab [Keytruda]", "pembrolizumab"),
        ("Pembrolizumab 200 mg", "pembrolizumab"),
        ("pembrolizumab 200mg", "pembrolizumab"),
        ("Pembrolizumab 2 mg/kg", "pembrolizumab"),
        ("Nab-paclitaxel 125 mg/m2", "nab paclitaxel"),  # punctuation is not part of a key
        ("Imatinib Mesylate", "imatinib"),
        ("Erlotinib Hydrochloride 150 mg", "erlotinib"),
        ("Heparin Sodium", "heparin"),
        ("Pembrolizumab 200 mg (MK-3475)", "pembrolizumab"),
        ("Carboplatin   AUC 5", "5 auc carboplatin"),  # not a dose unit we strip: kept
        ("Sodium Chloride", "chloride sodium"),  # "chloride" is not a stripped salt
        ("Sodium", "sodium"),  # a salt word is never stripped down to nothing
        ("(MK-3475)", "3475 mk"),  # nor is a bracket that is the whole name
    ],
)
def test_drug_key(raw: str, key: str) -> None:
    assert drug_key(raw) == key


# Spelling variants of one entity seen in 85,208 cached live records (2026-10-05): each group must
# share one key, so it is one node and one bar (CLAUDE.md §6 entity names).
SAME_ENTITY = [
    (EntityType.DRUG, ["Nab-paclitaxel", "Nab paclitaxel", "nab- paclitaxel", "(nab)-paclitaxel"]),
    (EntityType.DRUG, ["Pembrolizumab", "Pembrolizumab,", "pembrolizumab -", '"Pembrolizumab"']),
    (EntityType.DRUG, ["Docetaxel", "Docetaxel®", "Docetaxel."]),
    (EntityType.DRUG, ["5-Fluorouracil", "5 fluorouracil", "5Fluorouracil", "5- fluorouracil"]),
    (EntityType.DRUG, ["Insulin Glargine", "Glargine Insulin", "insulin/ glargine"]),
    (EntityType.DRUG, ["Nivolumab + Ipilimumab", "Ipilimumab/Nivolumab"]),
    (
        EntityType.CONDITION,
        [
            "Non-small Cell Lung Cancer",
            "NON SMALL CELL LUNG CANCER",
            "non-small-cell lung cancer",
            "Non-Small- Cell Lung Cancer",
        ],
    ),
    (
        EntityType.CONDITION,
        [
            "Carcinoma, Non-Small-Cell Lung",
            "Non-Small-Cell Lung Carcinoma",
            "carcinoma non small cell lung",
        ],
    ),
    (
        EntityType.CONDITION,
        [
            "Diabetes Mellitus, Type 2",
            "Type 2 Diabetes Mellitus",
            "type2 diabetes mellitus",
            "Diabetes Mellitus (Type 2)",
            "Diabetes Mellitus，Type 2",
        ],
    ),
    (EntityType.CONDITION, ["Breast Neoplasms", "Neoplasms, Breast"]),
    (
        EntityType.CONDITION,
        ["Multiple Sclerosis", "Multi\u0307ple Sclerosi\u0307s", "multiple sclerosis)"],
    ),
    (EntityType.CONDITION, ["Sjögren's Syndrome", "Sjogren's syndrome"]),
    (EntityType.SPONSOR, ["Celgene", "Celgene Corporation"]),
    (EntityType.SPONSOR, ["Daiichi Sankyo", "Daiichi Sankyo Co., Ltd.", "Daiichi Sankyo, Inc."]),
    (EntityType.SPONSOR, ["Eisai Inc.", "Eisai Co., Ltd.", "Eisai Limited", "Eisai GmbH"]),
    (
        EntityType.SPONSOR,
        [
            "Janssen-Cilag Ltd.",
            "Janssen-Cilag B.V.",
            "Janssen-Cilag, S.A.",
            "Janssen-Cilag Pty Ltd",
        ],
    ),
    (EntityType.SPONSOR, ["CellMax Life", "Cellmax  life"]),
]


@pytest.mark.parametrize(("entity_type", "names"), SAME_ENTITY)
def test_spelling_variants_share_one_key(entity_type: EntityType, names: list[str]) -> None:
    keys = {entity_key(entity_type, name) for name in names}
    assert len(keys) == 1, keys


# Different entities whose names differ only in what the rules must keep: numbers, a word, a
# chemical prefix. Merging any of these would put two real entities on one node.
DIFFERENT_ENTITIES = [
    (EntityType.CONDITION, "Type 1 Diabetes", "Type 2 Diabetes"),
    (EntityType.CONDITION, "Hepatitis B", "Hepatitis C"),
    (EntityType.CONDITION, "Small Cell Lung Cancer", "Non-small Cell Lung Cancer"),
    (EntityType.DRUG, "IL-2", "IL-12"),
    (EntityType.DRUG, "4-Hydroxytamoxifen", "Tamoxifen"),
    (EntityType.DRUG, "Insulin Glargine", "Insulin Degludec"),
    (EntityType.SPONSOR, "Merck Sharp & Dohme LLC", "Merck KGaA"),
    (EntityType.SPONSOR, "Novartis", "Novartis Pharmaceuticals"),  # a business unit, not a suffix
    # Person sponsors: swapped name order can be two people (both spellings seen in the cache).
    (EntityType.SPONSOR, "Yan Li", "Li Yan"),
]


@pytest.mark.parametrize(("entity_type", "a", "b"), DIFFERENT_ENTITIES)
def test_different_entities_keep_different_keys(entity_type: EntityType, a: str, b: str) -> None:
    assert entity_key(entity_type, a) != entity_key(entity_type, b)


def test_a_name_of_only_suffixes_or_symbols_keeps_a_key() -> None:
    assert entity_key(EntityType.SPONSOR, "Inc.") != ""
    assert entity_key(EntityType.DRUG, "®") != ""


def test_synonyms_are_not_string_rules() -> None:
    # A code name or a dropped chemical locant is a synonym, not a spelling: deferred (§13.4).
    assert drug_key("5-Fluorouracil") != drug_key("Fluorouracil")
    assert drug_key("RAD001") != drug_key("Everolimus")


def test_brand_and_generic_stay_separate() -> None:
    # Synonym merging is deferred (CLAUDE.md §13.4); the rules must not pretend to do it.
    assert drug_key("Keytruda") != drug_key("Pembrolizumab")


@pytest.mark.parametrize(
    ("entity_type", "raw", "key"),
    [
        (EntityType.SPONSOR, "Merck Sharp & Dohme LLC", "merck sharp dohme"),
        (EntityType.SPONSOR, " MERCK  Sharp & Dohme LLC", "merck sharp dohme"),
        # Conditions get no dose or bracket stripping: the bracket's words stay in the key.
        (EntityType.CONDITION, "Melanoma (Skin)", "melanoma skin"),
        (EntityType.DRUG, "Pembrolizumab (MK-3475)", "pembrolizumab"),
    ],
)
def test_entity_key(entity_type: EntityType, raw: str, key: str) -> None:
    assert entity_key(entity_type, raw) == key


def test_label_is_the_most_common_cleaned_spelling() -> None:
    raws = ["Pembrolizumab (MK-3475)", "pembrolizumab", "Pembrolizumab 200 mg", "PEMBROLIZUMAB"]
    # Cleaned spellings: Pembrolizumab x2, pembrolizumab x1, PEMBROLIZUMAB x1.
    assert label_for(EntityType.DRUG, raws) == "Pembrolizumab"


def test_label_ties_break_alphabetically() -> None:
    assert label_for(EntityType.SPONSOR, ["merck", "Merck"]) == "Merck"


# --- placebo ---


@pytest.mark.parametrize(
    "name",
    [
        "Placebo",
        "placebo",
        "Matching Placebo",
        "Placebo-matched tablets",
        "Sham injection",
        "Vehicle cream",
        "Normal Saline",
        "Placebos",
    ],
)
def test_placebo_names(name: str) -> None:
    assert is_placebo(name)


@pytest.mark.parametrize("name", ["Pembrolizumab", "Salinexumab", "Vehiclemab", "Shampoo"])
def test_placebo_is_matched_as_a_whole_word(name: str) -> None:
    assert not is_placebo(name)


# --- the drug rule ---


def test_drug_and_biological_registrations_merge_into_one_drug() -> None:
    selection = select_drugs(
        [
            _trial("NCT00000001", [("DRUG", "Pembrolizumab")]),
            _trial("NCT00000002", [("BIOLOGICAL", "Pembrolizumab (MK-3475)")]),
            _trial("NCT00000003", [("COMBINATION_PRODUCT", "pembrolizumab 200 mg")]),
        ]
    )
    for nct_id in ("NCT00000001", "NCT00000002", "NCT00000003"):
        assert [m.key for m in selection.mentions[nct_id]] == ["pembrolizumab"]
    assert selection.excluded == {PLACEBO_RULE: 0, NON_DRUG_RULE: 0, NO_DRUG_RULE: 0}


def test_mentions_keep_the_raw_registered_name_as_excerpt() -> None:
    selection = select_drugs([_trial("NCT00000002", [("BIOLOGICAL", "Pembrolizumab (MK-3475)")])])
    (mention,) = selection.mentions["NCT00000002"]
    assert mention.raw == "Pembrolizumab (MK-3475)"
    assert mention.label == "Pembrolizumab"


def test_a_drug_registered_twice_in_one_trial_is_one_mention() -> None:
    trial = _trial(
        "NCT00000001", [("DRUG", "Pembrolizumab"), ("BIOLOGICAL", "pembrolizumab 200 mg")]
    )
    mentions = select_drugs([trial]).mentions["NCT00000001"]
    assert [(m.key, m.raw) for m in mentions] == [("pembrolizumab", "Pembrolizumab")]


def test_placebo_non_drug_and_drugless_trials_are_counted_per_trial() -> None:
    trials = [
        # placebo dropped, real drug kept
        _trial("NCT00000001", [("DRUG", "Pembrolizumab"), ("DRUG", "Placebo")]),
        # two placebos in one trial count once
        _trial("NCT00000002", [("DRUG", "Ipilimumab"), ("DRUG", "Placebo"), ("OTHER", "Saline")]),
        # non-drug dropped, real drug kept
        _trial("NCT00000003", [("DRUG", "Nivolumab"), ("OTHER", "Laboratory Biomarker Analysis")]),
        # nothing left: non-drug and drugless
        _trial("NCT00000004", [("PROCEDURE", "Surgery")]),
        # nothing left: placebo and drugless
        _trial("NCT00000005", [("DRUG", "Placebo")]),
        # no interventions / only unnamed: already a normalize gap, not counted again here
        _trial("NCT00000006", []),
        _trial("NCT00000007", [("DRUG", None)]),
    ]
    selection = select_drugs(trials)
    assert selection.excluded == {PLACEBO_RULE: 3, NON_DRUG_RULE: 2, NO_DRUG_RULE: 2}
    assert [m.key for m in selection.mentions["NCT00000002"]] == ["ipilimumab"]
    assert {nct for nct, ms in selection.mentions.items() if not ms} == {
        "NCT00000004",
        "NCT00000005",
        "NCT00000006",
        "NCT00000007",
    }


def test_drug_mentions_keep_registration_order() -> None:
    trial = _trial("NCT00000001", [("DRUG", "Nivolumab"), ("DRUG", "Ipilimumab")])
    assert [m.key for m in select_drugs([trial]).mentions["NCT00000001"]] == [
        "nivolumab",
        "ipilimumab",
    ]


# --- sponsors and conditions ---


def test_sponsor_mention() -> None:
    mention = sponsor_mention(_trial("NCT00000001", [], sponsor_name="MERCK Sharp & Dohme LLC"))
    assert (mention.key, mention.raw) == ("merck sharp dohme", "MERCK Sharp & Dohme LLC")


def test_condition_mentions_dedupe_by_key() -> None:
    trial = _trial("NCT00000001", [], conditions=["Melanoma", "melanoma", "Lung Cancer"])
    assert [(m.key, m.raw) for m in condition_mentions(trial)] == [
        ("melanoma", "Melanoma"),
        ("cancer lung", "Lung Cancer"),
    ]


# --- synonyms from registered other names (Phase 8 step 5) ---
# Expected maps are derived by hand from the CLAUDE.md §14 Phase 8 step 5 rule: one hop, support
# >= 2 trials, share >= 60%, no common drug as an alias unless the two list each other, the name
# used more as an own name wins a cycle, and an intervention mentioning "biosimilar" adds no links.


def _drugs(nct: int, *items: tuple[str, list[str]]) -> NormalizedTrial:
    return make_trial(f"NCT{nct:08d}", [("DRUG", name, others) for name, others in items])


def _keys(trials: list[NormalizedTrial]) -> dict[str, list[str]]:
    selection = select_drugs(trials)
    return {nct: [m.key for m in ms] for nct, ms in selection.mentions.items()}


EVEROLIMUS = [
    _drugs(1, ("Everolimus", ["RAD001"])),
    _drugs(2, ("Everolimus", ["RAD001", "Afinitor"])),
    _drugs(3, ("RAD001", []), ("Exemestane", [])),
]


def test_an_alias_listed_under_one_drug_in_two_trials_merges_into_it() -> None:
    assert drug_aliases(EVEROLIMUS) == {drug_key("RAD001"): "everolimus"}
    assert _keys(EVEROLIMUS)["NCT00000003"] == ["everolimus", "exemestane"]


def test_a_merged_mention_keeps_its_raw_name_and_takes_the_drugs_label() -> None:
    mention = select_drugs(EVEROLIMUS).mentions["NCT00000003"][0]
    assert (mention.key, mention.label, mention.raw) == ("everolimus", "Everolimus", "RAD001")


def test_merges_are_disclosed_with_their_evidence() -> None:
    assert select_drugs(EVEROLIMUS).merges == (
        DrugMerge(
            key="everolimus",
            label="Everolimus",
            merged_names=("RAD001",),
            evidence=(("NCT00000002", "RAD001"), ("NCT00000001", "RAD001")),
        ),
    )


def test_no_merge_without_two_supporting_trials() -> None:
    # Afinitor is listed once; RAD001 is listed once when trial 2 is absent.
    assert drug_aliases(EVEROLIMUS) == {drug_key("RAD001"): "everolimus"}
    assert drug_aliases([EVEROLIMUS[0], EVEROLIMUS[2]]) == {}


def test_no_merge_when_the_alias_is_split_between_drugs() -> None:
    # "IL-2" listed twice under aldesleukin and twice under a CAR-T product: 50% each.
    trials = [
        _drugs(1, ("Aldesleukin", ["IL-2"])),
        _drugs(2, ("Aldesleukin", ["IL-2"])),
        _drugs(3, ("CAR-NK cells", ["IL-2"])),
        _drugs(4, ("CAR-NK cells", ["IL-2"])),
    ]
    assert drug_aliases(trials) == {}


def test_a_common_drug_misused_as_an_other_name_is_not_merged() -> None:
    # Live: lenalidomide's other names include "dexamethasone", itself the own name of 3 trials.
    trials = [
        _drugs(1, ("Lenalidomide", ["Dexamethasone"])),
        _drugs(2, ("Lenalidomide", ["Dexamethasone"])),
        _drugs(3, ("Dexamethasone", [])),
        _drugs(4, ("Dexamethasone", [])),
        _drugs(5, ("Dexamethasone", [])),
    ]
    assert drug_aliases(trials) == {}


def test_two_names_that_list_each_other_merge_into_the_more_used_one() -> None:
    # Both are own names in several trials, but each lists the other: one drug.
    trials = [
        _drugs(1, ("Fluorouracil", ["5-FU"])),
        _drugs(2, ("Fluorouracil", ["5-FU"])),
        _drugs(3, ("Fluorouracil", [])),
        _drugs(4, ("5-FU", ["Fluorouracil"])),
        _drugs(5, ("5-FU", ["Fluorouracil"])),
    ]
    assert drug_aliases(trials) == {drug_key("5-FU"): "fluorouracil"}


def test_aliases_never_chain() -> None:
    # SCH 900475 -> MK-3475 -> pembrolizumab: only the direct hop merges. MK-3475 is listed under
    # pembrolizumab in more trials than it is an own name, so the common-drug guard lets it merge.
    trials = [
        _drugs(1, ("Pembrolizumab", ["MK-3475"])),
        _drugs(2, ("Pembrolizumab", ["MK-3475"])),
        _drugs(5, ("Pembrolizumab", ["MK-3475"])),
        _drugs(3, ("MK-3475", ["SCH 900475"])),
        _drugs(4, ("MK-3475", ["SCH 900475"])),
    ]
    assert drug_aliases(trials) == {drug_key("MK-3475"): "pembrolizumab"}


def test_biosimilars_stay_separate() -> None:
    trials = [
        _drugs(1, ("BCD-201 (pembrolizumab biosimilar)", ["Pembrolizumab"])),
        _drugs(2, ("BCD-201 (pembrolizumab biosimilar)", ["Pembrolizumab"])),
        _drugs(3, ("Pembrolizumab", ["BCD-201 biosimilar"])),
        _drugs(4, ("Pembrolizumab", ["BCD-201 biosimilar"])),
    ]
    assert drug_aliases(trials) == {}


def test_drug_class_names_never_merge_into_one_drug() -> None:
    # Live (pembrolizumab, myeloma): sponsors register "Anti-PD-1" and "Checkpoint inhibitor" as
    # other names of pembrolizumab, and "Anti-CD38 Monoclonal Antibody" of daratumumab. A class is
    # not one drug, so neither direction links.
    trials = [
        _drugs(1, ("Pembrolizumab", ["Anti-PD-1", "Checkpoint inhibitor"])),
        _drugs(2, ("Pembrolizumab", ["Anti-PD-1", "Checkpoint inhibitor"])),
        _drugs(3, ("Pembrolizumab", ["Anti-PD-1"])),
        _drugs(4, ("Anti-PD-1 antibody", ["Pembrolizumab"])),
        _drugs(5, ("Daratumumab", ["Anti-CD38 Monoclonal Antibody"])),
        _drugs(6, ("Daratumumab", ["Anti-CD38 Monoclonal Antibody"])),
        _drugs(7, ("Filgrastim", ["Granulocyte Colony-Stimulating Factor"])),
        _drugs(8, ("Filgrastim", ["Granulocyte Colony-Stimulating Factor"])),
    ]
    assert drug_aliases(trials) == {}


def test_placebo_and_non_drug_interventions_add_no_links() -> None:
    trials = [
        make_trial("NCT00000001", [("DRUG", "Placebo", ["Everolimus"])]),
        make_trial("NCT00000002", [("DRUG", "Placebo", ["Everolimus"])]),
        make_trial("NCT00000003", [("PROCEDURE", "Biopsy", ["RAD001"])]),
        make_trial("NCT00000004", [("PROCEDURE", "Biopsy", ["RAD001"])]),
    ]
    assert drug_aliases(trials) == {}


def test_a_drug_registered_under_two_of_its_names_is_one_mention() -> None:
    # A third listing keeps RAD001's support above its own-name count (now 2 trials).
    trials = [
        *EVEROLIMUS,
        _drugs(5, ("Everolimus", ["RAD001"])),
        _drugs(4, ("Everolimus", []), ("RAD001", [])),
    ]
    assert _keys(trials)["NCT00000004"] == ["everolimus"]


def test_evidence_can_come_from_a_wider_set_of_trials() -> None:
    # A comparison draws aliases from every cohort, so one drug has one key in each.
    selection = select_drugs([EVEROLIMUS[2]], universe=EVEROLIMUS)
    assert [m.key for m in selection.mentions["NCT00000003"]] == ["everolimus", "exemestane"]
