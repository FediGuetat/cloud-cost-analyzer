import pandas as pd
import pytest

from cloud_cost_analyzer.analysis import (
    analyze, commitment_coverage, cost_by, daily_costs, find_anomalies, inconsistent_tag_keys,
    nonprod_weekend_cost, select_month, short_resource_id, summary, top_resources,
)
from conftest import make_bill, row


def test_summary_numbers(small_bill):
    s = summary(small_bill)
    assert s["usage_cost"] == pytest.approx(39.0)
    assert s["credits"] == pytest.approx(-3.0)
    assert s["net_cost"] == pytest.approx(36.0)
    assert s["untagged_cost"] == pytest.approx(4.0)
    assert s["untagged_share"] == pytest.approx(4 / 39)
    assert s["discount_savings"] == pytest.approx(2.0)  # list 12 vs paid 10 on day 4


def test_credits_are_not_counted_as_team_spend(small_bill):
    table = cost_by(small_bill, "tag_business_unit")
    assert table["Cost"].sum() == pytest.approx(39.0)


def test_cost_by_sorted_with_shares(small_bill):
    table = cost_by(small_bill, "ServiceName")
    assert table["ServiceName"].tolist() == ["EC2", "S3"]
    assert table["Cost"].tolist() == pytest.approx([30.0, 9.0])
    assert table["Share"].sum() == pytest.approx(1.0)


def test_cost_by_top_merges_rest_into_other():
    df = make_bill([row(1, c, service=s) for s, c in [("a", 5), ("b", 4), ("c", 3), ("d", 2)]])
    table = cost_by(df, "ServiceName", top=2)
    assert table["ServiceName"].tolist() == ["a", "b", "Other"]
    assert table["Cost"].tolist() == pytest.approx([5, 4, 5])


def test_daily_costs_fill_missing_days():
    df = make_bill([row(1, 2.0), row(3, 4.0)])
    daily = daily_costs(df)
    assert daily.tolist() == [2.0, 0.0, 4.0]


def series(values):
    return pd.Series(values, index=pd.date_range("2024-09-01", periods=len(values)), dtype=float)


def test_spike_is_found():
    daily = series([10, 11, 9, 10, 12, 10, 11, 30, 10])
    spikes = find_anomalies(daily)
    assert spikes["Date"].dt.day.tolist() == [8]
    assert spikes.iloc[0]["Expected"] == pytest.approx(10.0)


def test_normal_noise_is_not_a_spike():
    daily = series([10, 11, 9, 10, 12, 10, 11, 12, 9, 11])
    assert find_anomalies(daily).empty


def test_small_jump_below_min_increase_is_ignored():
    # perfectly flat history makes any change "many deviations", but +10% is not worth an alert
    daily = series([10] * 7 + [11])
    assert find_anomalies(daily).empty


def test_needs_full_window_before_judging():
    daily = series([1, 50, 1])
    assert find_anomalies(daily).empty


def test_nonprod_weekend_cost():
    # 2024-09-07 is a Saturday, 2024-09-09 a Monday
    df = make_bill([row(7, 5.0, env="dev"), row(9, 3.0, env="dev"), row(7, 100.0, env="prod")])
    result = nonprod_weekend_cost(df)
    assert result["weekend_cost"] == pytest.approx(5.0)
    assert result["nonprod_cost"] == pytest.approx(8.0)


def test_commitment_coverage():
    df = make_bill([row(1, 6.0, commitment="sp-1"), row(1, 4.0), row(1, 50.0, service_category="Storage")])
    assert commitment_coverage(df)["coverage"] == pytest.approx(0.6)


def test_inconsistent_tag_keys():
    messy = inconsistent_tag_keys({"Project": 3, "project": 1, "env": 2, "environment": 5, "owner": 1})
    assert messy == {"project": ["Project", "project"], "environment": ["env", "environment"]}


def test_select_month_auto_picks_biggest_month():
    rows = [row(1, 5.0), row(2, 5.0)]
    stray = row(1, 1.0)
    stray["ChargePeriodStart"] = "2024-03-01 00:00:00"
    df = select_month(make_bill(rows + [stray]))
    assert set(df["Month"]) == {"2024-09"}
    assert df.attrs["rows_outside_month"] == 1


def test_short_resource_id():
    assert short_resource_id("/subscriptions/x/resourceGroups/rg/providers/vm/my-vm") == "my-vm"
    assert short_resource_id("i-123") == "i-123"


def test_top_resources(small_bill):
    table = top_resources(small_bill, n=1)
    assert table.iloc[0]["Resource"] == "vm-1"
    assert table.iloc[0]["Cost"] == pytest.approx(30.0)


def test_analyze_runs_and_gives_recommendations(small_bill):
    results = analyze(small_bill)
    assert results["summary"]["usage_cost"] == pytest.approx(39.0)
    # 10% untagged and no commitments -> at least those two tips
    assert any("team tag" in tip for tip in results["recommendations"])
    assert any("savings plans" in tip for tip in results["recommendations"])
