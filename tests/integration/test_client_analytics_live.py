import pytest

import tools.client_analytics as mod
import tools.sites as sites_mod
from models import ClientAnalyticsEnvelope, OnboardingStageSummary
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration

STAGES = {"assoc", "auth", "dhcp", "dns"}


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    sites_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def analytics(tools, live_ctx):
    async def run(**kwargs) -> ClientAnalyticsEnvelope:
        result = await tools["central_get_client_analytics"](live_ctx, **kwargs)
        assert isinstance(result, ClientAnalyticsEnvelope)
        return result

    return run


@pytest.fixture(scope="module")
async def busiest_site_id(tools, live_ctx):
    """Return the site with the most clients, or skip when none exist."""
    summary = await tools["central_get_sites"](live_ctx, view="summary")
    candidates = [s for s in summary.items if s.site_id and s.total_clients]
    if not candidates:
        pytest.skip("No site with clients available")
    return max(candidates, key=lambda s: s.total_clients).site_id


def _assert_stage_items(result: ClientAnalyticsEnvelope, expected: set[str]) -> None:
    assert result.total == len(result.items) == len(expected)
    assert {item.stage for item in result.items} == expected


async def test_onboarding_summary_default_returns_all_stages(analytics):
    result = await analytics(metric="onboarding")

    _assert_stage_items(result, STAGES)
    assert all(isinstance(item, OnboardingStageSummary) for item in result.items)
    assert result.meta.response_format == "concise"
    for item in result.items:
        assert item.attempts is None or item.attempts >= 0
        if item.attempts:
            assert item.success_percent is not None
            assert 0 <= item.success_percent <= 100
            assert item.success_percent + 0.01 >= (item.success or 0) / item.attempts * 100
    if all(item.attempts for item in result.items):
        product = 100.0
        for item in result.items:
            product *= item.success_percent / 100
        assert result.overall_score is not None
        assert abs(result.overall_score - product) < 0.5


async def test_onboarding_summary_stage_filter_and_detailed(analytics):
    result = await analytics(
        metric="onboarding", stage="dns", response_format="detailed"
    )

    _assert_stage_items(result, {"dns"})
    item = result.model_dump()["items"][0]
    assert set(item["failed"]) == {"clients", "access_devices", "wlans", "band", "servers"}
    assert "omitted_fields" not in result.model_dump()["meta"]


async def test_onboarding_summary_by_attempts_view_type(analytics):
    default = await analytics(metric="onboarding", stage="auth")
    by_attempts = await analytics(
        metric="onboarding", stage="auth", view_type="BY_ATTEMPTS"
    )

    _assert_stage_items(by_attempts, {"auth"})
    default_attempts = default.items[0].attempts or 0
    assert (by_attempts.items[0].attempts or 0) <= default_attempts


async def test_onboarding_summary_accepts_version(analytics):
    result = await analytics(metric="onboarding", version="1", time_range="last_1h")

    _assert_stage_items(result, STAGES)


async def test_onboarding_summary_site_scope(analytics, busiest_site_id):
    tenant = await analytics(metric="onboarding")
    site = await analytics(metric="onboarding", site_id=busiest_site_id)

    _assert_stage_items(site, STAGES)
    tenant_attempts = {item.stage: item.attempts or 0 for item in tenant.items}
    for item in site.items:
        assert (item.attempts or 0) <= tenant_attempts[item.stage]


async def test_onboarding_reasons_and_count_views(analytics):
    reasons = await analytics(metric="onboarding", view="reasons", status="FAILED")
    count = await analytics(
        metric="onboarding", view="count", status="FAILED", field="topclients"
    )

    _assert_stage_items(reasons, STAGES)
    _assert_stage_items(count, STAGES)
    assert all(item.kind == "onboarding_reasons" for item in reasons.items)
    assert all(
        datum.field == "topclients" and datum.stage == item.stage
        for item in count.items
        for datum in item.data
    )


async def test_usage_views(analytics, busiest_site_id):
    top = await analytics(metric="usage", view="top", top_n=3)
    trend = await analytics(metric="usage", view="trend", site_id=busiest_site_id)
    usage = await analytics(metric="usage", site_id=busiest_site_id)

    assert len(top.items) <= 3
    assert all(item.kind == "top_client_usage" for item in top.items)
    assert all(item.kind == "client_trend_sample" for item in trend.items)
    assert all(item.kind == "usage_sample" for item in usage.items)


async def test_mobility_trail_for_top_client(analytics):
    top = await analytics(metric="usage", view="top", top_n=1)
    if not top.items:
        pytest.skip("No client usage available")

    result = await analytics(
        metric="mobility", mac_address=top.items[0].mac_address, limit=5
    )

    assert len(result.items) <= 5
    assert all(item.kind == "mobility_event" for item in result.items)
