"""Read a FOCUS billing export and clean it."""

import json

import pandas as pd

COST_COLUMNS = ["BilledCost", "EffectiveCost", "ListCost", "ContractedCost"]
REQUIRED_COLUMNS = ["BilledCost", "ChargeCategory", "ChargePeriodStart", "ServiceName"]
TEXT_COLUMNS = ["ProviderName", "ServiceName", "ServiceCategory", "SubAccountName", "RegionName"]

TAG_KEYS = ["business_unit", "environment", "application"]
OWNER_TAG = "business_unit"
TAG_ALIASES = {"env": "environment", "team": "business_unit", "app": "application"}
ENV_VALUE_ALIASES = {
    "development": "dev", "devtest": "dev",
    "production": "prod", "prd": "prod",
    "testing": "test", "stage": "staging",
}

UNKNOWN = "(unknown)"
UNTAGGED = "(untagged)"


def load_focus(path) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    return clean(raw)


def parse_tags(value) -> dict:
    # Tags is a JSON string per row, keys spelled however the team liked
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        tags = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(tags, dict):
        return {}

    clean_tags = {}
    for key, val in tags.items():
        key = str(key).strip().lower()
        key = TAG_ALIASES.get(key, key)
        if val is None or not str(val).strip():
            continue
        val = str(val).strip()
        if key == "environment":
            val = ENV_VALUE_ALIASES.get(val.lower(), val.lower())
        clean_tags[key] = val
    return clean_tags


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"not a FOCUS export, missing columns: {missing}")

    df = raw.copy()
    quality = {"rows_in": len(df)}

    for col in COST_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    category = df["ChargeCategory"].astype(str).str.strip()
    quality["category_fixed"] = int((category != category.str.capitalize()).sum())
    df["ChargeCategory"] = category.str.capitalize()

    df["ChargePeriodStart"] = pd.to_datetime(df["ChargePeriodStart"], errors="coerce")
    quality["bad_dates"] = int(df["ChargePeriodStart"].isna().sum())
    df = df.dropna(subset=["ChargePeriodStart"])
    df["Date"] = df["ChargePeriodStart"].dt.normalize()
    df["Month"] = df["ChargePeriodStart"].dt.to_period("M").astype(str)

    if "Id" in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset="Id")
        quality["duplicates_removed"] = before - len(df)
    else:
        quality["duplicates_removed"] = 0

    for col in TEXT_COLUMNS:
        if col not in df.columns:
            df[col] = UNKNOWN
        df[col] = df[col].fillna(UNKNOWN).astype(str)
    for col in ["ResourceId", "ResourceName", "CommitmentDiscountId"]:
        if col not in df.columns:
            df[col] = None

    raw_tags = df["Tags"] if "Tags" in df.columns else pd.Series(None, index=df.index)
    quality["tag_key_spellings"] = _count_tag_spellings(raw_tags)
    tags = raw_tags.apply(parse_tags)
    # tagged means we know which team owns the cost
    df["IsTagged"] = tags.apply(lambda t: OWNER_TAG in t)
    for key in TAG_KEYS:
        df["tag_" + key] = tags.apply(lambda t, k=key: t.get(k, UNTAGGED))

    quality["rows_out"] = len(df)
    df = df.reset_index(drop=True)
    df.attrs["quality"] = quality
    return df


def _count_tag_spellings(raw_tags: pd.Series) -> dict:
    counts = {}
    for value in raw_tags.dropna():
        try:
            tags = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(tags, dict):
            for key in tags:
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
