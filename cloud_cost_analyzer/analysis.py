"""The FinOps questions: where does the money go, what looks wrong, what can be saved.

Every function takes the cleaned table from load.py and returns plain
pandas objects, so the report code and the tests can use the same results.

Cost column: BilledCost by default (what is on the invoice). EffectiveCost
(cost after discounts, spread over time) can be chosen instead.
"""

import numpy as np
import pandas as pd

from .load import UNTAGGED

USAGE = "Usage"
DEFAULT_COST = "BilledCost"
NON_PROD = {"dev", "development", "test", "testing", "qa", "staging", "sandbox"}


def usage_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Only real consumption. Credits, tax and refunds are not 'spend' of a team."""
    return df[df["ChargeCategory"] == USAGE]


def summary(df: pd.DataFrame, cost: str = DEFAULT_COST) -> dict:
    """Headline numbers for the whole bill."""
    usage = usage_rows(df)
    usage_cost = usage[cost].sum()
    by_category = df.groupby("ChargeCategory")[cost].sum()
    list_cost = usage["ListCost"].sum()
    untagged = usage.loc[~usage["IsTagged"], cost].sum()

    return {
        "period_start": df["Date"].min().date(),
        "period_end": df["Date"].max().date(),
        "providers": sorted(df["ProviderName"].unique()),
        "accounts": df["SubAccountName"].nunique(),
        "resources": df["ResourceId"].nunique(),
        "usage_cost": usage_cost,
        "credits": by_category.get("Credit", 0.0),
        "net_cost": df[cost].sum(),
        "list_cost": list_cost,
        "discount_savings": list_cost - usage_cost,
        "untagged_cost": untagged,
        "untagged_share": untagged / usage_cost if usage_cost else 0.0,
    }


def cost_by(df: pd.DataFrame, column: str, cost: str = DEFAULT_COST, top: int | None = None) -> pd.DataFrame:
    """Usage cost per value of `column` (service, account, team ...), biggest first.

    With `top`, everything after the first `top` rows is merged into "Other".
    """
    usage = usage_rows(df)
    table = usage.groupby(column)[cost].sum().sort_values(ascending=False).reset_index()
    table.columns = [column, "Cost"]

    if top is not None and len(table) > top:
        rest = table.iloc[top:]["Cost"].sum()
        table = pd.concat(
            [table.iloc[:top], pd.DataFrame({column: ["Other"], "Cost": [rest]})],
            ignore_index=True,
        )

    total = table["Cost"].sum()
    table["Share"] = table["Cost"] / total if total else 0.0
    return table


def daily_costs(df: pd.DataFrame, cost: str = DEFAULT_COST) -> pd.Series:
    """Usage cost per day, with missing days filled in as 0."""
    daily = usage_rows(df).groupby("Date")[cost].sum()
    if daily.empty:
        return daily
    all_days = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    return daily.reindex(all_days, fill_value=0.0).rename("Cost")


def find_anomalies(daily: pd.Series, window: int = 7, threshold: float = 2.5,
                   min_increase: float = 0.25) -> pd.DataFrame:
    """Days that cost much more than the days before them.

    Expected cost = median of the previous `window` days. A day is a spike if
    it is `threshold` (default 2.5) robust standard deviations above that (MAD based, so a
    single earlier spike does not hide the next one) AND at least
    `min_increase` (25%) above the expected value, so tiny bills don't alarm.
    """
    previous = daily.shift(1).rolling(window, min_periods=window)
    expected = previous.median()
    mad = previous.apply(lambda x: np.median(np.abs(x - np.median(x))), raw=True)
    spread = (1.4826 * mad).clip(lower=0.05 * expected.abs())

    score = (daily - expected) / spread
    is_spike = (expected > 0) & (score >= threshold) & (daily >= expected * (1 + min_increase))

    result = pd.DataFrame({
        "Date": daily.index,
        "Cost": daily.values,
        "Expected": expected.values,
        "Score": score.values,
    })[is_spike.values]
    result["Extra"] = result["Cost"] - result["Expected"]
    result["Increase"] = result["Cost"] / result["Expected"] - 1
    return result.reset_index(drop=True)


def untagged_by(df: pd.DataFrame, column: str = "SubAccountName", cost: str = DEFAULT_COST,
                top: int = 10) -> pd.DataFrame:
    """Where the untagged spend sits, so you know whom to ask to fix their tags."""
    usage = usage_rows(df)
    untagged = usage[~usage["IsTagged"]]
    table = untagged.groupby(column)[cost].sum().sort_values(ascending=False).head(top).reset_index()
    table.columns = [column, "Untagged cost"]
    return table


def top_resources(df: pd.DataFrame, cost: str = DEFAULT_COST, n: int = 15) -> pd.DataFrame:
    """The single resources (VMs, databases ...) that cost the most."""
    usage = usage_rows(df).dropna(subset=["ResourceId"]).copy()
    usage["Resource"] = usage["ResourceName"].fillna(usage["ResourceId"].map(short_resource_id))
    group = ["Resource", "ServiceName", "SubAccountName", "tag_environment"]
    table = usage.groupby(group)[cost].sum().sort_values(ascending=False).head(n).reset_index()
    table.columns = ["Resource", "Service", "Account", "Environment", "Cost"]
    return table


def short_resource_id(resource_id) -> str:
    """Azure ids are long paths (/subscriptions/.../vm-name); the last part is the name."""
    text = str(resource_id).rstrip("/")
    return text.rsplit("/", 1)[-1] if "/" in text else text


def spike_driver(df: pd.DataFrame, day, cost: str = DEFAULT_COST, window: int = 7) -> str:
    """Which service grew the most on a spike day, compared to its usual daily cost."""
    usage = usage_rows(df)
    day = pd.Timestamp(day)
    before = usage[(usage["Date"] < day) & (usage["Date"] >= day - pd.Timedelta(days=window))]
    usual = before.groupby("ServiceName")[cost].sum() / window
    today = usage[usage["Date"] == day].groupby("ServiceName")[cost].sum()
    growth = today.sub(usual, fill_value=0.0).sort_values(ascending=False)
    if growth.empty or growth.iloc[0] <= 0:
        return "-"
    return f"{growth.index[0]} (+{growth.iloc[0]:,.2f})"


def nonprod_weekend_cost(df: pd.DataFrame, cost: str = DEFAULT_COST) -> dict:
    """Dev/test machines running on Saturday and Sunday, when nobody uses them.

    That cost could be saved by stopping non-prod resources on weekends.
    """
    usage = usage_rows(df)
    nonprod = usage[usage["tag_environment"].str.lower().isin(NON_PROD)]
    weekend = nonprod[nonprod["Date"].dt.dayofweek >= 5]
    nonprod_cost = nonprod[cost].sum()
    weekend_cost = weekend[cost].sum()
    return {
        "nonprod_cost": nonprod_cost,
        "weekend_cost": weekend_cost,
        "weekend_share": weekend_cost / nonprod_cost if nonprod_cost else 0.0,
    }


def commitment_coverage(df: pd.DataFrame, cost: str = DEFAULT_COST) -> dict:
    """Share of compute spend covered by savings plans / reserved instances."""
    usage = usage_rows(df)
    compute = usage[usage["ServiceCategory"] == "Compute"]
    if "CommitmentDiscountId" in compute.columns:
        covered = compute[compute["CommitmentDiscountId"].notna()][cost].sum()
    else:
        covered = 0.0
    total = compute[cost].sum()
    return {
        "compute_cost": total,
        "covered_cost": covered,
        "coverage": covered / total if total else 0.0,
    }


def inconsistent_tag_keys(spellings: dict) -> dict:
    """Group raw tag keys that mean the same thing ("Project", "project", "Project ").

    Returns {normalised key: [spellings]} for keys that have more than one spelling.
    """
    from .load import TAG_ALIASES

    groups = {}
    for key in spellings:
        norm = key.strip().lower()
        norm = TAG_ALIASES.get(norm, norm)
        groups.setdefault(norm, []).append(key)
    return {norm: keys for norm, keys in groups.items() if len(keys) > 1}


def select_month(df: pd.DataFrame, month: str | None = "auto") -> pd.DataFrame:
    """Analyse one billing month, like you would with a real monthly bill.

    "auto" picks the month with the most usage cost (exports often contain a few
    late or stray rows from other months). None or "all" keeps everything.
    """
    if month in (None, "all"):
        return df
    if month == "auto":
        usage = usage_rows(df)
        if usage.empty:
            return df
        month = usage.groupby("Month")["BilledCost"].sum().idxmax()
    selected = df[df["Month"] == month]
    selected.attrs = {**df.attrs, "month": month, "rows_outside_month": len(df) - len(selected)}
    return selected


def recommendations(results: dict) -> list[str]:
    """Turn the numbers into short, concrete next steps."""
    tips = []
    s = results["summary"]

    if s["untagged_share"] > 0.10:
        worst = results["untagged_by_account"]
        who = f" (biggest: {worst.iloc[0, 0]})" if not worst.empty else ""
        tips.append(
            f"{s['untagged_share']:.0%} of usage cost has no team tag, so nobody owns it. "
            f"Enforce a tagging policy for the accounts with the most untagged spend{who}."
        )

    weekend = results["nonprod_weekend"]
    if weekend["weekend_cost"] > 0:
        tips.append(
            f"Dev/test resources cost {weekend['weekend_cost']:,.2f} on weekends "
            f"({weekend['weekend_share']:.0%} of all non-prod cost). Auto-stopping them "
            f"Saturday and Sunday would save about that much per month."
        )

    anomalies = results["anomalies"]
    if not anomalies.empty:
        worst = anomalies.sort_values("Extra", ascending=False).iloc[0]
        tips.append(
            f"{len(anomalies)} cost spike(s) found. The biggest on {worst['Date']:%d.%m.%Y}: "
            f"{worst['Cost']:,.2f} instead of ~{worst['Expected']:,.2f} expected, "
            f"biggest increase: {worst['Main driver']}. Check what was started that day."
        )

    coverage = results["commitment"]
    if coverage["compute_cost"] > 0 and coverage["coverage"] < 0.5:
        share = "None" if coverage["coverage"] == 0 else f"Only {coverage['coverage']:.0%}"
        tips.append(
            f"{share} of the compute spend uses savings plans or reservations. "
            f"For steady workloads, commitments are usually 20-40% cheaper than on-demand."
        )

    messy = inconsistent_tag_keys(results["quality"].get("tag_key_spellings", {}))
    if messy:
        examples = "; ".join(" / ".join(repr(k) for k in keys) for keys in list(messy.values())[:3])
        tips.append(
            f"{len(messy)} tag keys are spelled in more than one way ({examples}). "
            f"Agree on one spelling per key, otherwise reports split the same team into several."
        )

    return tips


def analyze(df: pd.DataFrame, cost: str = DEFAULT_COST, top: int = 10) -> dict:
    """Run everything once and return all results in one dict."""
    daily = daily_costs(df, cost)
    results = {
        "cost_column": cost,
        "quality": df.attrs.get("quality", {}),
        "month": df.attrs.get("month", "all"),
        "rows_outside_month": df.attrs.get("rows_outside_month", 0),
        "summary": summary(df, cost),
        "by_provider": cost_by(df, "ProviderName", cost),
        "by_service": cost_by(df, "ServiceName", cost, top=top),
        "by_category": cost_by(df, "ServiceCategory", cost),
        "by_account": cost_by(df, "SubAccountName", cost, top=top),
        "by_team": cost_by(df, "tag_business_unit", cost, top=top),
        "by_environment": cost_by(df, "tag_environment", cost),
        "by_region": cost_by(df, "RegionName", cost, top=top),
        "daily": daily,
        "anomalies": find_anomalies(daily),
        "untagged_by_account": untagged_by(df, "SubAccountName", cost),
        "untagged_by_service": untagged_by(df, "ServiceName", cost),
        "top_resources": top_resources(df, cost),
        "nonprod_weekend": nonprod_weekend_cost(df, cost),
        "commitment": commitment_coverage(df, cost),
    }
    anomalies = results["anomalies"]
    anomalies["Main driver"] = [spike_driver(df, d, cost) for d in anomalies["Date"]]
    results["recommendations"] = recommendations(results)
    return results


__all__ = [
    "UNTAGGED", "analyze", "commitment_coverage", "cost_by", "daily_costs", "find_anomalies",
    "inconsistent_tag_keys", "nonprod_weekend_cost", "select_month", "short_resource_id", "spike_driver", "recommendations", "summary", "top_resources", "untagged_by", "usage_rows",
]
