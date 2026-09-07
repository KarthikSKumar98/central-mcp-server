import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
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
from utils.common import api_context
from utils.envelope import raise_central_error
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


_NETWORK_TEST_ALLOWED_ARGS: dict[str, dict[str, frozenset[str]]] = {
    "ping": {
        "aps": frozenset({"count", "packet_size", "source_interface"}),
        "cx": frozenset({"count", "packet_size", "use_ipv6", "vrf"}),
        "aos-s": frozenset({"count", "packet_size", "use_ipv6"}),
        "gateways": frozenset({"count", "packet_size", "source_interface", "use_ipv6"}),
    },
    "traceroute": {
        "aps": frozenset({"source_interface"}),
        "cx": frozenset({"use_ipv6", "vrf"}),
        "aos-s": frozenset({"source_interface"}),
        "gateways": frozenset(),
    },
    "http": {
        "aps": frozenset({"name_server", "source_interface", "vrf"}),
        "cx": frozenset({"name_server", "source_interface", "vrf"}),
        "gateways": frozenset({"name_server", "source_interface", "vrf"}),
    },
    "https": {
        "aps": frozenset(),
        "cx": frozenset({"name_server", "source_interface", "vrf"}),
        "gateways": frozenset(),
    },
    "tcp": {
        "aps": frozenset({"port"}),
    },
    "nslookup": {
        "aps": frozenset({"name_server"}),
    },
}


def _validate_network_test_args(
    test_type: str,
    provided_args: dict[str, object | None],
    *,
    family: str | None = None,
) -> None:
    """Reject optional arguments unused by the selected test and device family."""
    allowed_by_family = _NETWORK_TEST_ALLOWED_ARGS[test_type]
    allowed = (
        allowed_by_family[family]
        if family is not None
        else frozenset().union(*allowed_by_family.values())
    )
    for argument, value in provided_args.items():
        if value is None or argument in allowed:
            continue
        family_detail = f" on device family '{family}'" if family is not None else ""
        raise ValueError(
            f"Argument '{argument}' is not supported for test_type "
            f"'{test_type}'{family_detail}."
        )


def _format_port_lines(
    matched: list[dict],
    family: str,
    include_poe: bool,
) -> list[str]:
    """Build per-port detail lines for elicitation messages and port-details output.

    Returns a list of strings (one or two lines per port depending on neighbour data).
    Each port line includes name, status, speed, and optional PoE/neighbour fields.

    Args:
        matched: Interface dicts from select_interfaces_for_ports.
        family: Device family string ('cx', 'aos-s', 'gateways').
        include_poe: Whether to append poeStatus/poeClass fields. Set True for PoE
            bounce confirmation and for general port-detail inspection. Set False for
            physical port bounce confirmation where PoE context is not relevant.

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
            if include_poe:
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


async def _substitute_aoss_port_placeholders(
    conn: object,
    family: str,
    serial_number: str,
    commands: list[str],
) -> list[str]:
    """Replace AOS-S catalog ``{{port}}`` tokens with a live interface name."""
    if family != "aos-s" or not any("{{port}}" in command for command in commands):
        return commands

    interfaces = await fetch_device_interfaces(conn, family, serial_number)
    port_name = next(
        (str(interface["name"]) for interface in interfaces if interface.get("name")),
        None,
    )
    if port_name is None:
        raise ValueError(
            "AOS-S show-command templates containing '{{port}}' require at least "
            "one reported interface."
        )
    return [command.replace("{{port}}", port_name) for command in commands]


async def _run_network_test_impl(
    ctx: Context,
    test_type: str,
    serial_number: str,
    destination: str,
    port: int | None,
    count: int | None,
    packet_size: int | None,
    name_server: str | None,
    vrf: str | None,
    source_interface: str | None,
    use_ipv6: bool | None,
    max_attempts: int,
    poll_interval: int,
) -> TroubleshootingResult:
    """Execute a network test behind the registered tool's error boundary."""
    if max_attempts < 1:
        raise_central_error(
            ValueError("max_attempts must be >= 1"), "validating parameters"
        )
    if poll_interval < 1:
        raise_central_error(
            ValueError("poll_interval must be >= 1"), "validating parameters"
        )
    if test_type == "tcp" and port is None:
        raise_central_error(
            ValueError("port is required for tcp tests"), "validating parameters"
        )

    optional_args = {
        "port": port,
        "count": count,
        "packet_size": packet_size,
        "name_server": name_server,
        "vrf": vrf,
        "source_interface": source_interface,
        "use_ipv6": use_ipv6,
    }
    try:
        _validate_network_test_args(test_type, optional_args)
    except ValueError as exc:
        raise_central_error(exc, "validating parameters")

    async with api_context(ctx) as conn:
        try:
            family, effective_serial = await resolve_family_from_serial(
                conn, serial_number
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "resolving device family")

        dispatch_key = (test_type, family)
        if dispatch_key not in NETWORK_TEST_DISPATCH:
            supported = get_supported_families(test_type)
            raise_central_error(
                ValueError(
                    f"Device '{serial_number}' (family: {family}) does not support "
                    f"{test_type} tests. Supported families: "
                    f"{', '.join(supported) or 'none'}."
                ),
                f"running {test_type} test",
            )

        try:
            _validate_network_test_args(
                test_type,
                optional_args,
                family=family,
            )
        except ValueError as exc:
            raise_central_error(exc, "validating parameters")

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
                serial_number=effective_serial,
                max_attempts=max_attempts,
                poll_interval=poll_interval,
                **kwargs,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, f"running {test_type} test")


async def _run_show_commands_impl(
    ctx: Context,
    serial_number: str,
    commands: list[str],
    max_attempts: int,
    poll_interval: int,
) -> TroubleshootingResult:
    """Execute show commands behind the registered tool's error boundary."""
    if max_attempts < 1:
        raise_central_error(
            ValueError("max_attempts must be >= 1"), "validating parameters"
        )
    if poll_interval < 1:
        raise_central_error(
            ValueError("poll_interval must be >= 1"), "validating parameters"
        )
    if not commands:
        raise_central_error(
            ValueError("commands list must not be empty"), "validating parameters"
        )
    if len(commands) > SHOW_COMMANDS_MAX:
        raise_central_error(
            ValueError(f"maximum {SHOW_COMMANDS_MAX} commands per call"),
            "validating parameters",
        )

    invalid = [c for c in commands if not c.strip().lower().startswith("show ")]
    if invalid:
        raise_central_error(
            ValueError(f"All commands must start with 'show '. Invalid: {invalid}"),
            "validating parameters",
        )

    async with api_context(ctx) as conn:
        try:
            family, effective_serial = await resolve_family_from_serial(
                conn, serial_number
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "resolving device family")

        try:
            catalog = await asyncio.to_thread(
                Troubleshooting.list_show_commands,
                central_conn=conn,
                device_type=family,
                serial_number=effective_serial,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "fetching supported show commands")

        unmatched = validate_show_commands_against_catalog(commands, catalog)
        if unmatched:
            raise_central_error(
                ValueError(
                    f"Unsupported commands: {unmatched}. "
                    f"Supported show commands for this device: {catalog}"
                ),
                "validating show commands",
            )

        try:
            execution_commands = await _substitute_aoss_port_placeholders(
                conn,
                family,
                effective_serial,
                commands,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "preparing show commands")

        try:
            return await run_async_test(
                conn=conn,
                initiate_name="initiate_show_commands",
                get_result_name="get_show_commands_result",
                device_family=family,
                serial_number=effective_serial,
                max_attempts=max_attempts,
                poll_interval=poll_interval,
                device_type=family,
                commands=execution_commands,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "running show commands")


async def _bounce_port_impl(
    ctx: Context,
    serial_number: str,
    ports: list[str],
    bounce_type: str,
    max_attempts: int,
    poll_interval: int,
) -> TroubleshootingResult:
    """Execute a port bounce behind the registered tool's error boundary."""
    if max_attempts < 1:
        raise_central_error(
            ValueError("max_attempts must be >= 1"), "validating parameters"
        )
    if poll_interval < 1:
        raise_central_error(
            ValueError("poll_interval must be >= 1"), "validating parameters"
        )
    if not ports:
        raise_central_error(
            ValueError("ports list must not be empty"), "validating parameters"
        )
    if len(ports) > BOUNCE_PORTS_MAX:
        raise_central_error(
            ValueError(f"maximum {BOUNCE_PORTS_MAX} ports per call"),
            "validating parameters",
        )

    async with api_context(ctx) as conn:
        try:
            family, effective_serial = await resolve_family_from_serial(
                conn, serial_number
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "resolving device family")

        if family not in ("cx", "aos-s", "gateways"):
            raise_central_error(
                ValueError(
                    f"Device '{serial_number}' (family: {family}) does not support "
                    "port/PoE bounce. Supported families: cx, aos-s, gateways."
                ),
                f"running {bounce_type} bounce",
            )

        try:
            interfaces = await fetch_device_interfaces(conn, family, effective_serial)
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "fetching interface list")

        matched, unknown = select_interfaces_for_ports(interfaces, ports)
        if unknown:
            raise_central_error(
                ValueError(
                    f"Unknown ports: {unknown}. "
                    f"Available ports on this device: "
                    f"{[i.get('name') for i in interfaces]}"
                ),
                "validating ports",
            )

        if bounce_type == "poe":
            warning = (
                "WARNING: This will cut PoE power to the listed ports for several "
                "seconds. Any powered device (AP, phone, camera) will lose power "
                "and reboot."
            )
        else:
            warning = (
                "WARNING: This will drop the link on the listed ports for several "
                "seconds. Any connected device or client will lose connectivity "
                "during that time."
            )
        lines = [
            f"Confirm {bounce_type.upper()} BOUNCE on device "
            f"{serial_number} ({family})",
            warning,
            f"The following {len(matched)} port(s) will be affected:\n",
        ]
        lines.extend(
            _format_port_lines(
                matched,
                family,
                include_poe=(bounce_type == "poe"),
            )
        )
        lines.append("\nAccept to proceed. Decline or cancel to abort.")
        approval_msg = "\n".join(lines)

        elicit_result = await ctx.elicit(approval_msg, response_type=None)
        if not isinstance(elicit_result, AcceptedElicitation):
            raise_central_error(
                ValueError("Bounce was declined or cancelled by the user."),
                f"running {bounce_type} bounce",
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
                serial_number=effective_serial,
                max_attempts=max_attempts,
                poll_interval=poll_interval,
                device_type=family,
                ports=ports,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, f"running {bounce_type} bounce")


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
    ) -> TroubleshootingResult:
        """Run a live network diagnostic against a Central-managed device.

        Use for ping, traceroute, HTTP(S), TCP, or DNS checks after identifying a device.
        Cross-field rules: TCP requires port; optional probe fields apply only to supported test/family combinations; polling values must be positive.
        Returns one TroubleshootingResult with the resolved family and final task output.
        """
        try:
            return await _run_network_test_impl(
                ctx,
                test_type,
                serial_number,
                destination,
                port,
                count,
                packet_size,
                name_server,
                vrf,
                source_interface,
                use_ipv6,
                max_attempts,
                poll_interval,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, f"running {test_type} test")

    @mcp.tool(annotations=DIAGNOSTIC)
    async def central_run_show_commands(
        ctx: Context,
        serial_number: str,
        commands: list[str],
        max_attempts: int = TROUBLESHOOTING_POLL_MAX_ATTEMPTS,
        poll_interval: int = TROUBLESHOOTING_POLL_INTERVAL,
    ) -> TroubleshootingResult:
        """Run catalog-supported show commands on a Central-managed device.

        Use for read-only CLI diagnostics after selecting commands from the device catalog.
        Cross-field rules: commands must be non-empty, start with 'show ', stay within the call cap, and AOS-S ``{{port}}`` templates use the first live interface.
        Returns one TroubleshootingResult containing the command task output.
        """
        try:
            return await _run_show_commands_impl(
                ctx,
                serial_number,
                commands,
                max_attempts,
                poll_interval,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, "running show commands")

    @mcp.tool(annotations=DESTRUCTIVE)
    async def central_bounce_port(
        ctx: Context,
        serial_number: str,
        ports: list[str],
        bounce_type: Literal["port", "poe"],
        max_attempts: int = TROUBLESHOOTING_POLL_MAX_ATTEMPTS,
        poll_interval: int = TROUBLESHOOTING_POLL_INTERVAL,
    ) -> TroubleshootingResult:
        """Bounce switch/gateway links or PoE after explicit user confirmation.

        Use only when a verified port needs a disruptive reset and the client supports elicitation.
        Cross-field rules: ports must exist on CX, AOS-S, or gateway devices, stay within the call cap, and polling values must be positive.
        Returns one TroubleshootingResult for the confirmed bounce task; decline or cancellation is an error with no network change.
        """
        try:
            return await _bounce_port_impl(
                ctx,
                serial_number,
                ports,
                bounce_type,
                max_attempts,
                poll_interval,
            )
        except (ToolError, McpError):
            raise
        except Exception as exc:
            raise_central_error(exc, f"running {bounce_type} bounce")

    # @mcp.tool(annotations=DIAGNOSTIC)
    # async def central_get_port_details(
    #     ctx: Context,
    #     serial_number: str,
    #     ports: list[str],
    # ) -> str:
    #     """Return live port state for one or more switch or gateway ports.

    #     Fetches the current interface list for the device and returns status,
    #     speed, neighbour information, and PoE state (poeStatus/poeClass) for each
    #     requested port when the interface reports it.
    #     Use this tool to assess port health or understand what is connected
    #     before deciding whether to take action (e.g. bouncing a port).

    #     Supported device families: CX switches, AOS-S switches, gateways.
    #     Not supported: access points.

    #     Parameters
    #     ----------
    #     - serial_number: Serial number of the target device.
    #     - ports: List of port names to inspect (e.g. ["1/1/1", "1/1/2"]).

    #     """
    #     async with api_context(ctx) as conn:
    #         try:
    #             family = await resolve_family_from_serial(conn, serial_number)
    #         except ValueError as e:
    #             raise_central_error(e, "resolving device family")

    #         if family not in ("cx", "aos-s", "gateways"):
    #             raise_central_error(
    #                 ValueError(
    #                     f"Device '{serial_number}' (family: {family}) does not support port inspection. "
    #                     "Supported families: cx, aos-s, gateways."
    #                 ),
    #                 "fetching port details",
    #             )

    #         try:
    #             interfaces = await fetch_device_interfaces(conn, family, serial_number)
    #         except Exception as e:
    #             raise_central_error(e, "fetching interface list")

    #         matched, unknown = select_interfaces_for_ports(interfaces, ports)
    #         if unknown:
    #             raise_central_error(
    #                 ValueError(
    #                     f"Unknown ports: {unknown}. "
    #                     f"Available ports on this device: {[i.get('name') for i in interfaces]}"
    #                 ),
    #                 "fetching port details",
    #             )

    #         lines = [f"Port details for device {serial_number} ({family}):\n"]
    #         lines.extend(_format_port_lines(matched, family, include_poe=True))
    #         return "\n".join(lines)
