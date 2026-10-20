"""Load a FOCUS billing export and clean it up so it can be analysed.

FOCUS is the open billing format from the FinOps Foundation. AWS, Azure,
Google Cloud and Oracle can all export their bills in it, so the same code
works for every provider.

Real exports are messy, so cleaning is half the work here:
- cost columns come in as text or NULL -> numbers, missing = 0
- ChargeCategory is sometimes "usage" instead of "Usage"
- tags are a JSON string per row, and teams spell the keys differently
  ("environment", "env", " Environment") -> one clean column per tag
"""

import json

import pandas as pd

COST_COLUMNS = ["BilledCost", "EffectiveCost", "ListCost", "ContractedCost"]
REQUIRED_COLUMNS = ["BilledCost", "ChargeCategory", "ChargePeriodStart", "ServiceName"]
TEXT_COLUMNS = ["ProviderName", "ServiceName", "ServiceCategory", "SubAccountName", "RegionName"]

# the tags we turn into their own columns
TAG_KEYS = ["business_unit", "environment", "application"]
OWNER_TAG = "business_unit"
# different spellings of the same tag key -> the name we use
TAG_ALIASES = {"env": "environment", "team": "business_unit", "app": "application"}

# teams also write the same environment differently
ENV_VALUE_ALIASES = {
    "development": "dev", "devtest": "dev",
    "production": "prod", "prd": "prod",
    "testing": "test", "stage": "staging",
}

UNKNOWN = "(unknown)"
UNTAGGED = "(untagged)"


def load_focus(path) -> pd.DataFrame:
    """Read a FOCUS CSV (or .csv.gz) and return the cleaned table."""
    raw = pd.read_csv(path, low_memory=False)
    return clean(raw)


def parse_tags(value) -> dict:
    """Turn the Tags cell into a dict with normalised keys. Bad or empty -> {}."""
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
    """Clean a raw FOCUS table. Data quality numbers end up in df.attrs["quality"]."""
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"not a FOCUS export, missing columns: {missing}")

    df = raw.copy()
    quality = {"rows_in": len(df)}

    for col in COST_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # "usage" and "Usage" are the same thing
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
    if "ResourceId" not in df.columns:
        df["ResourceId"] = None
    if "ResourceName" not in df.columns:
        df["ResourceName"] = None
    if "CommitmentDiscountId" not in df.columns:
        df["CommitmentDiscountId"] = None

    raw_tags = df["Tags"] if "Tags" in df.columns else pd.Series(None, index=df.index)
    quality["tag_key_spellings"] = _count_tag_spellings(raw_tags)
    tags = raw_tags.apply(parse_tags)
    # "tagged" = we know which team owns the cost
    df["IsTagged"] = tags.apply(lambda t: OWNER_TAG in t)
    for key in TAG_KEYS:
        df["tag_" + key] = tags.apply(lambda t, k=key: t.get(k, UNTAGGED))

    quality["rows_out"] = len(df)
    df = df.reset_index(drop=True)
    df.attrs["quality"] = quality
    return df


def _count_tag_spellings(raw_tags: pd.Series) -> dict:
    """How often each raw tag key appears, to show inconsistent tagging."""
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
