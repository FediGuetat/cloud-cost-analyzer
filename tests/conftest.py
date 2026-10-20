"""Small fake FOCUS bills, so every number in the tests can be checked by hand."""

import json

import pandas as pd
import pytest

from cloud_cost_analyzer.load import clean


def row(day, cost, service="EC2", category="Usage", account="acc-a", team=None, env=None,
        resource="r1", list_cost=None, commitment=None, service_category="Compute", rid=None):
    tags = {}
    if team:
        tags["business_unit"] = team
    if env:
        tags["environment"] = env
    return {
        "Id": rid,
        "BilledCost": cost,
        "EffectiveCost": cost,
        "ListCost": cost if list_cost is None else list_cost,
        "ChargeCategory": category,
        "ChargePeriodStart": f"2024-09-{day:02d} 00:00:00",
        "ServiceName": service,
        "ServiceCategory": service_category,
        "ProviderName": "AWS",
        "SubAccountName": account,
        "RegionName": "eu-central-1",
        "ResourceId": resource,
        "ResourceName": None,
        "CommitmentDiscountId": commitment,
        "Tags": json.dumps(tags) if tags else None,
    }


def make_bill(rows) -> pd.DataFrame:
    raw = pd.DataFrame(rows)
    raw["Id"] = [r.get("Id") or i for i, r in enumerate(rows)]
    return clean(raw)


@pytest.fixture
def small_bill():
    """3 days, 2 teams, one untagged row, one credit."""
    return make_bill([
        row(2, 10.0, team="data", env="prod", resource="vm-1"),
        row(2, 5.0, service="S3", team="ai", env="dev", resource="bucket", service_category="Storage"),
        row(3, 10.0, team="data", env="prod", resource="vm-1"),
        row(3, 4.0, service="S3", resource="bucket-2", service_category="Storage"),  # untagged
        row(4, 10.0, team="data", env="prod", resource="vm-1", list_cost=12.0),
        row(4, -3.0, category="Credit", resource=None),
    ])
