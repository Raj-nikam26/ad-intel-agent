import pandas as pd
from app.graph_builder import build_graph, advertiser_summary, advertisers_by_category_and_office


def make_df():
    return pd.DataFrame({
        "Advertiser Name by AI": ["Acme Corp", "Acme Corp", "Beta Inc", "Pune"],  # "Pune" as advertiser name on purpose - collision test
        "AdvertiserName": ["ACME CORP", "ACME CORP", "BETA INC", "PUNE ENTERPRISES"],
        "Publication": ["Times", "Herald", "Times", "Herald"],
        "Category": ["Finance", "Finance", "Retail", "Retail"],
        "Sub Category": ["Loan", "Loan", "Fashion", "Fashion"],
        "AdvertiserLocation": ["Pune", "Pune", "Mumbai", "Pune"],  # "Pune" as a LOCATION value too - same collision test
        "AdvertiserSalesOffice": ["Pune", "Pune", "Mumbai", "Pune"],
        "Edition": ["Pune", "Mumbai", "Pune", "Mumbai"],
        "Date": ["2026-01-01"] * 4,
        "Page": [1, 2, 3, 4],
        "Width (cm)": [4, 4, 5, 5],
        "Height (cm)": [5, 5, 5, 5],
        "Area (sq cm)": [20, 20, 25, 25],
        "Advertiser Reach": ["Regional"] * 4,
        "IsHouseAd": [None, None, "Yes", None],
    })


def test_graph_builds_without_node_collision():
    # "Pune" appears as both an advertiser name AND a location/sales
    # office/edition value - this must NOT collapse into one node.
    g = build_graph(make_df())
    assert "Advertiser::Pune" in g
    assert "Location::Pune" in g
    assert g.nodes["Advertiser::Pune"]["type"] == "Advertiser"
    assert g.nodes["Location::Pune"]["type"] == "Location"


def test_advertiser_summary_aggregates_correctly():
    g = build_graph(make_df())
    summary = advertiser_summary(g, "Acme Corp")
    assert summary["total_ad_insertions"] == 2
    assert set(summary["publications"]) == {"Times", "Herald"}
    assert summary["categories"] == ["Finance"]
    assert summary["house_ads"] == 0


def test_house_ad_flag_tracked():
    g = build_graph(make_df())
    summary = advertiser_summary(g, "Beta Inc")
    assert summary["house_ads"] == 1


def test_multihop_query():
    g = build_graph(make_df())
    result = advertisers_by_category_and_office(g, "Finance", "Pune")
    assert "Acme Corp" in result
    assert "Beta Inc" not in result


def test_unknown_advertiser_returns_none():
    g = build_graph(make_df())
    assert advertiser_summary(g, "Nonexistent Co") is None
