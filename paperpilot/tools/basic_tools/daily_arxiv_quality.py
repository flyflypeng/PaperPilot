"""
Daily arXiv quality configuration.

This module keeps the built-in institution tiers and quality strategy defaults
separate from crawler logic so settings migration and UI metadata stay stable.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


DAILY_ARXIV_QUALITY_STRATEGIES: Dict[str, Dict[str, Any]] = {
    "strict": {
        "label": "Strict",
        "summary": "Small high-confidence feed for intensive reading.",
        "description": (
            "Uses Tier S first and Tier A only with strong relevance. Tier B/C and "
            "unknown institutions are normally filtered out."
        ),
        "maxPapersPerCategory": 20,
        "minInstitutionTier": "A",
        "allowUnknownInstitutions": False,
        "externalSignals": ["institution_tier", "official_code", "citation_hint"],
    },
    "balanced": {
        "label": "Balanced",
        "summary": "Default mode balancing quality, diversity, and recall.",
        "description": (
            "Prioritizes Tier S/A, accepts Tier B with keyword matches, and allows "
            "unknown institutions behind configured tiers. Recommended for daily tracking."
        ),
        "maxPapersPerCategory": 40,
        "minInstitutionTier": "B",
        "allowUnknownInstitutions": True,
        "externalSignals": ["institution_tier", "official_code", "citation_hint"],
    },
    "discovery": {
        "label": "Discovery",
        "summary": "Broader feed for finding emerging work.",
        "description": (
            "Accepts Tier S/A/B/C plus unknown institutions when keywords match. "
            "Use this when recall matters more than short-term precision."
        ),
        "maxPapersPerCategory": 80,
        "minInstitutionTier": "C",
        "allowUnknownInstitutions": True,
        "externalSignals": ["institution_tier", "official_code", "citation_hint"],
    },
}


DEFAULT_DAILY_ARXIV_INSTITUTION_TIERS: Dict[str, List[str]] = {
    "S": [
        "MIT",
        "Stanford",
        "UC Berkeley",
        "CMU",
        "Princeton",
        "Harvard",
        "Caltech",
        "Oxford",
        "Cambridge",
        "ETH Zurich",
        "EPFL",
        "Tsinghua",
        "Peking",
        "Google",
        "Google DeepMind",
        "Meta AI",
        "OpenAI",
        "Microsoft Research",
        "NVIDIA",
    ],
    "A": [
        "Cornell",
        "Columbia",
        "UIUC",
        "University of Washington",
        "UMich",
        "UCLA",
        "UCSD",
        "UT Austin",
        "University of Toronto",
        "MILA",
        "NYU",
        "Georgia Tech",
        "University of Maryland",
        "Yale",
        "UPenn",
        "Imperial College London",
        "UCL",
        "University of Edinburgh",
        "SJTU",
        "Fudan",
        "Zhejiang University",
        "USTC",
        "NUS",
        "NTU",
        "AWS AI",
        "Amazon",
        "Apple",
        "Adobe Research",
        "IBM Research",
        "Huawei",
        "Tencent AI Lab",
        "Alibaba",
        "ByteDance",
    ],
    "B": [
        "Duke",
        "Brown",
        "JHU",
        "Northwestern",
        "UChicago",
        "Rice",
        "Dartmouth",
        "Vanderbilt",
        "Notre Dame",
        "WashU",
        "University of Wisconsin-Madison",
        "University of Waterloo",
        "KAIST",
        "POSTECH",
        "HKUST",
        "CUHK",
        "CityU Hong Kong",
        "PolyU Hong Kong",
        "HIT",
        "Nanjing University",
        "Renmin University",
        "Sun Yat-sen University",
        "Southeast University",
        "Beihang University",
        "Baidu Research",
        "Salesforce Research",
        "Intel Labs",
        "Samsung Research",
        "Sony AI",
    ],
    "C": [
        "Other reputable universities",
        "Other national labs",
        "Other industrial research labs",
    ],
}


def get_default_quality_config() -> Dict[str, Any]:
    return {
        "strategy": "balanced",
        "strategies": deepcopy(DAILY_ARXIV_QUALITY_STRATEGIES),
        "institutionTiers": deepcopy(DEFAULT_DAILY_ARXIV_INSTITUTION_TIERS),
    }


def normalize_quality_config(value: Any) -> Dict[str, Any]:
    defaults = get_default_quality_config()
    if not isinstance(value, dict):
        return defaults

    normalized = deepcopy(defaults)
    strategy = value.get("strategy")
    if strategy in DAILY_ARXIV_QUALITY_STRATEGIES:
        normalized["strategy"] = strategy

    tiers = value.get("institutionTiers")
    if isinstance(tiers, dict):
        normalized_tiers: Dict[str, List[str]] = {}
        for tier in ["S", "A", "B", "C"]:
            raw_items = tiers.get(tier, [])
            if not isinstance(raw_items, list):
                raw_items = []
            seen = set()
            items = []
            for item in raw_items:
                if not isinstance(item, str):
                    continue
                cleaned = item.strip()
                if cleaned and cleaned.casefold() not in seen:
                    seen.add(cleaned.casefold())
                    items.append(cleaned)
            normalized_tiers[tier] = items
        normalized["institutionTiers"] = normalized_tiers

    strategies = value.get("strategies")
    if isinstance(strategies, dict):
        for key, strategy_config in strategies.items():
            if key not in normalized["strategies"] or not isinstance(strategy_config, dict):
                continue
            merged = dict(normalized["strategies"][key])
            merged.update(strategy_config)
            normalized["strategies"][key] = merged

    return normalized
