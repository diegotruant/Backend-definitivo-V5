from engines import Tier, tier_for


def test_tier_lookup_smoke() -> None:
    assert tier_for("power_engine") is Tier.REFERENCE


def test_public_alias_smoke() -> None:
    assert tier_for("metabolic_profiler") is Tier.MODEL
