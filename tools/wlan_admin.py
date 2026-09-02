import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from fastmcp.server.elicitation import AcceptedElicitation
from mcp import McpError

from tools import DESTRUCTIVE
from utils.common import api_context, format_tool_error

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


async def _confirm(ctx: Context, lines: list[str]) -> str | None:
    """Show an elicitation prompt. Returns an error string on decline/no-support, else None."""
    approval_msg = "\n".join(lines)
    try:
        elicit_result = await ctx.elicit(approval_msg, response_type=None)
    except McpError:
        return format_tool_error(
            "modifying WLAN",
            ValueError(
                "This MCP client does not support elicitation. "
                "WLAN write operations require a client that declares elicitation capability."
            ),
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
        site_id: str | None = None,
        device_function: DEVICE_FUNCTION = "CAMPUS_AP",
        forward_mode: Literal[
            "FORWARD_MODE_BRIDGE", "FORWARD_MODE_L2", "FORWARD_MODE_L3", "FORWARD_MODE_MIXED"
        ] = "FORWARD_MODE_BRIDGE",
    ) -> str:
        """Create a new WLAN SSID profile, after user confirmation.

        Shows the proposed WLAN configuration for approval before creating it.
        The WLAN will NOT be created unless the user accepts.

        By default the profile is created as a SHARED/library profile, not bound
        to any site. Pass site_id to create it scoped to a specific site instead.

        Parameters
        ----------
        - wlan_name: SSID / profile name for the new WLAN.
        - security_type: One of "open", "wpa2-personal", "wpa3-personal",
          "wpa2-enterprise", "wpa3-enterprise".
        - vlan: VLAN ID to assign this WLAN to. Omit to leave unset.
        - passphrase: Pre-shared key. Required for wpa2-personal / wpa3-personal.
        - hidden: Whether to hide the SSID from broadcast. Defaults to visible.
        - site_id: Site to scope this WLAN to. Omit to create an unscoped
          library profile instead. Call central_get_summary first to resolve site IDs.
        - device_function: Device function for site scoping (only used when
          site_id is set). Defaults to "CAMPUS_AP".
        - forward_mode: SSID forward mode. Defaults to "FORWARD_MODE_BRIDGE".

        """
        if security_type in ("wpa2-personal", "wpa3-personal") and not passphrase:
            return format_tool_error(
                "validating parameters",
                ValueError(f"passphrase is required for security_type '{security_type}'"),
            )

        lines = [
            f"Confirm CREATE WLAN '{wlan_name}'"
            + (f" scoped to site {site_id}" if site_id else " (unscoped library profile)"),
            f"  security={security_type}  vlan={vlan}  hidden={bool(hidden)}  forward_mode={forward_mode}",
            "\nAccept to proceed. Decline or cancel to abort.",
        ]
        error = await _confirm(ctx, lines)
        if error:
            return error

        payload = _build_wlan_payload(wlan_name, security_type, vlan, passphrase, hidden, forward_mode)
        params = _build_scope_params(site_id, device_function)
        async with api_context(ctx) as conn:
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
        return f"WLAN '{wlan_name}' created" + (f" scoped to site {site_id}." if site_id else " as a library profile.")

    @mcp.tool(annotations=DESTRUCTIVE)
    async def central_update_wlan(
        ctx: Context,
        wlan_name: str,
        security_type: SECURITY_TYPE | None = None,
        vlan: str | None = None,
        passphrase: str | None = None,
        hidden: bool | None = None,
        site_id: str | None = None,
        device_function: DEVICE_FUNCTION = "CAMPUS_AP",
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
        - site_id: Set only if the profile is LOCAL/site-scoped and you're
          updating it in that scope; omit for a SHARED/library profile.
        - device_function: Device function for site scoping (only used when
          site_id is set). Defaults to "CAMPUS_AP".

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

        lines = [
            f"Confirm UPDATE WLAN '{wlan_name}'"
            + (f" scoped to site {site_id}" if site_id else " (library profile)"),
            f"  changes: {display_updates}",
            "\nAccept to proceed. Decline or cancel to abort.",
        ]
        error = await _confirm(ctx, lines)
        if error:
            return error

        params = _build_scope_params(site_id, device_function)
        async with api_context(ctx) as conn:
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
        site_id: str | None = None,
        device_function: DEVICE_FUNCTION = "CAMPUS_AP",
    ) -> str:
        """Delete a WLAN SSID profile. Cannot be undone.

        Parameters
        ----------
        - wlan_name: Name of the WLAN profile to delete.
        - site_id: Set only if the profile is LOCAL/site-scoped; omit for a
          SHARED/library profile.
        - device_function: Device function for site scoping (only used when
          site_id is set). Defaults to "CAMPUS_AP".

        """
        lines = [
            f"Confirm DELETE WLAN '{wlan_name}'"
            + (f" scoped to site {site_id}" if site_id else " (library profile)"),
            "WARNING: This permanently removes the WLAN profile. Any clients connected to it will be disconnected.",
            "This action cannot be undone.",
            "\nAccept to proceed. Decline or cancel to abort.",
        ]
        error = await _confirm(ctx, lines)
        if error:
            return error

        params = _build_scope_params(site_id, device_function)
        async with api_context(ctx) as conn:
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
