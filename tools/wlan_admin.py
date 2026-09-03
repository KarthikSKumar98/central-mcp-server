import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from fastmcp.server.elicitation import AcceptedElicitation
from mcp import McpError

from tools import DESTRUCTIVE
from utils.common import api_context, format_tool_error
from utils.sites import fetch_site_name_id_map, resolve_global_scope_id

_UNSCOPED_CHOICE = "(no site — unscoped library profile)"
_GLOBAL_CHOICE = "Global"

SECURITY_TYPE = Literal["open", "wpa2-personal", "wpa3-personal", "wpa2-enterprise", "wpa3-enterprise"]

DEVICE_FUNCTION = Literal[
    "CAMPUS_AP",
    "ACCESS_SWITCH",
    "AGG_SWITCH",
    "CORE_SWITCH",
    "MOBILITY_GW",
    "BRIDGE",
    "MICROBRANCH_AP",
    "BRANCH_GW",
    "HYBRID_NAC",
]

_SECURITY_OPMODE = {
    "open": "OPEN",
    "wpa2-personal": "WPA2_PERSONAL",
    "wpa3-personal": "WPA3_SAE",
    "wpa2-enterprise": "WPA2_ENTERPRISE",
    "wpa3-enterprise": "WPA3_ENTERPRISE_CNSA",
}

_WLAN_PATH = "network-config/v1alpha1/wlan-ssids/{wlan_name}"


def _build_scope_params(site_id: str | None, device_function: str) -> dict:
    """Build the object-type/scope-id/device-function query params for site scoping."""
    if not site_id:
        return {}
    return {
        "object-type": "LOCAL",
        "scope-id": site_id,
        "device-function": device_function,
    }


def _build_wlan_payload(
    wlan_name: str,
    security_type: SECURITY_TYPE,
    vlan: str | None,
    passphrase: str | None,
    hidden: bool | None,
    forward_mode: str,
) -> dict:
    """Build the network-config/v1alpha1/wlan-ssids/{wlan_name} request body."""
    payload: dict = {
        "essid": {"name": wlan_name},
        "opmode": _SECURITY_OPMODE[security_type],
        "forward-mode": forward_mode,
    }
    if vlan is not None:
        payload["vlan-id-range"] = [vlan]
        payload["vlan-selector"] = "VLAN_RANGES"
    if passphrase is not None:
        payload["personal-security"] = {"wpa-passphrase": passphrase}
    if hidden is not None:
        payload["hide-ssid"] = hidden
    return payload


async def _resolve_site(
    ctx: Context, conn, site_name: str | None
) -> tuple[str | None, str | None] | str:
    """Resolve a site_name to (site_id, site_name), asking the user to choose one if omitted.

    - site_name="none" (case-insensitive) explicitly requests an unscoped/library profile.
    - site_name="global" (case-insensitive) explicitly requests the account's Global scope.
    - site_name given (a real site name): resolved directly, no prompt.
    - site_name omitted: the user is asked to pick a site, Global, or "no site" via
      elicitation when the client supports it; otherwise a preview listing the options
      is returned asking the caller to re-run with an explicit site_name.

    Returns (site_id, site_name) — both None for an explicit unscoped choice, or
    (global_scope_id, "Global") for the Global choice — or an error/preview string
    when the caller should NOT proceed yet.
    """
    if site_name is not None:
        stripped = site_name.strip().lower()
        if stripped == "none":
            return None, None
        if stripped == "global":
            global_id = await asyncio.to_thread(resolve_global_scope_id, conn)
            if global_id is None:
                return format_tool_error(
                    "resolving site", ValueError("Could not resolve the account's Global scope id.")
                )
            return global_id, _GLOBAL_CHOICE
        name_map = await asyncio.to_thread(fetch_site_name_id_map, conn)
        site_id = name_map.get(site_name)
        if site_id is None:
            return format_tool_error(
                "resolving site",
                ValueError(
                    f"No site named '{site_name}' found. Call central_get_summary to see valid site names."
                ),
            )
        return site_id, site_name

    name_map = await asyncio.to_thread(fetch_site_name_id_map, conn)
    options = list(name_map.keys()) + [_GLOBAL_CHOICE, _UNSCOPED_CHOICE]
    try:
        elicit_result = await ctx.elicit(
            "No site specified. Choose a site to scope this WLAN to, Global, or unscoped.",
            response_type=options,
        )
    except McpError:
        listed = ", ".join(name_map.keys())
        return (
            f"No site specified. Available sites: {listed}.\n"
            "Re-run with site_name=<name> to scope this WLAN to a site, "
            "site_name='Global' for the account-wide Global scope, "
            "or site_name='none' to explicitly create an unscoped library profile."
        )
    if not isinstance(elicit_result, AcceptedElicitation):
        return format_tool_error(
            "resolving site", ValueError("Site selection was declined or cancelled.")
        )
    chosen = elicit_result.data
    if chosen == _UNSCOPED_CHOICE:
        return None, None
    if chosen == _GLOBAL_CHOICE:
        global_id = await asyncio.to_thread(resolve_global_scope_id, conn)
        if global_id is None:
            return format_tool_error(
                "resolving site", ValueError("Could not resolve the account's Global scope id.")
            )
        return global_id, _GLOBAL_CHOICE
    return name_map.get(chosen), chosen


async def _confirm(ctx: Context, lines: list[str], confirm: bool) -> str | None:
    """Confirm the pending change.

    Uses interactive elicitation when the client supports it. Otherwise falls
    back to requiring an explicit ``confirm=True`` re-call, showing the same
    preview so the caller can review it first. Returns an error/preview
    string when the caller should NOT proceed yet, else None.
    """
    approval_msg = "\n".join(lines)
    try:
        elicit_result = await ctx.elicit(approval_msg, response_type=None)
    except McpError:
        if confirm:
            return None
        return (
            approval_msg
            + "\n\nThis MCP client does not support interactive confirmation. "
            "Review the change above, then re-run this tool with confirm=true to proceed."
        )
    if not isinstance(elicit_result, AcceptedElicitation):
        return format_tool_error(
            "modifying WLAN",
            ValueError("Change was declined or cancelled by the user."),
        )
    return None


def register(mcp: FastMCP) -> None:
    """Register WLAN write tools with the MCP server."""

    @mcp.tool(annotations=DESTRUCTIVE)
    async def central_create_wlan(
        ctx: Context,
        wlan_name: str,
        security_type: SECURITY_TYPE,
        vlan: str | None = None,
        passphrase: str | None = None,
        hidden: bool | None = None,
        site_name: str | None = None,
        device_function: DEVICE_FUNCTION = "CAMPUS_AP",
        forward_mode: Literal[
            "FORWARD_MODE_BRIDGE", "FORWARD_MODE_L2", "FORWARD_MODE_L3", "FORWARD_MODE_MIXED"
        ] = "FORWARD_MODE_BRIDGE",
        confirm: bool = False,
    ) -> str:
        """Create a new WLAN SSID profile, after user confirmation.

        Shows the proposed WLAN configuration for approval before creating it.
        The WLAN will NOT be created unless the user accepts.

        If site_name is omitted, the user is asked to pick a site (or explicitly
        choose "no site") before proceeding — the profile is never silently
        created unscoped.

        Parameters
        ----------
        - wlan_name: SSID / profile name for the new WLAN.
        - security_type: One of "open", "wpa2-personal", "wpa3-personal",
          "wpa2-enterprise", "wpa3-enterprise".
        - vlan: VLAN ID to assign this WLAN to. Omit to leave unset.
        - passphrase: Pre-shared key. Required for wpa2-personal / wpa3-personal.
        - hidden: Whether to hide the SSID from broadcast. Defaults to visible.
        - site_name: Exact site name (e.g. "TheCity") to scope this WLAN to.
          Resolved automatically — no need to call central_get_summary first.
          Pass "Global" for the account-wide Global scope, or "none" to
          explicitly create an unscoped library profile. Omit entirely to
          be asked to choose.
        - device_function: Device function for site scoping (only used when
          site_name is set). Defaults to "CAMPUS_AP".
        - forward_mode: SSID forward mode. Defaults to "FORWARD_MODE_BRIDGE".
        - confirm: Only needed on clients without interactive confirmation
          support. Leave false on the first call to see a preview; re-run
          with confirm=true after reviewing it to actually create the WLAN.

        """
        if security_type in ("wpa2-personal", "wpa3-personal") and not passphrase:
            return format_tool_error(
                "validating parameters",
                ValueError(f"passphrase is required for security_type '{security_type}'"),
            )

        async with api_context(ctx) as conn:
            resolved = await _resolve_site(ctx, conn, site_name)
            if isinstance(resolved, str):
                return resolved
            site_id, site_name = resolved

            lines = [
                f"Confirm CREATE WLAN '{wlan_name}'"
                + (f" scoped to site '{site_name}'" if site_name else " (unscoped library profile)"),
                f"  security={security_type}  vlan={vlan}  hidden={bool(hidden)}  forward_mode={forward_mode}",
                "\nAccept to proceed. Decline or cancel to abort.",
            ]
            error = await _confirm(ctx, lines, confirm)
            if error:
                return error

            payload = _build_wlan_payload(wlan_name, security_type, vlan, passphrase, hidden, forward_mode)
            params = _build_scope_params(site_id, device_function)
            try:
                response = await asyncio.to_thread(
                    conn.command,
                    api_method="POST",
                    api_path=_WLAN_PATH.format(wlan_name=wlan_name),
                    api_params=params or None,
                    api_data=payload,
                )
            except Exception as e:
                return format_tool_error("creating WLAN", e)

        if response["code"] not in (200, 201):
            return format_tool_error(
                "creating WLAN",
                Exception(f"API returned {response['code']}: {response['msg']}"),
            )
        return f"WLAN '{wlan_name}' created" + (f" scoped to site '{site_name}'." if site_name else " as a library profile.")

    @mcp.tool(annotations=DESTRUCTIVE)
    async def central_update_wlan(
        ctx: Context,
        wlan_name: str,
        security_type: SECURITY_TYPE | None = None,
        vlan: str | None = None,
        passphrase: str | None = None,
        hidden: bool | None = None,
        site_name: str | None = None,
        device_function: DEVICE_FUNCTION = "CAMPUS_AP",
        confirm: bool = False,
    ) -> str:
        """Update an existing WLAN SSID profile's configuration, after user confirmation.

        Only fields you provide are changed; omitted fields are left as-is.
        Shows the proposed changes for approval before applying them.

        Parameters
        ----------
        - wlan_name: Name of the existing WLAN profile to update.
        - security_type: New security type, if changing.
        - vlan: New VLAN ID, if changing.
        - passphrase: New pre-shared key, if changing.
        - hidden: New hidden-SSID setting, if changing.
        - site_name: Exact site name (e.g. "TheCity"), if this profile is
          site-scoped. Resolved automatically — no need to call
          central_get_summary first. Pass "Global" for the account-wide
          Global scope, or "none" for a SHARED/library profile. Omit
          entirely to be asked to choose.
        - device_function: Device function for site scoping (only used when
          site_name is set). Defaults to "CAMPUS_AP".
        - confirm: Only needed on clients without interactive confirmation
          support. Leave false on the first call to see a preview; re-run
          with confirm=true after reviewing it to actually apply the update.

        """
        updates: dict = {}
        if security_type is not None:
            updates["opmode"] = _SECURITY_OPMODE[security_type]
        if vlan is not None:
            updates["vlan-id-range"] = [vlan]
            updates["vlan-selector"] = "VLAN_RANGES"
        if passphrase is not None:
            updates["personal-security"] = {"wpa-passphrase": passphrase}
        if hidden is not None:
            updates["hide-ssid"] = hidden

        if not updates:
            return format_tool_error(
                "validating parameters",
                ValueError("At least one field to update must be provided."),
            )

        display_updates = updates.copy()
        if "personal-security" in display_updates:
            display_updates["personal-security"] = {"wpa-passphrase": "<redacted>"}

        async with api_context(ctx) as conn:
            resolved = await _resolve_site(ctx, conn, site_name)
            if isinstance(resolved, str):
                return resolved
            site_id, site_name = resolved

            lines = [
                f"Confirm UPDATE WLAN '{wlan_name}'"
                + (f" scoped to site '{site_name}'" if site_name else " (library profile)"),
                f"  changes: {display_updates}",
                "\nAccept to proceed. Decline or cancel to abort.",
            ]
            error = await _confirm(ctx, lines, confirm)
            if error:
                return error

            params = _build_scope_params(site_id, device_function)
            try:
                response = await asyncio.to_thread(
                    conn.command,
                    api_method="PATCH",
                    api_path=_WLAN_PATH.format(wlan_name=wlan_name),
                    api_params=params or None,
                    api_data=updates,
                )
            except Exception as e:
                return format_tool_error("updating WLAN", e)

        if response["code"] not in (200, 204):
            return format_tool_error(
                "updating WLAN",
                Exception(f"API returned {response['code']}: {response['msg']}"),
            )
        return f"WLAN '{wlan_name}' updated."

    @mcp.tool(annotations=DESTRUCTIVE)
    async def central_delete_wlan(
        ctx: Context,
        wlan_name: str,
        site_name: str | None = None,
        device_function: DEVICE_FUNCTION = "CAMPUS_AP",
        confirm: bool = False,
    ) -> str:
        """Delete a WLAN SSID profile. Cannot be undone.

        Parameters
        ----------
        - wlan_name: Name of the WLAN profile to delete.
        - site_name: Exact site name (e.g. "TheCity"), if this profile is
          site-scoped. Resolved automatically — no need to call
          central_get_summary first. Pass "Global" for the account-wide
          Global scope, or "none" for a SHARED/library profile. Omit
          entirely to be asked to choose.
        - device_function: Device function for site scoping (only used when
          site_name is set). Defaults to "CAMPUS_AP".
        - confirm: Only needed on clients without interactive confirmation
          support. Leave false on the first call to see a preview; re-run
          with confirm=true after reviewing it to actually delete the WLAN.

        """
        async with api_context(ctx) as conn:
            resolved = await _resolve_site(ctx, conn, site_name)
            if isinstance(resolved, str):
                return resolved
            site_id, site_name = resolved

            lines = [
                f"Confirm DELETE WLAN '{wlan_name}'"
                + (f" scoped to site '{site_name}'" if site_name else " (library profile)"),
                "WARNING: This permanently removes the WLAN profile. Any clients connected to it will be disconnected.",
                "This action cannot be undone.",
                "\nAccept to proceed. Decline or cancel to abort.",
            ]
            error = await _confirm(ctx, lines, confirm)
            if error:
                return error

            params = _build_scope_params(site_id, device_function)
            try:
                response = await asyncio.to_thread(
                    conn.command,
                    api_method="DELETE",
                    api_path=_WLAN_PATH.format(wlan_name=wlan_name),
                    api_params=params or None,
                )
            except Exception as e:
                return format_tool_error("deleting WLAN", e)

        if response["code"] not in (200, 204):
            return format_tool_error(
                "deleting WLAN",
                Exception(f"API returned {response['code']}: {response['msg']}"),
            )
        return f"WLAN '{wlan_name}' deleted."
