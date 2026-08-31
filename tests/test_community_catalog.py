"""Contracts for versioned approved-community configuration."""

from pathlib import Path

import opportunity_radar


def test_default_scan_config_matches_the_versioned_approved_community_catalog() -> None:
    """The checked-in scan defaults must stay aligned with the approved community plan."""
    catalog = opportunity_radar.load_community_catalog(
        Path("configs/community_catalog.v1.yaml")
    )
    config = opportunity_radar.load_config(Path("configs/diesel_90d.yaml"))

    assert catalog.version == "community-catalog.v1"
    assert config.community_catalog_version == catalog.version
    assert [community.name for community in config.communities] == [
        "Cummins",
        "Duramax",
        "powerstroke",
        "FordDiesels",
    ]
    assert [community.name for community in catalog.communities] == [
        "Cummins",
        "Duramax",
        "powerstroke",
        "FordDiesels",
    ]

    cummins = catalog.communities[0]
    assert cummins.aliases == ("cummins", "5.9 cummins", "6.7 cummins")
    assert cummins.include == ("cummins", "ram diesel")
    assert cummins.exclude == ("WTB", "forsale")
    assert cummins.category == "diesel_platform"
    assert cummins.brand == "Ram"
    assert cummins.slang == ("5.9", "6.7", "common rail")

