import json

import pandas as pd
import pytest

from cloud_cost_analyzer.load import UNTAGGED, clean, parse_tags
from conftest import make_bill, row


def test_parse_tags_normalises_keys_and_aliases():
    tags = parse_tags(json.dumps({" Env ": "Production", "Team": "data", "app": "shop"}))
    assert tags == {"environment": "prod", "business_unit": "data", "application": "shop"}


@pytest.mark.parametrize("value", [None, "", "not json", "[1, 2]", float("nan")])
def test_parse_tags_bad_input_is_empty(value):
    assert parse_tags(value) == {}


def test_lowercase_usage_is_fixed():
    df = make_bill([row(1, 1.0, category="usage"), row(1, 1.0)])
    assert set(df["ChargeCategory"]) == {"Usage"}
    assert df.attrs["quality"]["category_fixed"] == 1


def test_costs_become_numbers():
    df = make_bill([row(1, "2.5"), row(1, None)])
    assert df["BilledCost"].tolist() == [2.5, 0.0]


def test_duplicate_ids_are_dropped():
    df = make_bill([row(1, 1.0, rid="x"), row(1, 1.0, rid="x"), row(1, 1.0, rid="y")])
    assert len(df) == 2
    assert df.attrs["quality"]["duplicates_removed"] == 1


def test_bad_dates_are_dropped():
    rows = [row(1, 1.0), row(1, 1.0)]
    rows[1]["ChargePeriodStart"] = "yesterday-ish"
    df = make_bill(rows)
    assert len(df) == 1
    assert df.attrs["quality"]["bad_dates"] == 1


def test_tag_columns_and_is_tagged():
    df = make_bill([row(1, 1.0, team="data", env="dev"), row(1, 1.0, env="dev"), row(1, 1.0)])
    assert df["tag_business_unit"].tolist() == ["data", UNTAGGED, UNTAGGED]
    assert df["tag_environment"].tolist() == ["dev", "dev", UNTAGGED]
    # tagged = we know the owning team
    assert df["IsTagged"].tolist() == [True, False, False]


def test_missing_required_column_raises():
    with pytest.raises(ValueError, match="missing columns"):
        clean(pd.DataFrame({"BilledCost": [1.0]}))
