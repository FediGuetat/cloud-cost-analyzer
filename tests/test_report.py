import pandas as pd
import pytest

from cloud_cost_analyzer.__main__ import main
from cloud_cost_analyzer.analysis import analyze
from cloud_cost_analyzer.report import console_summary, write_excel, write_powerbi


def test_excel_has_all_sheets(small_bill, tmp_path):
    path = write_excel(analyze(small_bill), tmp_path / "r.xlsx")
    sheets = pd.read_excel(path, sheet_name=None)
    for name in ["Summary", "Recommendations", "By service", "By team", "Daily", "Spikes", "Untagged"]:
        assert name in sheets


def test_powerbi_export_keeps_the_total(small_bill, tmp_path):
    path = write_powerbi(small_bill, tmp_path / "pbi.csv")
    fact = pd.read_csv(path)
    assert fact["BilledCost"].sum() == pytest.approx(small_bill["BilledCost"].sum())
    assert {"Date", "Service", "Team", "Environment", "BilledCost"} <= set(fact.columns)


def test_console_summary_mentions_totals(small_bill):
    text = console_summary(analyze(small_bill))
    assert "usage cost" in text
    assert "39.00" in text


def test_cli_end_to_end(tmp_path, capsys):
    rows = []
    for day in range(1, 15):
        rows.append({
            "Id": day, "BilledCost": 10.0 + (40.0 if day == 12 else 0.0), "ChargeCategory": "Usage",
            "ChargePeriodStart": f"2024-09-{day:02d} 00:00:00", "ServiceName": "EC2",
            "ServiceCategory": "Compute", "ProviderName": "AWS", "SubAccountName": "a",
            "RegionName": "eu", "ResourceId": "vm", "Tags": '{"business_unit": "data", "env": "dev"}',
        })
    src = tmp_path / "bill.csv"
    pd.DataFrame(rows).to_csv(src, index=False)

    main([str(src), "--out", str(tmp_path / "out")])

    assert (tmp_path / "out" / "cost_report.xlsx").exists()
    assert (tmp_path / "out" / "powerbi_costs.csv").exists()
    assert (tmp_path / "out" / "daily_cost.png").exists()
    assert "spike" in capsys.readouterr().out
