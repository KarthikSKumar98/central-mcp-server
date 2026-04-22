from types import SimpleNamespace
from unittest.mock import patch

import pytest

import tools.hierarchy as mod
from models import HierarchyNode, NetworkHierarchy
from tests.conftest import FakeMCP, make_ctx


def _site(id, name, collection_id=None):
    return SimpleNamespace(
        get_id=lambda: id,
        get_name=lambda: name,
        site_collection_id=collection_id,
    )


def _collection(id, name):
    return SimpleNamespace(get_id=lambda: id, get_name=lambda: name)


def _device(serial, device_type, site_id, provisioned=True):
    return SimpleNamespace(
        get_serial=lambda: serial,
        get_name=lambda: serial,
        device_type=device_type,
        site_id=site_id,
        provisioned_status=provisioned,
    )


def _make_scopes(collections, sites, devices):
    return SimpleNamespace(
        site_collections=collections,
        sites=sites,
        devices=devices,
    )


def _make_conn(scopes):
    return SimpleNamespace(get_scopes=lambda: scopes)


COLLECTION_A = _collection(1, "North America")
COLLECTION_B = _collection(2, "EMEA")

SITE_1 = _site(10, "Dallas HQ", collection_id=1)
SITE_2 = _site(20, "Chicago", collection_id=1)
SITE_3 = _site(30, "London", collection_id=2)

DEVICE_1 = _device("SN001", "ACCESS_POINT", site_id=10)
DEVICE_2 = _device("SN002", "SWITCH", site_id=10)
DEVICE_3 = _device("SN003", "GATEWAY", site_id=30)
DEVICE_4 = _device("SN004", "ACCESS_POINT", site_id=20)


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


@pytest.mark.asyncio
async def test_full_hierarchy(tools):
    scopes = _make_scopes(
        [COLLECTION_A, COLLECTION_B],
        [SITE_1, SITE_2, SITE_3],
        [DEVICE_1, DEVICE_2, DEVICE_3, DEVICE_4],
    )
    ctx = make_ctx()
    ctx.lifespan_context["conn"] = _make_conn(scopes)

    result = await tools["central_get_network_hierarchy"](ctx)

    assert isinstance(result, NetworkHierarchy)
    root = result.root
    assert root.id == "global"
    assert root.type == "root"

    collection_ids = {c.id for c in root.children}
    assert "collection:1" in collection_ids
    assert "collection:2" in collection_ids

    na = next(c for c in root.children if c.id == "collection:1")
    assert na.label == "North America"
    site_ids = {s.id for s in na.children}
    assert "site:10" in site_ids
    assert "site:20" in site_ids

    dallas = next(s for s in na.children if s.id == "site:10")
    device_ids = {d.id for d in dallas.children}
    assert "device:SN001" in device_ids
    assert "device:SN002" in device_ids

    emea = next(c for c in root.children if c.id == "collection:2")
    london = emea.children[0]
    assert london.id == "site:30"
    assert london.children[0].id == "device:SN003"


@pytest.mark.asyncio
async def test_site_names_filter(tools):
    scopes = _make_scopes(
        [COLLECTION_A, COLLECTION_B],
        [SITE_1, SITE_2, SITE_3],
        [DEVICE_1, DEVICE_2, DEVICE_3, DEVICE_4],
    )
    ctx = make_ctx()
    ctx.lifespan_context["conn"] = _make_conn(scopes)

    result = await tools["central_get_network_hierarchy"](ctx, site_names=["Dallas HQ"])

    assert isinstance(result, NetworkHierarchy)
    # Only coll-1 should appear; EMEA has no matching sites so it's pruned
    collection_ids = {c.id for c in result.root.children}
    assert "collection:1" in collection_ids
    assert "collection:2" not in collection_ids

    na = next(c for c in result.root.children if c.id == "collection:1")
    site_ids = {s.id for s in na.children}
    assert "site:10" in site_ids
    assert "site:20" not in site_ids


@pytest.mark.asyncio
async def test_no_collections_flat_hierarchy(tools):
    """When no collections exist the tool emits Global → Site → Device."""
    scopes = _make_scopes([], [SITE_1, SITE_2], [DEVICE_1])
    ctx = make_ctx()
    ctx.lifespan_context["conn"] = _make_conn(scopes)

    result = await tools["central_get_network_hierarchy"](ctx)

    assert isinstance(result, NetworkHierarchy)
    child_types = {c.type for c in result.root.children}
    assert child_types == {"site"}
    site_ids = {s.id for s in result.root.children}
    assert "site:10" in site_ids
    assert "site:20" in site_ids


@pytest.mark.asyncio
async def test_uncategorized_sites(tools):
    """Sites with no collection_id are linked directly under Global."""
    orphan = _site(99, "Orphan Site", collection_id=None)
    scopes = _make_scopes([COLLECTION_A], [SITE_1, orphan], [])
    ctx = make_ctx()
    ctx.lifespan_context["conn"] = _make_conn(scopes)

    result = await tools["central_get_network_hierarchy"](ctx)

    child_ids = {c.id for c in result.root.children}
    assert "collection:uncategorized" not in child_ids
    assert "site:99" in child_ids
    assert "collection:1" in child_ids


@pytest.mark.asyncio
async def test_device_node_fields(tools):
    """Device nodes carry serial as label and device_type."""
    scopes = _make_scopes([COLLECTION_A], [SITE_1], [DEVICE_1])
    ctx = make_ctx()
    ctx.lifespan_context["conn"] = _make_conn(scopes)

    result = await tools["central_get_network_hierarchy"](ctx)

    na = next(c for c in result.root.children if c.id == "collection:1")
    dallas = next(s for s in na.children if s.id == "site:10")
    dev = dallas.children[0]
    assert dev.id == "device:SN001"
    assert dev.label == "SN001"
    assert dev.device_type == "ACCESS_POINT"
    assert dev.type == "device"
    assert dev.provisioned is True


@pytest.mark.asyncio
async def test_unprovisioned_devices_included(tools):
    """Unprovisioned devices appear in the hierarchy with provisioned=False."""
    unprovisioned = _device("SN_UNPROV", "SWITCH", site_id=10, provisioned=False)
    scopes = _make_scopes([COLLECTION_A], [SITE_1], [DEVICE_1, unprovisioned])
    ctx = make_ctx()
    ctx.lifespan_context["conn"] = _make_conn(scopes)

    result = await tools["central_get_network_hierarchy"](ctx)

    na = next(c for c in result.root.children if c.id == "collection:1")
    dallas = next(s for s in na.children if s.id == "site:10")
    device_ids = {d.id for d in dallas.children}
    assert "device:SN001" in device_ids
    assert "device:SN_UNPROV" in device_ids

    unprov_node = next(d for d in dallas.children if d.id == "device:SN_UNPROV")
    assert unprov_node.provisioned is False

    prov_node = next(d for d in dallas.children if d.id == "device:SN001")
    assert prov_node.provisioned is True


@pytest.mark.asyncio
async def test_api_error_returns_error_string(tools):
    ctx = make_ctx()
    with patch("tools.hierarchy.build_hierarchy", side_effect=Exception("boom")):
        result = await tools["central_get_network_hierarchy"](ctx)

    assert isinstance(result, str)
    assert "fetching network hierarchy" in result
    assert "boom" in result
