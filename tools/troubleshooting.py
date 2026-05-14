import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from fastmcp.server.elicitation import AcceptedElicitation
from mcp import McpError
from pycentral.troubleshooting import Troubleshooting

from constants import (
    BOUNCE_PORTS_MAX,
    SHOW_COMMANDS_MAX,
    TROUBLESHOOTING_POLL_INTERVAL,
    TROUBLESHOOTING_POLL_MAX_ATTEMPTS,
)
from models import TroubleshootingResult
from tools import DESTRUCTIVE, DIAGNOSTIC
from utils.common import api_context, format_tool_error
from utils.troubleshooting import (
    NETWORK_TEST_DISPATCH,
    fetch_device_interfaces,
    format_port_speed,
    get_supported_families,
    resolve_family_from_serial,
    run_async_test,
    select_interfaces_for_ports,
    validate_show_commands_against_catalog,
)


def _strip_none(d: dict) -> dict:
    """Return a copy of d with None values removed."""
    return {k: v for k, v in d.items() if v is not None}


def _format_port_lines(
    matched: list[dict],
    family: str,
    bounce_type: str,
) -> list[str]:
    """Build per-port detail lines for elicitation messages and port-details output.

    Returns a list of strings (one or two lines per port depending on neighbour data).
    Each port line includes name, status, speed, and optional PoE/neighbour fields.

    Args:
        matched: Interface dicts from select_interfaces_for_ports.
        family: Device family string ('cx', 'aos-s', 'gateways').
        bounce_type: 'port' or 'poe' — controls whether PoE fields are included.

    """
    lines: list[str] = []
    for iface in matched:
        name = iface.get("name", "?")
        speed = format_port_speed(iface.get("speed"))
        if family == "gateways":
            oper = iface.get("operState", "unknown")
            health = iface.get("health", "unknown")
            line = f"  • {name}  status={oper}  speed={speed}  health={health}"
            lines.append(line)
        else:
            oper = iface.get("operStatus") or iface.get("status") or "unknown"
            desc = iface.get("description") or iface.get("alias") or ""
            line = f"  • {name}  status={oper}  speed={speed}"
            if desc:
                line += f"  desc={desc}"
            if bounce_type == "poe":
                poe_status = iface.get("poeStatus", "N/A")
                poe_class = iface.get("poeClass", "N/A")
                line += f"  poeStatus={poe_status}  poeClass={poe_class}"
            neighbour = iface.get("neighbour")
            if neighbour:
                n_type = iface.get("neighbourType")
                n_health = iface.get("neighbourHealth")
                if n_type and n_health:
                    neighbour_line = (
                        f"      connected: {neighbour} ({n_type}, health={n_health})"
                    )
                elif n_type:
                    neighbour_line = f"      connected: {neighbour} ({n_type})"
                else:
                    neighbour_line = f"      connected: {neighbour}"
                lines.append(line)
                lines.append(neighbour_line)
            else:
                lines.append(line)
    return lines


def _build_initiate_kwargs(
    test_type: str,
    family: str,
    destination: str,
    port: int | None,
    count: int | None,
    packet_size: int | None,
    name_server: str | None,
    vrf: str | None,
    source_interface: str | None,
    use_ipv6: bool | None,
) -> dict:
    """Build the initiate-function kwargs for a given test_type + device family."""
    if test_type == "ping":
        base = {
            "destination": destination,
            "packet_size": packet_size,
            "count": count,
            "include_raw_output": True,
        }
        if family == "aps":
            return _strip_none({**base, "source_interface": source_interface})
        if family == "cx":
            return _strip_none({**base, "use_ipv6": use_ipv6, "vrf_name": vrf})
        if family == "aos-s":
            return _strip_none({**base, "use_ipv6": use_ipv6})
        # gateways
        return _strip_none(
            {**base, "use_ipv6": use_ipv6, "source_interface": source_interface}
        )

    if test_type == "traceroute":
        base = {"destination": destination, "include_raw_output": True}
        if family == "aps":
            return _strip_none({**base, "source_interface": source_interface})
        if family == "cx":
            return _strip_none({**base, "use_ipv6": use_ipv6, "vrf_name": vrf})
        if family == "aos-s":
            return _strip_none({**base, "source_interface": source_interface})
        # gateways
        return _strip_none(base)

    if test_type == "http":
        # initiate_http_test takes device_type as a positional param
        return _strip_none(
            {
                "device_type": family,
                "destination": destination,
                "vrf": vrf,
                "source_interface": source_interface,
                "name_server": name_server,
            }
        )

    if test_type == "https":
        if family == "aps":
            return {"destination": destination}
        if family == "cx":
            return _strip_none(
                {
                    "destination": destination,
                    "vrf": vrf,
                    "source_interface": source_interface,
                    "name_server": name_server,
                }
            )
        # gateways
        return {"destination": destination}

    if test_type == "tcp":
        # initiate_tcp_test: host + port required; device_type as param
        kwargs: dict = {"device_type": family, "host": destination}
        if port is not None:
            kwargs["port"] = port
        return kwargs

    if test_type == "nslookup":
        # initiate_nslookup_test: host param, dns_server instead of name_server
        return _strip_none(
            {"host": destination, "device_type": family, "dns_server": name_server}
        )

    return {"destination": destination}


def register(mcp: FastMCP) -> None:
    """Register troubleshooting tools with the MCP server."""

    @mcp.tool(annotations=DIAGNOSTIC)
    async def central_run_network_test(
        ctx: Context,
        test_type: Literal["ping", "traceroute", "http", "https", "tcp", "nslookup"],
        serial_number: str,
        destination: str,
        port: int | None = None,
        count: int | None = None,
        packet_size: int | None = None,
        name_server: str | None = None,
        vrf: str | None = None,
        source_interface: str | None = None,
        use_ipv6: bool | None = None,
        max_attempts: int = TROUBLESHOOTING_POLL_MAX_ATTEMPTS,
        poll_interval: int = TROUBLESHOOTING_POLL_INTERVAL,
    ) -> TroubleshootingResult | str:
        """Run a live network diagnostic test against a Central-managed device.

        Resolves the device family from the serial number automatically, then dispatches
        the correct pycentral test method.  Results are polled until the task completes
        or the polling budget is exhausted.

        Supported test types and device families:
        - ping: ACCESS_POINT, SWITCH (CX and AOS-S), GATEWAY
        - traceroute: ACCESS_POINT, SWITCH (CX and AOS-S), GATEWAY
        - http: ACCESS_POINT, SWITCH (CX only), GATEWAY
        - https: ACCESS_POINT, SWITCH (CX only), GATEWAY
        - tcp: ACCESS_POINT only
        - nslookup: ACCESS_POINT only

        Parameters
        ----------
        - test_type: Type of diagnostic to run (ping, traceroute, http, https, tcp, nslookup).
        - serial_number: Serial number of the target device. Used to resolve device family.
        - destination: Target hostname or IP address for the test. For tcp/nslookup this is the host.
        - port: TCP port number. Required for tcp tests.
        - count: Number of probe packets. Applies to: ping.
        - packet_size: Probe packet size in bytes. Applies to: ping.
        - name_server: DNS server to use. Applies to: nslookup, http (as name_server), https (CX only).
        - vrf: VRF name for the test. Applies to: http, https (CX), ping (CX), traceroute (CX).
        - source_interface: Source interface override. Applies to: http, https (CX), ping (APs/gateways), traceroute (APs/AOS-S).
        - use_ipv6: Use IPv6 for the test. Applies to: ping (CX, AOS-S, gateways), traceroute (CX).

        The response includes a `raw_output` field with the human-readable test transcript for
        ping and traceroute tests. For other test types `raw_output` will be None.

        - max_attempts: Maximum polling iterations (default 5). Each iteration waits poll_interval seconds.
          One extra wait is performed if the task is still running after all attempts.
          Maximum effective wait: (max_attempts + 1) × poll_interval seconds.
        - poll_interval: Seconds between polling attempts (default 5).

        """
        if max_attempts < 1:
            return format_tool_error(
                "validating parameters", ValueError("max_attempts must be >= 1")
            )
        if poll_interval < 1:
            return format_tool_error(
                "validating parameters", ValueError("poll_interval must be >= 1")
            )
        if test_type == "tcp" and port is None:
            return format_tool_error(
                "validating parameters", ValueError("port is required for tcp tests")
            )

        async with api_context(ctx) as conn:
            try:
                family = await resolve_family_from_serial(conn, serial_number)
            except ValueError as e:
                return format_tool_error("resolving device family", e)

            dispatch_key = (test_type, family)
            if dispatch_key not in NETWORK_TEST_DISPATCH:
                supported = get_supported_families(test_type)
                return format_tool_error(
                    f"running {test_type} test",
                    ValueError(
                        f"Device '{serial_number}' (family: {family}) does not support {test_type} tests. "
                        f"Supported families: {', '.join(supported) or 'none'}."
                    ),
                )

            initiate_name, get_result_name = NETWORK_TEST_DISPATCH[dispatch_key]
            kwargs = _build_initiate_kwargs(
                test_type,
                family,
                destination,
                port,
                count,
                packet_size,
                name_server,
                vrf,
                source_interface,
                use_ipv6,
            )

            try:
                return await run_async_test(
                    conn=conn,
                    initiate_name=initiate_name,
                    get_result_name=get_result_name,
                    device_family=family,
                    serial_number=serial_number,
                    max_attempts=max_attempts,
                    poll_interval=poll_interval,
                    **kwargs,
                )
            except Exception as e:
                return format_tool_error(f"running {test_type} test", e)

    @mcp.tool(annotations=DIAGNOSTIC)
    async def central_run_show_commands(
        ctx: Context,
        serial_number: str,
        commands: list[str],
        max_attempts: int = TROUBLESHOOTING_POLL_MAX_ATTEMPTS,
        poll_interval: int = TROUBLESHOOTING_POLL_INTERVAL,
    ) -> TroubleshootingResult | str:
        """Run one or more show commands on a Central-managed device and return the output.

        This tool automatically validates the requested commands against the device's
        supported show-command catalog before executing them. If any command is not
        supported, an error is returned listing both the unmatched commands and the full
        catalog so you can select a valid alternative and retry.

        Each command must begin with 'show ' (case-insensitive). Maximum 5 commands per call.

        Workflow:
        1. Resolves device family from serial_number.
        2. Validates commands are non-empty and start with 'show '.
        3. Fetches the device's supported command catalog.
        4. Validates each command against the catalog; returns catalog on any mismatch.
        5. Runs the matched commands and polls for results.

        Parameters
        ----------
        - serial_number: Serial number of the target device.
        - commands: List of show commands to execute (e.g. ["show version", "show arp"]).
          Each must start with 'show ' (case-insensitive). Maximum 5 commands.
        - max_attempts: Maximum polling iterations (default 5).
        - poll_interval: Seconds between polling attempts (default 5).

        """
        if max_attempts < 1:
            return format_tool_error(
                "validating parameters", ValueError("max_attempts must be >= 1")
            )
        if poll_interval < 1:
            return format_tool_error(
                "validating parameters", ValueError("poll_interval must be >= 1")
            )
        if not commands:
            return format_tool_error(
                "validating parameters", ValueError("commands list must not be empty")
            )
        if len(commands) > SHOW_COMMANDS_MAX:
            return format_tool_error(
                "validating parameters",
                ValueError(f"maximum {SHOW_COMMANDS_MAX} commands per call"),
            )

        invalid = [c for c in commands if not c.strip().lower().startswith("show ")]
        if invalid:
            return format_tool_error(
                "validating parameters",
                ValueError(f"All commands must start with 'show '. Invalid: {invalid}"),
            )

        async with api_context(ctx) as conn:
            try:
                family = await resolve_family_from_serial(conn, serial_number)
            except ValueError as e:
                return format_tool_error("resolving device family", e)

            try:
                catalog = await asyncio.to_thread(
                    Troubleshooting.list_show_commands,
                    central_conn=conn,
                    device_type=family,
                    serial_number=serial_number,
                )
            except Exception as e:
                return format_tool_error("fetching supported show commands", e)

            unmatched = validate_show_commands_against_catalog(commands, catalog)
            if unmatched:
                return format_tool_error(
                    "validating show commands",
                    ValueError(
                        f"Unsupported commands: {unmatched}. "
                        f"Supported show commands for this device: {catalog}"
                    ),
                )

            try:
                return await run_async_test(
                    conn=conn,
                    initiate_name="initiate_show_commands",
                    get_result_name="get_show_commands_result",
                    device_family=family,
                    serial_number=serial_number,
                    max_attempts=max_attempts,
                    poll_interval=poll_interval,
                    device_type=family,
                    commands=commands,
                )
            except Exception as e:
                return format_tool_error("running show commands", e)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def central_bounce_port(
        ctx: Context,
        serial_number: str,
        ports: list[str],
        bounce_type: Literal["port", "poe"],
        max_attempts: int = TROUBLESHOOTING_POLL_MAX_ATTEMPTS,
        poll_interval: int = TROUBLESHOOTING_POLL_INTERVAL,
    ) -> TroubleshootingResult | str:
        """Bounce one or more switch/gateway ports or toggle PoE on ports after user confirmation.

        Fetches the live interface list for the device, validates the requested ports exist,
        then presents the port details (status, speed, PoE state) to the user for approval
        before executing the bounce. The bounce will NOT proceed unless the user accepts.

        Supported device families: CX switches, AOS-S switches, gateways.
        Not supported: access points.

        Parameters
        ----------
        - serial_number: Serial number of the target device.
        - ports: List of port names to bounce (e.g. ["1/1/1", "1/1/2"]). Maximum 5 ports.
        - bounce_type: "port" for a physical port bounce (disables then re-enables the port),
          "poe" to toggle Power over Ethernet (cuts and restores power to the connected device).
        - max_attempts: Maximum polling iterations (default 10).
        - poll_interval: Seconds between polling attempts (default 15).

        The user will be shown the current state of each requested port before the bounce
        is executed. Declining or cancelling the prompt aborts the operation with no change
        to the network.

        """
        if max_attempts < 1:
            return format_tool_error(
                "validating parameters", ValueError("max_attempts must be >= 1")
            )
        if poll_interval < 1:
            return format_tool_error(
                "validating parameters", ValueError("poll_interval must be >= 1")
            )
        if not ports:
            return format_tool_error(
                "validating parameters", ValueError("ports list must not be empty")
            )
        if len(ports) > BOUNCE_PORTS_MAX:
            return format_tool_error(
                "validating parameters",
                ValueError(f"maximum {BOUNCE_PORTS_MAX} ports per call"),
            )

        async with api_context(ctx) as conn:
            try:
                family = await resolve_family_from_serial(conn, serial_number)
            except ValueError as e:
                return format_tool_error("resolving device family", e)

            if family not in ("cx", "aos-s", "gateways"):
                return format_tool_error(
                    f"running {bounce_type} bounce",
                    ValueError(
                        f"Device '{serial_number}' (family: {family}) does not support port/PoE bounce. "
                        "Supported families: cx, aos-s, gateways."
                    ),
                )

            try:
                interfaces = await fetch_device_interfaces(conn, family, serial_number)
            except Exception as e:
                return format_tool_error("fetching interface list", e)

            matched, unknown = select_interfaces_for_ports(interfaces, ports)
            if unknown:
                return format_tool_error(
                    "validating ports",
                    ValueError(
                        f"Unknown ports: {unknown}. "
                        f"Available ports on this device: {[i.get('name') for i in interfaces]}"
                    ),
                )

            if bounce_type == "poe":
                warning = (
                    "WARNING: This will cut PoE power to the listed ports for several seconds. "
                    "Any powered device (AP, phone, camera) will lose power and reboot."
                )
            else:
                warning = (
                    "WARNING: This will drop the link on the listed ports for several seconds. "
                    "Any connected device or client will lose connectivity during that time."
                )
            lines = [
                f"Confirm {bounce_type.upper()} BOUNCE on device {serial_number} ({family})",
                warning,
                f"The following {len(matched)} port(s) will be affected:\n",
            ]
            lines.extend(_format_port_lines(matched, family, bounce_type))
            lines.append("\nAccept to proceed. Decline or cancel to abort.")
            approval_msg = "\n".join(lines)

            try:
                elicit_result = await ctx.elicit(approval_msg, response_type=None)
            except McpError:
                return format_tool_error(
                    f"running {bounce_type} bounce",
                    ValueError(
                        "This MCP client does not support elicitation. "
                        "Port bounce requires a client that declares elicitation capability."
                    ),
                )
            if not isinstance(elicit_result, AcceptedElicitation):
                return format_tool_error(
                    f"running {bounce_type} bounce",
                    ValueError("Bounce was declined or cancelled by the user."),
                )

            initiate_name = (
                "initiate_port_bounce_test"
                if bounce_type == "port"
                else "initiate_poe_bounce_test"
            )
            get_result_name = (
                "get_port_bounce_test_result"
                if bounce_type == "port"
                else "get_poe_bounce_test_result"
            )

            try:
                return await run_async_test(
                    conn=conn,
                    initiate_name=initiate_name,
                    get_result_name=get_result_name,
                    device_family=family,
                    serial_number=serial_number,
                    max_attempts=max_attempts,
                    poll_interval=poll_interval,
                    device_type=family,
                    ports=ports,
                )
            except Exception as e:
                return format_tool_error(f"running {bounce_type} bounce", e)

    @mcp.tool(annotations=DIAGNOSTIC)
    async def central_get_port_details(
        ctx: Context,
        serial_number: str,
        ports: list[str],
    ) -> str:
        """Return live port state for one or more switch or gateway ports.

        Fetches the current interface list for the device and returns status,
        speed, PoE state, and neighbour information for each requested port.
        Use this tool to assess port health or understand what is connected
        before deciding whether to take action (e.g. bouncing a port).

        Supported device families: CX switches, AOS-S switches, gateways.
        Not supported: access points.

        Parameters
        ----------
        - serial_number: Serial number of the target device.
        - ports: List of port names to inspect (e.g. ["1/1/1", "1/1/2"]).

        """
        async with api_context(ctx) as conn:
            try:
                family = await resolve_family_from_serial(conn, serial_number)
            except ValueError as e:
                return format_tool_error("resolving device family", e)

            if family not in ("cx", "aos-s", "gateways"):
                return format_tool_error(
                    "fetching port details",
                    ValueError(
                        f"Device '{serial_number}' (family: {family}) does not support port inspection. "
                        "Supported families: cx, aos-s, gateways."
                    ),
                )

            try:
                interfaces = await fetch_device_interfaces(conn, family, serial_number)
            except Exception as e:
                return format_tool_error("fetching interface list", e)

            matched, unknown = select_interfaces_for_ports(interfaces, ports)
            if unknown:
                return format_tool_error(
                    "fetching port details",
                    ValueError(
                        f"Unknown ports: {unknown}. "
                        f"Available ports on this device: {[i.get('name') for i in interfaces]}"
                    ),
                )

            lines = [f"Port details for device {serial_number} ({family}):\n"]
            lines.extend(_format_port_lines(matched, family, "port"))
            return "\n".join(lines)
