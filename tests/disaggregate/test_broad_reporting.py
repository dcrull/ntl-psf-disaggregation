from __future__ import annotations

from nocturne.disaggregate.broad_reporting import broad_reporting_matrix


def test_broad_reporting_matrix_is_minimal_and_coverage_complete() -> None:
    delhi = broad_reporting_matrix("india_delhi")
    new_york = broad_reporting_matrix("usa_new_york")

    assert [item.kind for item in delhi] == ["direct", "uniform", "stationary"]
    assert [item.kind for item in new_york] == [
        "direct",
        "uniform",
        "stationary",
        "stationary",
    ]
    assert all(item.radiance_contract == "broad" for item in (*delhi, *new_york))
    assert delhi[-1].proxy == "built_form_primary"
    assert new_york[-1].proxy == "s2_only_ablation"
    assert all(item.water_variant == "no_water_prior" for item in new_york[2:])
