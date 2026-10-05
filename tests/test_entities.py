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
    EntityType,
    condition_mentions,
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
