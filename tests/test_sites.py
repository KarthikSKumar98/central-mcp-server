import inspect
import json
from typing import get_type_hints
from unittest.mock import call, patch

import pytest
from fastmcp.exceptions import ToolError

import tools.sites as mod
from constants import MAX_PAGE_SIZE
from models import SiteEnvelope, SiteSummary
from tests.conftest import FakeMCP, annotated_field, make_ctx
from utils.cursor import decode_cursor, encode_cursor, hash_query

RAW_SITE = {
    "siteName": "HQ",
    "id": "site-42",
    "health": {
        "groups": [
            {"name": "Good", "value": 8},
            {"name": "Fair", "value": 2},
            {"name": "Poor", "value": 0},
        ]
    },
    "devices": {"count": 10},
    "clients": {"count": 50},
    "alerts": {
        "groups": [{"name": "Critical", "count": 1}],
        "totalCount": 3,
    },
}

RAW_SITE_PARTIAL_HEALTH = {
    **RAW_SITE,
    "health": {
        "groups": [
            {"name": "Good", "value": 8},
            {"name": "Fair", "value": 2},
        ]
    },
}

RAW_SITE_FLAT_HEALTH = {
    **RAW_SITE,
    "health": {"Poor": 0, "Fair": 2, "Good": 8},
}

RAW_DETAIL_SITE = {
    **RAW_SITE,
    "location": {"latitude": "25.2048", "longitude": "55.2708"},
}

RAW_DETAIL_SITE_2 = {
    **RAW_DETAIL_SITE,
    "siteName": "Branch",
    "id": "site-43",
}

RAW_DEVICE_HEALTH = {
    "siteName": "HQ",
    "deviceTypes": [
        {
            "name": "Access Points",
            "health": {"groups": [{"name": "Good", "value": 3}]},
        }
    ],
}

RAW_CLIENT_HEALTH = {
    "siteName": "HQ",
    "clientTypes": [
        {
            "name": "Wireless",
            "health": {"groups": [{"name": "Good", "value": 10}]},
        }
    ],
}


def site_page(
    items: list[dict] | None = None,
    *,
    total: int = 0,
    offset: int = 0,
) -> dict:
    page_items = [] if items is None else items
    return {
        "items": page_items,
        "count": len(page_items),
        "total": total,
        "offset": offset,
        "response": {},
    }


def command_page(items: list[dict] | None = None, *, total: int = 0) -> dict:
    return {
        "code": 200,
        "msg": {
            "items": [] if items is None else items,
            "total": total,
        },
    }


def set_detail_pages(
    ctx,
    master: dict,
    device: dict | None = None,
    client: dict | None = None,
) -> None:
    pages = [master]
    if master["msg"]["items"]:
        pages.extend(
            [
                command_page() if device is None else device,
                command_page() if client is None else client,
            ]
        )
    ctx.lifespan_context["conn"].command.side_effect = pages


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def test_registers_only_site_survivor(tools):
    assert list(tools) == ["central_get_sites"]


def test_get_sites_limit_has_schema_bounds(tools):
    parameter = inspect.signature(tools["central_get_sites"]).parameters["limit"]
    assert parameter.default is None
    annotation = get_type_hints(tools["central_get_sites"], include_extras=True)[
        "limit"
    ]
    field = annotated_field(annotation)
    assert field.metadata[0].ge == 1
    assert field.metadata[1].le == MAX_PAGE_SIZE


# --- get_sites ---


@pytest.mark.asyncio
async def test_get_sites_no_filter_returns_all(tools):
    ctx = make_ctx()
    set_detail_pages(
        ctx,
        command_page(
            [RAW_DETAIL_SITE, RAW_DETAIL_SITE_2],
            total=2,
        ),
    )
    result = await tools["central_get_sites"](ctx)

    assert isinstance(result, SiteEnvelope)
    assert [item.name for item in result.items] == ["HQ", "Branch"]
    assert result.total == 2
    assert result.meta.total_available == 2


@pytest.mark.asyncio
async def test_get_sites_with_filter(tools):
    ctx = make_ctx()
    set_detail_pages(
        ctx,
        command_page([RAW_DETAIL_SITE], total=1),
    )
    result = await tools["central_get_sites"](ctx, site_names=["HQ"])

    assert len(result.items) == 1
    assert result.items[0].name == "HQ"
    master_call = ctx.lifespan_context["conn"].command.call_args_list[0]
    assert master_call.kwargs["api_params"]["filter"] == "siteName in ('HQ')"


@pytest.mark.asyncio
async def test_get_sites_unknown_name_returns_error(tools):
    ctx = make_ctx()
    set_detail_pages(
        ctx,
        command_page([RAW_DETAIL_SITE], total=1),
    )
    result = await tools["central_get_sites"](
        ctx, site_names=["HQ", "NONEXISTENT"]
    )

    assert len(result.items) == 1
    assert result.items[0].name == "HQ"


@pytest.mark.asyncio
async def test_get_sites_failure_returns_formatted_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = Exception("boom")
    with (
        pytest.raises(ToolError, match="boom"),
    ):
        await tools["central_get_sites"](ctx)


@pytest.mark.asyncio
async def test_get_sites_empty_is_empty_envelope(tools):
    ctx = make_ctx()
    set_detail_pages(ctx, command_page(total=0))
    result = await tools["central_get_sites"](ctx)

    assert isinstance(result, SiteEnvelope)
    assert result.items == []
    assert result.meta.returned == 0
    assert result.total == 0
    assert result.next_cursor is None
    ctx.lifespan_context["conn"].command.assert_called_once()


@pytest.mark.asyncio
async def test_get_sites_limit_truncates_with_accounting(tools):
    ctx = make_ctx()
    set_detail_pages(ctx, command_page([RAW_DETAIL_SITE], total=3))
    result = await tools["central_get_sites"](ctx, limit=1)

    assert len(result.items) == 1
    assert result.next_cursor is not None
    assert result.truncated is False
    assert result.meta.total_available == 3


# --- view=summary ---


@pytest.mark.asyncio
async def test_get_sites_summary_keys(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE], total=1),
    ):
        result = await tools["central_get_sites"](ctx, view="summary")
    assert isinstance(result, SiteEnvelope)
    assert isinstance(result.items[0], SiteSummary)
    entry = result.items[0].model_dump()
    assert entry["name"] == "HQ"
    assert set(entry) == {
        "name",
        "site_id",
        "health",
        "total_devices",
        "total_clients",
        "critical_alerts",
        "total_alerts",
    }


@pytest.mark.asyncio
async def test_get_sites_summary_health_calculation(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE], total=1),
    ):
        result = await tools["central_get_sites"](ctx, view="summary")
    # Good=8, Fair=2, Poor=0 → round(8*1 + 2*0.5 + 0*0) = round(9) = 9
    assert result.items[0].health == 9


@pytest.mark.asyncio
async def test_get_sites_summary_partial_health_groups_treat_missing_as_zero(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE_PARTIAL_HEALTH], total=1),
    ):
        result = await tools["central_get_sites"](ctx, view="summary")
    assert result.items[0].health == 9


@pytest.mark.asyncio
async def test_get_sites_summary_flat_health_dict_is_normalized(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE_FLAT_HEALTH], total=1),
    ):
        result = await tools["central_get_sites"](ctx, view="summary")
    assert result.items[0].health == 9


@pytest.mark.asyncio
async def test_get_sites_summary_missing_health_groups(tools):
    ctx = make_ctx()
    site_no_health = {**RAW_SITE, "health": {}}
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([site_no_health], total=1),
    ):
        result = await tools["central_get_sites"](ctx, view="summary")
    assert result.items[0].health is None


@pytest.mark.asyncio
async def test_get_sites_summary_counts(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE], total=1),
    ):
        result = await tools["central_get_sites"](ctx, view="summary")
    entry = result.items[0]
    assert entry.site_id == "site-42"
    assert entry.total_devices == 10
    assert entry.total_clients == 50
    assert entry.total_alerts == 3
    assert entry.critical_alerts == 1


@pytest.mark.asyncio
async def test_get_sites_summary_preserves_upstream_order_without_health_sort(tools):
    ctx = make_ctx()
    healthy_alpha = {
        **RAW_SITE,
        "siteName": "Alpha",
        "health": {"groups": [{"name": "Good", "value": 10}]},
    }
    unhealthy_beta = {
        **RAW_SITE,
        "siteName": "Beta",
        "health": {"groups": [{"name": "Poor", "value": 10}]},
    }
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([healthy_alpha, unhealthy_beta], total=2),
    ):
        result = await tools["central_get_sites"](ctx, view="summary")

    assert [item.name for item in result.items] == ["Alpha", "Beta"]
    assert [item.health for item in result.items] == [10, 0]


@pytest.mark.asyncio
async def test_get_sites_summary_failure_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.sites.MonitoringSites.get_sites",
            side_effect=Exception("Central unavailable"),
        ),
        pytest.raises(ToolError, match="Central unavailable"),
    ):
        await tools["central_get_sites"](ctx, view="summary")


@pytest.mark.asyncio
async def test_get_sites_summary_rejects_site_names_before_connection(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.sites.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError, match=r"site_names.*view='detail'"),
    ):
        await tools["central_get_sites"](
            ctx,
            view="summary",
            site_names=["HQ"],
        )
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_sites_summary_page_one_emits_offset_cursor(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.sites.MonitoringSites.get_sites",
            return_value=site_page([RAW_SITE, RAW_DETAIL_SITE_2], total=5),
        ) as mock_get_sites,
        patch(
            "tools.sites.MonitoringSites.get_all_sites",
            side_effect=AssertionError("all-pages helper called"),
        ) as mock_get_all_sites,
    ):
        result = await tools["central_get_sites"](
            ctx,
            view="summary",
            limit=2,
        )

    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_sites",
        expected_query_hash=hash_query(
            {
                "view": "summary",
                "site_names": None,
            }
        ),
    )
    assert decoded.page_size == 2
    assert decoded.position == {"upstream_offset": 2}
    assert result.total == 5
    assert result.meta.total_available == 5
    mock_get_sites.assert_called_once_with(
        central_conn=ctx.lifespan_context["conn"],
        limit=2,
        offset=0,
    )
    mock_get_all_sites.assert_not_called()


@pytest.mark.asyncio
async def test_get_sites_summary_last_page_is_terminal(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE], total=5, offset=4),
    ):
        result = await tools["central_get_sites"](
            ctx,
            view="summary",
            limit=2,
            cursor=encode_cursor(
                "central_get_sites",
                2,
                {"upstream_offset": 4},
                hash_query({"view": "summary", "site_names": None}),
            ),
        )

    assert result.next_cursor is None
    assert result.total == 5


@pytest.mark.asyncio
async def test_get_sites_summary_cursor_replay_fetches_next_offset(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        side_effect=[
            site_page([RAW_SITE, RAW_DETAIL_SITE_2], total=3),
            site_page([RAW_SITE], total=3, offset=2),
        ],
    ) as mock_get_sites:
        first_page = await tools["central_get_sites"](
            ctx,
            view="summary",
            limit=2,
        )
        second_page = await tools["central_get_sites"](
            ctx,
            view="summary",
            cursor=first_page.next_cursor,
        )

    assert mock_get_sites.call_args_list[1].kwargs["offset"] == 2
    assert mock_get_sites.call_args_list[1].kwargs["limit"] == 2
    assert second_page.next_cursor is None


@pytest.mark.asyncio
async def test_get_sites_detail_uses_master_page_for_enrichment_and_cursor(tools):
    ctx = make_ctx()
    set_detail_pages(
        ctx,
        command_page([RAW_DETAIL_SITE, RAW_DETAIL_SITE_2], total=5),
        command_page([RAW_DEVICE_HEALTH], total=99),
        command_page([RAW_CLIENT_HEALTH], total=199),
    )

    result = await tools["central_get_sites"](ctx, view="detail", limit=2)

    assert [item.name for item in result.items] == ["HQ", "Branch"]
    assert result.items[0].metrics.devices["details"]["access_points"]["good"] == 3
    assert result.items[0].metrics.clients["details"]["wireless"]["good"] == 10
    assert result.total == 5
    assert result.meta.total_available == 5
    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_sites",
        expected_query_hash=hash_query(
            {
                "view": "detail",
                "site_names": None,
            }
        ),
    )
    assert decoded.position == {"upstream_offset": 2}
    expected_filter = "siteName in ('HQ', 'Branch')"
    assert ctx.lifespan_context["conn"].command.call_args_list == [
        call(
            api_method="GET",
            api_path="network-monitoring/v1/sites-health",
            api_params={"limit": 2, "offset": 0},
        ),
        call(
            api_method="GET",
            api_path="network-monitoring/v1/sites-device-health",
            api_params={
                "filter": expected_filter,
                "limit": 2,
                "offset": 0,
            },
        ),
        call(
            api_method="GET",
            api_path="network-monitoring/v1/sites-client-health",
            api_params={
                "filter": expected_filter,
                "limit": 2,
                "offset": 0,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_get_sites_detail_cursor_replay_advances_only_master_offset(tools):
    ctx = make_ctx()
    set_detail_pages(
        ctx,
        command_page([RAW_DETAIL_SITE], total=2),
    )
    first_page = await tools["central_get_sites"](
        ctx,
        view="detail",
        site_names=["HQ", "Branch"],
        limit=1,
    )

    ctx.lifespan_context["conn"].command.reset_mock()
    set_detail_pages(
        ctx,
        command_page([RAW_DETAIL_SITE_2], total=2),
    )
    second_page = await tools["central_get_sites"](
        ctx,
        view="detail",
        site_names=["HQ", "Branch"],
        cursor=first_page.next_cursor,
    )

    assert [item.name for item in second_page.items] == ["Branch"]
    calls = ctx.lifespan_context["conn"].command.call_args_list
    assert calls[0].kwargs["api_params"] == {
        "filter": "siteName in ('HQ', 'Branch')",
        "limit": 1,
        "offset": 1,
    }
    assert calls[1].kwargs["api_params"] == {
        "filter": "siteName in ('Branch')",
        "limit": 1,
        "offset": 0,
    }
    assert calls[2].kwargs["api_params"] == {
        "filter": "siteName in ('Branch')",
        "limit": 1,
        "offset": 0,
    }
    assert second_page.next_cursor is None


@pytest.mark.asyncio
async def test_get_sites_rejects_limit_conflicting_with_cursor_page_size(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE], total=2),
    ) as mock_get_sites:
        first_page = await tools["central_get_sites"](
            ctx,
            view="summary",
            limit=1,
        )
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_sites"](
                ctx,
                view="summary",
                limit=2,
                cursor=first_page.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "limit conflicts with the cursor page_size" in error["message"]
    assert mock_get_sites.call_count == 1


@pytest.mark.asyncio
async def test_get_sites_rejects_cursor_replayed_with_different_query(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_sites",
        return_value=site_page([RAW_SITE], total=2),
    ) as mock_get_sites:
        first_page = await tools["central_get_sites"](
            ctx,
            view="summary",
            limit=1,
        )
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_sites"](
                ctx,
                view="detail",
                cursor=first_page.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "invalid or stale cursor" in error["message"]
    assert mock_get_sites.call_count == 1
