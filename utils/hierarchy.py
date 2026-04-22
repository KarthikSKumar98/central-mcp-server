from models import HierarchyNode, NetworkHierarchy


def build_hierarchy(
    conn,
    site_names: list[str] | None = None,
) -> NetworkHierarchy:
    """Build the network hierarchy from the Central scopes object.

    Calls conn.get_scopes() once to obtain the fully-correlated Global →
    Site Collection → Site → Device tree, then maps it to HierarchyNode models.
    """
    scopes = conn.get_scopes()
    if site_names:
        site_names_set = set(site_names)
        filtered_sites = [s for s in scopes.sites if s.get_name() in site_names_set]
    else:
        filtered_sites = scopes.sites

    site_ids_in_scope = {s.get_id() for s in filtered_sites}
    # Group device nodes by site id
    devices_by_site: dict[int, list[HierarchyNode]] = {}
    for d in scopes.devices:
        if not d.site_id:
            continue
        sid = int(d.site_id)
        if sid in site_ids_in_scope:
            serial = d.get_serial() or d.get_name() or "unknown"
            devices_by_site.setdefault(sid, []).append(
                HierarchyNode(
                    id=f"device:{serial}",
                    label=serial,
                    type="device",
                    device_type=d.device_type,
                    provisioned=bool(d.provisioned_status),
                )
            )

    # Group site nodes by collection id (None = uncategorized)
    sites_by_collection: dict[int | None, list[HierarchyNode]] = {}
    for s in filtered_sites:
        coll_id = s.site_collection_id
        sites_by_collection.setdefault(coll_id, []).append(
            HierarchyNode(
                id=f"site:{s.get_id()}",
                label=s.get_name(),
                type="site",
                children=devices_by_site.get(s.get_id(), []),
            )
        )

    if not scopes.site_collections:
        # No collections — flat Global → Site → Device tree
        all_sites = [node for nodes in sites_by_collection.values() for node in nodes]
        return NetworkHierarchy(
            root=HierarchyNode(
                id="global", label="Global", type="root", children=all_sites
            )
        )

    known_ids = {c.get_id() for c in scopes.site_collections}
    collection_nodes: list[HierarchyNode] = []
    for c in scopes.site_collections:
        cid = c.get_id()
        child_sites = sites_by_collection.get(cid, [])
        if child_sites or not site_names:
            collection_nodes.append(
                HierarchyNode(
                    id=f"collection:{cid}",
                    label=c.get_name(),
                    type="collection",
                    children=child_sites,
                )
            )

    # Sites with no collection or an unrecognized collection id go directly under Global
    direct_sites: list[HierarchyNode] = list(sites_by_collection.get(None, []))
    for coll_id, nodes in sites_by_collection.items():
        if coll_id is not None and coll_id not in known_ids:
            direct_sites.extend(nodes)

    return NetworkHierarchy(
        root=HierarchyNode(
            id="global",
            label="Global",
            type="root",
            children=collection_nodes + direct_sites,
        )
    )
