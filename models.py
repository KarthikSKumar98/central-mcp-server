import ast as _ast
from enum import Enum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema


class ConciseProjectable(BaseModel):
    """Keep projected fields typed but optional in serialized output schemas."""

    concise_omit: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        schema = handler(core_schema)
        if required := schema.get("required"):
            schema["required"] = [
                name for name in required if name not in cls.concise_omit
            ]
        return schema


class EnvelopeMeta(BaseModel):
    """Shared response accounting for Central tool envelopes."""

    returned: int = Field(description="Number of items returned in this envelope.")
    total_available: int | None = Field(
        default=None,
        description="Number of items available before the response ceiling was applied.",
    )
    sampled: bool = Field(
        default=False,
        description="Whether the returned items are a bounded sample of a larger series.",
    )
    response_format: Literal["concise", "detailed"] = Field(
        default="concise",
        description="Response projection applied to envelope items.",
    )
    omitted_fields: list[str] | None = Field(
        default=None,
        description="Item fields suppressed by the concise projection.",
    )


class CentralEnvelope(BaseModel):
    """Base response envelope subclassed by Central tools."""

    items: list[Any] = Field(description="Typed records returned by the Central tool.")
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next upstream page, when one is available.",
    )
    truncated: bool = Field(
        default=False,
        description="Whether records were omitted because a response ceiling was reached.",
    )
    total: int | None = Field(
        default=None,
        description="Total record count reported by the upstream API, when available.",
    )
    meta: EnvelopeMeta = Field(description="Shared response-size accounting metadata.")

    @model_serializer(mode="wrap")
    def serialize_response_format(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ):
        """Apply an item's concise projection after normal typed serialization."""
        data = handler(self)
        meta = data["meta"]
        if meta.get("response_format") == "detailed":
            meta.pop("omitted_fields", None)
            return data

        omitted: set[str] = set()
        for item, serialized in zip(self.items, data["items"], strict=True):
            for field in getattr(item, "concise_omit", ()):
                if field in serialized:
                    serialized.pop(field)
                    omitted.add(field)
        if omitted:
            meta["omitted_fields"] = sorted(omitted)
        else:
            meta.pop("omitted_fields", None)
        return data


class CentralError(BaseModel):
    """Structured error contract shared by Central tools."""

    code: Literal[
        "rate_limited",
        "upstream_timeout",
        "upstream_server_error",
        "upstream_request_error",
        "timeout",
        "connection_error",
        "validation_error",
        "unexpected_error",
    ] = Field(description="Stable machine-readable error category.")
    message: str = Field(
        description="Human-readable description of the failed operation."
    )
    retryable: bool = Field(
        description="Whether retrying the operation may succeed without changing the request."
    )
    suggestion: str | None = Field(
        default=None,
        description="Actionable guidance for correcting or retrying the operation.",
    )


class SourceType(str, Enum):
    ACCESS_POINT = "Access Point"
    SWITCH = "Switch"
    GATEWAY = "Gateway"
    WIRELESS_CLIENT = "Wireless Client"
    WIRED_CLIENT = "Wired Client"
    BRIDGE = "Bridge"


class SiteMetrics(BaseModel):
    """Standardized site metrics structure."""

    health: dict[str, Any] = Field(
        default_factory=dict,
        description="Health score distribution: Poor/Fair/Good percentages plus a Summary score (0–100, weighted average where Good=1, Fair=0.5, Poor=0).",
    )
    devices: dict[str, Any] = Field(
        default_factory=dict,
        description="Device counts for the site. Contains 'Summary' (Poor/Fair/Good/Total) and optional 'Details' broken down by device type (Access Points, Switches, Gateways, Bridges).",
    )
    clients: dict[str, Any] = Field(
        default_factory=dict,
        description="Client counts for the site. Contains 'Summary' (Poor/Fair/Good/Total) and optional 'Details' broken down by medium (Wired, Wireless).",
    )
    alerts: dict[str, Any] | int = Field(
        default_factory=dict,
        description="Alert counts for the site: Critical (int) and Total (int).",
    )


class SiteData(ConciseProjectable):
    """Standardized site data structure."""

    concise_omit: ClassVar[frozenset[str]] = frozenset({"location"})

    site_id: str = Field(
        description="Unique identifier for the site in Central. Used to reference the site in other API calls."
    )
    name: str = Field(description="Display name of the site.")
    location: dict = Field(description="Geographic coordinates: lat and lng.")
    metrics: SiteMetrics = Field(
        description="Site performance metrics: health, devices, clients, alerts."
    )


class SiteSummary(ConciseProjectable):
    """Lightweight site overview used by the summary view."""

    concise_omit: ClassVar[frozenset[str]] = frozenset()

    name: str = Field(description="Display name of the site.")
    site_id: str | None = Field(
        default=None,
        description="Unique identifier for the site in Central.",
    )
    health: int | None = Field(
        default=None,
        description="Weighted site health score, or null when health is unavailable.",
    )
    total_devices: int = Field(description="Total devices assigned to the site.")
    total_clients: int = Field(
        description="Total clients currently counted at the site."
    )
    critical_alerts: int = Field(description="Critical alerts at the site.")
    total_alerts: int = Field(description="All alerts at the site.")


class SiteEnvelope(CentralEnvelope):
    """Typed response envelope for detailed and summary site views."""

    items: list[SiteData | SiteSummary] = Field(
        description="Detailed site records or compact site summaries."
    )


class Device(ConciseProjectable):
    """Device inventory data structure (duplicates removed)."""

    concise_omit: ClassVar[frozenset[str]] = frozenset(
        {
            "part_number",
            "function",
            "is_provisioned",
            "role",
            "deployment",
            "tier",
            "firmware_version",
            "device_group_name",
            "scope_id",
            "ipv4",
            "stack_id",
        }
    )

    # Primary identifiers
    serial_number: str = Field(
        description="Unique serial number. The most reliable way to identify and reference a device in Central."
    )
    mac_address: str = Field(description="MAC address of the device.")

    # Device information
    device_type: str = Field(
        description="Category of device: ACCESS_POINT, SWITCH, or GATEWAY."
    )
    model: str = Field(description="Device model number (e.g., AP-735-RWF1).")
    part_number: str = Field(description="Manufacturer part number.")
    name: str = Field(
        description="Display name of the device. Configurable in Central."
    )
    function: str | None = Field(
        description="Device function classification defining its role in the network."
    )

    # Status and configuration
    status: str | None = Field(
        description="Current operational status: ONLINE or OFFLINE."
    )
    is_provisioned: bool = Field(
        description="True if the device is configured and sending monitoring data to Central. False means it is not yet provisioned."
    )
    role: str | None = Field(description="Device role in the network.")
    deployment: str | None = Field(
        description="Deployment mode (e.g., Standalone, Stack)."
    )
    tier: str | None = Field(
        description="License tier (e.g., ADVANCED_AP). Indicates which Central subscription covers this device."
    )

    # Version information
    firmware_version: str | None = Field(
        description="Current firmware version installed on the device."
    )

    # Location and grouping
    site_id: str | None = Field(
        description="ID of the site where the device is located."
    )
    site_name: str | None = Field(
        description="Name of the site where the device is located."
    )
    device_group_name: str | None = Field(
        description="Name of the device group this device belongs to."
    )
    scope_id: str | None = Field(
        description="Scope identifier required for configuration actions on this device."
    )

    # Network information
    ipv4: str | None = Field(description="IPv4 address of the device.")

    # Additional metadata
    stack_id: str | None = Field(
        description="Stack identifier for stack-capable devices."
    )


class DeviceEnvelope(CentralEnvelope):
    """Typed response envelope for device inventory and exact lookup results."""

    items: list[Device] = Field(description="Central device inventory records.")


_REBOOT_REASON_MAP: dict[str, str] = {
    "UNKNOWN": "Unknown",
    "AP_RELOAD": "Reload",
    "USER_REBOOT": "User reboot",
    "WRITE_ERASE_REBOOT": "Write erase reboot",
    "WRITE_ERASE_ALL_REBOOT": "Write erase all reboot",
    "IMAGE_SYNC_FAILED": "Image sync failed",
    "IMAGE_SYNC_SUCCESSFUL": "Image sync successful",
    "IMAGE_UPGRADE": "Image upgrade successful",
    "IMAGE_DOWNLOAD_FAILURE": "Image download failure",
    "OUT_OF_MEMORY": "Reboot caused by out of memory",
    "DOWN_UPLINK": "Current uplink down, no useable uplink.",
    "CONDUCTOR_TO_LOCAL": "Conductor transitioned to local",
    "NETWORK_DISCONNECT_USB_RESET": "Internet connection lost, reset usb modem",
    "NETWORK_DISCONNECT": "Internet connection lost",
    "UNREACHABLE_GATEWAY": "Gateway unreachable",
    "FATAL_EXCEPTION": "Reboot caused by kernel panic: fatal exception",
    "FATAL_EXCEPTION_IN_INTERRUPT": "Reboot caused by kernel panic: fatal exception in interrupt",
    "SOFTLOCKUP": "Reboot caused by kernel panic: softlockup: hung tasks",
    "NTP_SYNC": "System clock is too far ahead of ntp sync result",
    "BAD_MESH_LINK": "Mesh link bad. Rebooting mesh point by sapd",
    "MESH_TO_PORTAL": "Mesh point transitioned to portal",
    "REBOOT_BY_AIRWAVE": "Reboot by Airwave",
    "AMP_COMMAND": "Amp",
    "VC_COMMAND": "VC",
    "REBOOTED_BY_CENTRAL": "Reboot by Central",
    "CLOUD_MANAGEMENT_COMMAND": "Cloud management",
    "CLI_COMMAND": "CLI",
    "CONDUCTOR_IP_FAILURE": "Failed to get conductor-ip",
    "NON_FIPS": "Non-fips --> fips",
    "FIPS": "Fips --> non-fips",
    "TOPOLOGY_CHANGE": "Rebooting AP due to topology change: hierarchy to flat",
    "AP_DISCONNECTED": "AP disconnected from Central",
    "VC_DISCONNECTED": "Virtual controller disconnected from Central",
    "COLD_HW_RESET": "AP reboot caused by cold hw reset(power loss)",
    "POWER_LOSS": "AP rebooted due to loss power",
    "THERMAL_MODE": "Reboot due to trigger the cooldown event",
    "OVERHEAT_EVENT": "Reboot due to trigger the overheat event",
    "PREEMPTED_BY_CONDUCTOR": "Preempted by provisioned conductor",
}


class AccessPoint(BaseModel):
    """Access point monitoring data structure."""

    model_config = ConfigDict(populate_by_name=True)

    serial_number: str = Field(
        validation_alias="serialNumber",
        description="Unique serial number of the access point.",
    )
    device_name: str | None = Field(
        default=None,
        validation_alias="deviceName",
        description="Name of the access point.",
    )
    mac_address: str | None = Field(
        default=None,
        validation_alias="macAddress",
        description="MAC address of the access point.",
    )
    site_id: str | None = Field(
        default=None,
        validation_alias="siteId",
        description="ID of the site where the AP is located.",
    )
    site_name: str | None = Field(
        default=None,
        validation_alias="siteName",
        description="Name of the site where the AP is located.",
    )
    status: Literal["ONLINE", "OFFLINE"] | None = Field(
        default=None, description="Current AP status (ONLINE or OFFLINE)."
    )
    model: str | None = Field(default=None, description="AP model number.")
    firmware_version: str | None = Field(
        default=None,
        validation_alias="firmwareVersion",
        description="Firmware version currently running on the AP.",
    )
    deployment: str | None = Field(
        default=None, description="Deployment mode of the AP."
    )
    cluster_id: str | None = Field(
        default=None,
        validation_alias="clusterId",
        description="ID of cluster associated with the AP.",
    )
    cluster_name: str | None = Field(
        default=None,
        validation_alias="clusterName",
        description="Name of cluster associated with the AP.",
    )
    part_number: str | None = Field(
        default=None,
        validation_alias="partNumber",
        description="Manufacturer part number of the AP.",
    )
    device_function: str | None = Field(
        default=None,
        validation_alias="deviceFunction",
        description="Device function classification of the AP. This is a user-defined role that determines the role of the AP in the network.",
    )
    role: str | None = Field(
        default=None,
        description="Role assigned to the AP within the cluster or network.",
    )
    ipv4: str | None = Field(default=None, description="IPv4 address of the AP.")
    ipv6: str | None = Field(default=None, description="IPv6 address of the AP.")
    last_seen_at: str | None = Field(
        default=None,
        validation_alias="lastSeenAt",
        description="Timestamp when the AP was last seen in monitoring.",
    )
    cpu_utilization: int | float | None = Field(
        default=None,
        validation_alias="cpuUtilization",
        description="Latest CPU utilization value reported for the AP.",
    )
    memory_utilization: int | float | None = Field(
        default=None,
        validation_alias="memoryUtilization",
        description="Latest memory utilization value reported for the AP.",
    )
    power_consumption: int | float | None = Field(
        default=None,
        validation_alias="powerConsumption",
        description="Latest AP power consumption value.",
    )
    client_count: int | None = Field(
        default=None,
        validation_alias="clientCount",
        description="Number of clients currently connected to the AP.",
    )
    last_reboot_reason: str | None = Field(
        default=None,
        validation_alias="lastRebootReason",
        description="Reason for the last AP reboot.",
    )
    public_ipv4: str | None = Field(
        default=None,
        validation_alias="publicIpv4",
        description="Public IPv4 address of the AP.",
    )

    @classmethod
    def from_api(cls, raw_ap: dict[str, Any]) -> "AccessPoint":
        """Normalize raw Central AP payloads into a sparse MCP-friendly shape."""
        normalized = dict(raw_ap)
        if normalized.get("status") == "ONLINE":
            normalized["lastSeenAt"] = None
        reason = normalized.get("lastRebootReason")
        if reason and reason in _REBOOT_REASON_MAP:
            normalized["lastRebootReason"] = _REBOOT_REASON_MAP[reason]
        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields during serialization to keep AP payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class AccessPointStatistics(BaseModel):
    """Time-series monitoring statistics for a single access point."""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: str = Field(description="RFC 3339 timestamp for the statistics sample.")
    cpu_utilization: int | float | None = Field(
        default=None,
        validation_alias="cpuUtilization",
        description="CPU utilization percentage reported for the AP at this sample time.",
    )
    memory_utilization: int | float | None = Field(
        default=None,
        validation_alias="memoryUtilization",
        description="Memory utilization percentage reported for the AP at this sample time.",
    )
    power_consumption: int | float | None = Field(
        default=None,
        validation_alias="powerConsumption",
        description="Power consumption reported for the AP at this sample time.",
    )


class WLAN(ConciseProjectable):
    """WLAN (wireless network) data structure."""

    concise_omit: ClassVar[frozenset[str]] = frozenset()

    model_config = ConfigDict(populate_by_name=True)

    wlan_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("wlan_name", "wlanName"),
        description="Name/SSID of the WLAN.",
    )
    security_level: str | None = Field(
        default=None,
        validation_alias=AliasChoices("security_level", "securityLevel"),
        description="Security level (e.g., Open, Personal, Enterprise).",
    )
    security: str | None = Field(
        default=None,
        description="Security protocol (e.g., WPA2, WPA3).",
    )
    band: str | None = Field(
        default=None,
        description="Wireless band (e.g., 2.4GHz, 5GHz, 6GHz).",
    )
    status: str | None = Field(default=None, description="WLAN operational status.")
    vlan: str | None = Field(default=None, description="VLAN assigned to this WLAN.")
    throughput: list["WLANThroughputSample"] | None = Field(
        default=None,
        description="Throughput samples included only when include contains 'throughput'.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Omit additive fields unless the caller requested them."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class WLANThroughputSample(BaseModel):
    """Standardized WLAN throughput time-series sample."""

    timestamp: str = Field(description="RFC 3339 timestamp for the throughput sample.")
    tx: int | float | None = Field(
        default=None,
        description="Transmitted (tx) throughput reported for the WLAN at this timestamp, in bits per second.",
    )
    rx: int | float | None = Field(
        default=None,
        description="Received (rx) throughput reported for the WLAN at this timestamp, in bits per second.",
    )


class WlanEnvelope(CentralEnvelope):
    """Typed response envelope for WLANs and optional throughput samples."""

    items: list[WLAN] = Field(description="Central WLAN configuration records.")


class APRadio(BaseModel):
    """Access point radio data structure.

    Models the union of embedded radios (from get_ap_details) and the richer
    dedicated get_ap_radios items.  All fields are optional so both payload
    shapes deserialise without errors.
    """

    model_config = ConfigDict(populate_by_name=True)

    radio_number: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("radio_number", "radioNumber"),
        description="Radio slot/index number.",
    )
    band: str | None = Field(
        default=None, description="Wireless band (e.g. 2.4GHz, 5GHz, 6GHz)."
    )
    band_range: str | None = Field(
        default=None,
        validation_alias=AliasChoices("band_range", "bandRange"),
        description="Band range descriptor.",
    )
    bandwidth: int | float | str | None = Field(
        default=None, description="Channel bandwidth (e.g. '20 MHz' or 20)."
    )
    channel: int | float | str | None = Field(
        default=None, description="Current operating channel."
    )
    channel_change_count: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("channel_change_count", "channelChangeCount"),
        description="Number of channel changes since last reset.",
    )
    channel_quality: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("channel_quality", "channelQuality"),
        description="Channel quality score (0–100).",
    )
    channel_utilization: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("channel_utilization", "channelUtilization"),
        description="Channel utilisation percentage.",
    )
    client_count: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("client_count", "clientCount"),
        description="Number of clients currently associated to this radio.",
    )
    drops: int | float | None = Field(default=None, description="Dropped frame count.")
    mac_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mac_address", "macAddress"),
        description="MAC address of this radio.",
    )
    mode: str | None = Field(default=None, description="Radio operating mode.")
    noise_floor: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("noise_floor", "noiseFloor"),
        description="Noise floor in dBm.",
    )
    non_wifi_interference: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("non_wifi_interference", "nonWifiInterference"),
        description="Non-Wi-Fi interference percentage.",
    )
    power: int | float | str | None = Field(
        default=None, description="Transmit power (e.g. '20 dBm' or 20)."
    )
    power_change_count: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("power_change_count", "powerChangeCount"),
        description="Number of transmit-power changes since last reset.",
    )
    radio_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("radio_type", "radioType"),
        description="Radio hardware type (e.g. 802.11ax).",
    )
    retries: int | float | None = Field(default=None, description="Retry frame count.")
    rx_utilization: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("rx_utilization", "rxUtilization"),
        description="Receive utilisation percentage.",
    )
    tx_utilization: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("tx_utilization", "txUtilization"),
        description="Transmit utilisation percentage.",
    )
    site_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("site_id", "siteId"),
        description="Site ID reported by the dedicated radio endpoint.",
    )
    spatial_stream: str | None = Field(
        default=None,
        validation_alias=AliasChoices("spatial_stream", "spatialStream"),
        description="Spatial stream configuration (e.g. '2x2:2').",
    )
    antenna: str | None = Field(default=None, description="Antenna type/model.")
    status: str | None = Field(default=None, description="Radio operational status.")
    id: str | None = Field(
        default=None, description="Unique radio resource ID (dedicated endpoint)."
    )
    type: str | None = Field(
        default=None, description="Resource type tag (dedicated endpoint)."
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "APRadio":
        """Normalise a raw radio dict from either embedded or dedicated payloads."""
        normalized: dict[str, Any] = dict(raw)
        # Embedded summary shape has radioStats: [{noiseFloor, channelUtilization}]
        radio_stats = normalized.pop("radioStats", None)
        if isinstance(radio_stats, list) and radio_stats:
            for key, value in radio_stats[0].items():
                normalized.setdefault(key, value)
        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep radio payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class APPort(BaseModel):
    """Access point port data structure.

    Models the union of embedded ports (from get_ap_details) and dedicated
    get_ap_ports items.  All fields are optional.
    """

    model_config = ConfigDict(populate_by_name=True)

    port_index: int | float | None = Field(
        default=None,
        validation_alias=AliasChoices("port_index", "portIndex"),
        description="Port index number.",
    )
    name: str | None = Field(default=None, description="Port name.")
    status: str | None = Field(default=None, description="Port operational status.")
    speed: int | float | str | None = Field(
        default=None,
        description="Port speed in Mbps or 'Auto'.",
    )
    duplex: str | None = Field(default=None, description="Duplex mode (Full, Half).")
    connector: str | None = Field(default=None, description="Physical connector type.")
    mac_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mac_address", "macAddress"),
        description="MAC address of the port.",
    )
    access_vlan: int | str | None = Field(
        default=None,
        validation_alias=AliasChoices("access_vlan", "accessVlan"),
        description="Access VLAN ID assigned to the port ('-' when unset).",
    )
    allowed_vlan: str | None = Field(
        default=None,
        validation_alias=AliasChoices("allowed_vlan", "allowedVlan"),
        description="Allowed VLANs on the port (trunk mode).",
    )
    native_vlan: int | str | None = Field(
        default=None,
        validation_alias=AliasChoices("native_vlan", "nativeVlan"),
        description="Native VLAN for the port ('-' when unset).",
    )
    vlan_mode: str | None = Field(
        default=None,
        validation_alias=AliasChoices("vlan_mode", "vlanMode"),
        description="VLAN mode (Access, Trunk).",
    )
    id: str | None = Field(
        default=None, description="Unique port resource ID (dedicated endpoint)."
    )
    type: str | None = Field(
        default=None, description="Resource type tag (dedicated endpoint)."
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "APPort":
        """Construct an APPort from a raw port dict."""
        return cls(**raw)

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep port payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class APDetail(AccessPoint):
    """Rich single-AP detail, as returned by get_ap_details.

    Subclasses AccessPoint and adds detail-only fields plus embedded
    radios, ports, and wlans.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Detail-only scalar fields
    uptime_in_millis: int | None = Field(
        default=None,
        validation_alias=AliasChoices("uptime_in_millis", "uptimeInMillis"),
        description="AP uptime in milliseconds.",
    )
    manufacturer: str | None = Field(
        default=None, description="AP hardware manufacturer."
    )
    mode: str | None = Field(
        default=None, description="Current operating mode of the AP."
    )
    mesh_role: str | None = Field(
        default=None,
        validation_alias=AliasChoices("mesh_role", "meshRole"),
        description="Mesh role (Portal, MeshPoint).",
    )
    default_gateway: str | None = Field(
        default=None,
        validation_alias=AliasChoices("default_gateway", "defaultGateway"),
        description="Default gateway IP address.",
    )
    subnet_mask: str | None = Field(
        default=None,
        validation_alias=AliasChoices("subnet_mask", "subnetMask"),
        description="Subnet mask of the AP's IP address.",
    )
    country_code: str | None = Field(
        default=None,
        validation_alias=AliasChoices("country_code", "countryCode"),
        description="Regulatory country code.",
    )
    current_uplink_in_use: str | None = Field(
        default=None,
        validation_alias=AliasChoices("current_uplink_in_use", "currentUplinkInUse"),
        description="Current active uplink interface.",
    )
    negotiated_power: int | float | str | None = Field(
        default=None,
        validation_alias=AliasChoices("negotiated_power", "negotiatedPower"),
        description="PoE negotiated power or PoE class (e.g. '802.3at').",
    )
    band_selection: str | None = Field(
        default=None,
        validation_alias=AliasChoices("band_selection", "bandSelection"),
        description="Band steering/selection mode.",
    )
    notes: str | None = Field(default=None, description="Operator notes for the AP.")

    # Embedded sub-entities
    radios: list[APRadio] | None = Field(
        default=None,
        description="List of radio interfaces on this AP.",
    )
    ports: list[APPort] | None = Field(
        default=None,
        description="List of wired ports on this AP.",
    )
    wlans: list[WLAN] | None = Field(
        default=None,
        description="List of WLANs served by this AP.",
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "APDetail":  # type: ignore[override]
        """Normalise a get_ap_details payload into an APDetail instance."""
        normalized: dict[str, Any] = dict(raw)

        # --- Inherited AccessPoint normalisations ---
        if normalized.get("status") == "ONLINE":
            normalized["lastSeenAt"] = None
        reason = normalized.get("lastRebootReason")
        if reason and reason in _REBOOT_REASON_MAP:
            normalized["lastRebootReason"] = _REBOOT_REASON_MAP[reason]

        # --- Flatten apStats: [{clientCount, cpuUtilization, memoryUtilization}] ---
        ap_stats = normalized.pop("apStats", None)
        if isinstance(ap_stats, list) and ap_stats:
            stats = ap_stats[0]
            normalized.setdefault("clientCount", stats.get("clientCount"))
            normalized.setdefault("cpuUtilization", stats.get("cpuUtilization"))
            normalized.setdefault("memoryUtilization", stats.get("memoryUtilization"))

        # --- Convert embedded sub-entities ---
        raw_radios = normalized.pop("radios", None)
        if isinstance(raw_radios, list):
            normalized["radios"] = [APRadio.from_api(r) for r in raw_radios]

        raw_ports = normalized.pop("ports", None)
        if isinstance(raw_ports, list):
            normalized["ports"] = [APPort.from_api(p) for p in raw_ports]

        raw_wlans = normalized.pop("wlans", None)
        if isinstance(raw_wlans, list):
            normalized["wlans"] = [WLAN(**w) for w in raw_wlans]

        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(  # type: ignore[override]
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep detail payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class TrendSample(ConciseProjectable):
    """Generic AP/radio/port trend sample with a dynamic metric value key.

    The metric value keys (e.g. ``cpu_utilization``, ``tx``, ``rx``,
    ``non_wifi_interference``) vary per metric type and are captured via
    ``extra="allow"``.  The sparse serializer drops any null extras.
    """

    concise_omit: ClassVar[frozenset[str]] = frozenset()

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    timestamp: str = Field(description="RFC 3339 timestamp for the trend sample.")

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields (including extras) to keep trend payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class DeviceTrendsEnvelope(CentralEnvelope):
    """Typed response envelope for device trend samples."""

    items: list[TrendSample] = Field(
        description="Bounded time-series samples for the selected device trend."
    )


class Client(ConciseProjectable):
    """Client device data structure."""

    concise_omit: ClassVar[frozenset[str]] = frozenset(
        {
            "ipv6",
            "hostname",
            "vendor",
            "manufacturer",
            "category",
            "function",
            "os",
            "capabilities",
            "last_seen_at",
            "tunnel_type",
            "tunnel_id",
            "wireless_band",
            "wireless_channel",
            "wireless_security",
            "key_management",
            "bssid",
            "radio_mac",
            "authentication",
            "role",
            "tags",
        }
    )

    # Primary identifiers
    mac: str | None = Field(description="MAC address of the client.")
    name: str | None = Field(description="Display name of the client.")
    ipv4: str | None = Field(description="IPv4 address of the client.")
    ipv6: str | None = Field(description="IPv6 address of the client.")
    hostname: str | None = Field(description="Hostname of the client.")

    # Client classification
    connection_type: str | None = Field(
        description="Client type (e.g., Wireless, Wired)."
    )
    vendor: str | None = Field(description="Vendor name of the client device.")
    manufacturer: str | None = Field(description="Manufacturer of the client device.")
    category: str | None = Field(description="Category classification of the client.")
    function: str | None = Field(
        description="Functional role of the client in the network."
    )
    os: str | None = Field(description="Operating system or model of the client.")
    capabilities: str | None = Field(description="Client capability flags.")

    # Status and health
    status: str | None = Field(description="Current connection status of the client.")

    # Connection information
    connected_device_type: str | None = Field(
        description="Type of the device this client is connected to."
    )
    connected_device_serial: str | None = Field(
        description="Serial number of the device this client is connected to."
    )
    connected_to: str | None = Field(
        description="Name or identifier of the connected device."
    )
    connected_at: str | None = Field(description="Timestamp when the client connected.")
    last_seen_at: str | None = Field(
        description="Timestamp when the client was last seen."
    )
    port: str | None = Field(
        default=None, description="Port on the connected device."
    )  # Wired only

    # Network configuration
    vlan_id: str | None = Field(description="VLAN ID assigned to the client.")
    tunnel_type: str | None = Field(description="Tunnel type if applicable.")
    tunnel_id: int | None = Field(description="Tunnel identifier.")

    # Wireless-specific fields (omitted for wired clients)
    wlan_name: str | None = Field(
        default=None,
        description="Name of the wireless network the client is connected to.",
    )  # Wireless only
    wireless_band: str | None = Field(
        default=None, description="Wireless band (e.g., 2.4GHz, 5GHz)."
    )  # Wireless only
    wireless_channel: str | None = Field(
        default=None, description="Wireless channel in use."
    )  # Wireless only
    wireless_security: str | None = Field(
        default=None, description="Wireless security protocol."
    )  # Wireless only
    key_management: str | None = Field(
        default=None, description="Key management method."
    )  # Wireless only
    bssid: str | None = Field(
        default=None,
        description="BSSID to which the client is connected on the device.",
    )  # Wireless only
    radio_mac: str | None = Field(
        default=None, description="MAC address of the radio serving this client."
    )  # Wireless only

    # Authentication
    user_name: str | None = Field(
        description="Authenticated username if 802.1X is in use."
    )
    authentication: str | None = Field(description="Authentication method used.")

    # Site information
    site_id: str | None = Field(
        description="ID of the site where the client is located."
    )
    site_name: str | None = Field(
        description="Name of the site where the client is located."
    )

    # Additional metadata
    role: str | None = Field(
        description="Role assigned to the client (e.g., from policy)."
    )
    tags: str | None = Field(description="Tags associated with the client.")


class ClientEnvelope(CentralEnvelope):
    """Typed response envelope for client lists and exact MAC lookups."""

    items: list[Client] = Field(description="Central wired or wireless client records.")


class Alert(ConciseProjectable):
    concise_omit: ClassVar[frozenset[str]] = frozenset(
        {"cleared_reason", "updated_at", "updated_by"}
    )

    summary: str = Field(description="Short summary of the alert.")
    cleared_reason: str | None = Field(
        description="Reason the alert was cleared, if applicable."
    )
    created_at: str = Field(
        description="Timestamp when the alert was created (RFC 3339)."
    )
    priority: str = Field(description="Priority level of the alert.")
    updated_at: str | None = Field(
        description="Timestamp of the last update to the alert."
    )
    device_type: str | None = Field(
        description="Type of device that triggered the alert."
    )
    updated_by: str | None = Field(
        description="User or system that last updated the alert."
    )
    name: str | None = Field(description="Name/title of the alert.")
    status: str | None = Field(
        description="Current status of the alert (e.g., ACTIVE, CLEARED)."
    )
    category: str | None = Field(description="Alert category.")
    severity: str | None = Field(
        description="Severity level (e.g., CRITICAL, MAJOR, MINOR)."
    )


class AlertEnvelope(CentralEnvelope):
    """Typed response envelope for alert records."""

    items: list[Alert] = Field(description="Central alert records.")


class EventNameCount(ConciseProjectable):
    concise_omit: ClassVar[frozenset[str]] = frozenset()

    event_id: str = Field(description="Event type identifier.")
    event_name: str = Field(description="Human-readable event name.")
    count: int = Field(description="Number of occurrences.")


class EventSourceTypeCount(ConciseProjectable):
    concise_omit: ClassVar[frozenset[str]] = frozenset()

    source_type: str = Field(description="Source type (e.g. 'Wireless Client').")
    count: int = Field(description="Number of events from this source type.")


class EventCategoryCount(ConciseProjectable):
    concise_omit: ClassVar[frozenset[str]] = frozenset()

    category: str = Field(description="Event category (e.g. 'Clients').")
    count: int = Field(description="Number of events in this category.")


class EventFilters(ConciseProjectable):
    concise_omit: ClassVar[frozenset[str]] = frozenset()

    total: int = Field(description="Total event count (sum of all categories).")
    event_names: list[EventNameCount] = Field(
        description="Per-event-type breakdown, sorted by count descending."
    )
    source_types: list[EventSourceTypeCount] = Field(
        description="Breakdown by source type."
    )
    categories: list[EventCategoryCount] = Field(
        description="Breakdown by event category."
    )


class CompactEventName(BaseModel):
    event_id: str = Field(description="Event type identifier for filtering.")
    event_name: str = Field(description="Human-readable event name.")


class CompactEventFilters(ConciseProjectable):
    concise_omit: ClassVar[frozenset[str]] = frozenset()

    total: int = Field(description="Total event count (sum of all categories).")
    event_names: list[CompactEventName] = Field(
        description="All event id/name pairs sorted by descending count."
    )
    source_types: list[str] = Field(
        description="All source types sorted by descending count."
    )
    categories: list[str] = Field(
        description="All categories sorted by descending count."
    )


class EventFacetsEnvelope(CentralEnvelope):
    """Typed response envelope for full or compact event facet aggregations."""

    items: list[EventFilters | CompactEventFilters] = Field(
        description="Full or compact aggregate event facets for the selected context."
    )


class EventAttribute(BaseModel):
    """One additional label/value attribute for an event record."""

    label: str = Field(description="Display label for the event attribute.")
    value: str = Field(description="Value reported for the event attribute.")


class Event(ConciseProjectable):
    concise_omit: ClassVar[frozenset[str]] = frozenset(
        {
            "client_mac_address",
            "device_mac_address",
            "stack_id",
            "bssid",
            "reason",
            "attributes",
        }
    )

    model_config = ConfigDict(populate_by_name=True)
    event_id: str = Field(alias="eventId", description="The event type identifier.")
    event_identifier: str = Field(
        alias="eventIdentifier", description="Unique identifier for the event."
    )
    serial_number: str = Field(
        alias="serialNumber",
        description="Serial number of the device that generated the event.",
    )
    time_at: str = Field(
        alias="timeAt",
        description="Timestamp when the event occurred at the source (RFC 3339 with milliseconds).",
    )
    event_name: str = Field(alias="eventName", description="Name of the event.")
    category: str = Field(description="Event category.")
    source_type: SourceType = Field(
        alias="sourceType", description="Type of source that generated the event."
    )
    source_name: str = Field(
        alias="sourceName",
        description="Name of the device or client that generated the event.",
    )
    description: str = Field(description="Detailed description of the event.")
    client_mac_address: str | None = Field(
        alias="clientMacAddress",
        description="MAC address of the client involved in the event.",
    )
    device_mac_address: str | None = Field(
        alias="deviceMacAddress",
        description="MAC address of the device that generated the event.",
    )
    stack_id: str | None = Field(
        alias="stackId", description="Stack identifier for stack-capable devices."
    )
    bssid: str | None = Field(
        description="Basic Service Set Identifier for wireless events."
    )
    reason: str | None = Field(description="Reason or cause of the event.")
    severity: str | None = Field(description="Severity level of the event.")
    attributes: list[EventAttribute] | None = Field(
        default=None,
        validation_alias=AliasChoices("attributes", "eventExtraAttributes"),
        description=(
            "Additional label/value details populated when include='attributes'."
        ),
    )


class EventEnvelope(CentralEnvelope):
    """Typed response envelope for event records."""

    items: list[Event] = Field(description="Central event records.")


class TroubleshootingResult(BaseModel):
    """Result of an async troubleshooting task run against a Central-managed device."""

    status: str = Field(
        description="Final task status returned by Central (e.g. COMPLETED, FAILED, RUNNING)."
    )
    device_type: str = Field(
        description="Resolved device family used to dispatch the test (aps, cx, aoss, or gateways)."
    )
    serial_number: str = Field(description="Serial number of the device under test.")
    raw_output: str | None = Field(
        default=None,
        description="CLI Raw output for Troubleshooting Test (populated for ping and traceroute).",
    )
    output: dict[str, Any] | str | None = Field(
        default=None,
        description="Parsed output payload from Central. Structure varies by test type.",
    )
    error: str | None = Field(
        default=None,
        description="Error detail returned by Central if the task failed, or None on success.",
    )


# --- Switch monitoring (a20) ---


class SwitchTrend(BaseModel):
    """Inline switch trend snapshot embedded in get_all_switches list items."""

    model_config = ConfigDict(populate_by_name=True)

    cpu_utilization: int | float | None = Field(
        default=None,
        validation_alias="cpuUtilization",
        description="CPU utilization percentage.",
    )
    memory_utilization: int | float | None = Field(
        default=None,
        validation_alias="memoryUtilization",
        description="Memory utilization percentage.",
    )
    poe_available: int | float | None = Field(
        default=None,
        validation_alias="poeAvailable",
        description="Available PoE power in watts.",
    )
    poe_consumption: int | float | None = Field(
        default=None,
        validation_alias="poeConsumption",
        description="Consumed PoE power in watts.",
    )
    power_consumption: int | float | None = Field(
        default=None,
        validation_alias="powerConsumption",
        description="Switch power consumption in watts.",
    )
    system_temperature: int | float | None = Field(
        default=None,
        validation_alias="systemTemperature",
        description="System temperature reading.",
    )
    total_power_consumption: int | float | None = Field(
        default=None,
        validation_alias="totalPowerConsumption",
        description="Total power consumption in watts.",
    )
    up_link_ports: list[str] | None = Field(
        default=None,
        validation_alias="upLinkPorts",
        description="List of uplink port identifiers.",
    )
    usage: int | float | None = Field(
        default=None,
        description="Current usage metric (bytes transferred).",
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "SwitchTrend":
        """Normalise a raw switchTrend dict, parsing stringified upLinkPorts."""
        normalized = dict(raw)
        ul = normalized.get("upLinkPorts")
        if isinstance(ul, str):
            try:
                normalized["upLinkPorts"] = _ast.literal_eval(ul)
            except (ValueError, SyntaxError):
                pass
        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        data = handler(self)
        return {k: v for k, v in data.items() if v is not None}


class SwitchInterface(BaseModel):
    """Switch interface/port data as returned by get_switch_interfaces."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str | None = Field(
        default=None, description="Short port name (e.g. 'Gi1/0/1')."
    )
    name: str | None = Field(default=None, description="Port name.")
    alias: str | None = Field(
        default=None,
        description="Full IOS-style port name (e.g. 'GigabitEthernet1/0/1').",
    )
    status: str | None = Field(
        default=None, description="Port status (e.g. 'Connected', 'Disconnected')."
    )
    admin_status: str | None = Field(
        default=None,
        validation_alias="adminStatus",
        description="Administrative status (Up/Down).",
    )
    oper_status: str | None = Field(
        default=None,
        validation_alias="operStatus",
        description="Operational status (Up/Down).",
    )
    speed: int | float | None = Field(default=None, description="Port speed in bps.")
    duplex: str | None = Field(default=None, description="Duplex mode.")
    mtu: int | None = Field(default=None, description="MTU size.")
    vlan_mode: str | None = Field(
        default=None,
        validation_alias="vlanMode",
        description="VLAN mode (Access/Trunk).",
    )
    native_vlan: int | str | None = Field(
        default=None,
        validation_alias="nativeVlan",
        description="Native VLAN ID.",
    )
    allowed_vlans: list[str] | None = Field(
        default=None,
        validation_alias="allowedVlans",
        description="Allowed VLAN ranges (trunk mode).",
    )
    allowed_vlan_ids: list[int] | None = Field(
        default=None,
        validation_alias="allowedVlanIds",
        description="Expanded list of allowed VLAN IDs.",
    )
    uplink: bool | None = Field(
        default=None, description="True if this is an uplink port."
    )
    poe_status: str | None = Field(
        default=None,
        validation_alias="poeStatus",
        description="PoE status.",
    )
    poe_class: str | None = Field(
        default=None,
        validation_alias="poeClass",
        description="PoE class.",
    )
    connector: str | None = Field(default=None, description="Physical connector type.")
    serial_number: str | None = Field(
        default=None,
        validation_alias="serialNumber",
        description="Serial number of the switch member hosting this port.",
    )
    neighbour: str | None = Field(default=None, description="Neighbouring device name.")
    neighbour_port: str | None = Field(
        default=None,
        validation_alias="neighbourPort",
        description="Neighbouring device port.",
    )
    neighbour_type: str | None = Field(
        default=None,
        validation_alias="neighbourType",
        description="Neighbouring device type.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        data = handler(self)
        return {k: v for k, v in data.items() if v is not None}


class SwitchVlan(BaseModel):
    """Switch VLAN data as returned by get_switch_vlans."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str | None = Field(default=None, description="VLAN ID.")
    name: str | None = Field(default=None, description="VLAN name.")
    type: str | None = Field(default=None, description="VLAN type (e.g. 'Static').")
    status: str | None = Field(
        default=None, description="VLAN status (e.g. 'Not used', 'Active')."
    )
    ipv4: str | None = Field(
        default=None, description="IP address assigned to this VLAN SVI."
    )
    voice: str | None = Field(
        default=None, description="Voice VLAN status (Enabled/Disabled)."
    )
    interfaces: list[str] | None = Field(
        default=None,
        description="List of interface names in this VLAN.",
    )
    tagged_ports: list[str] | None = Field(
        default=None,
        validation_alias="taggedPorts",
        description="Tagged (trunk) ports in this VLAN.",
    )
    untagged_ports: list[str] | None = Field(
        default=None,
        validation_alias="untaggedPorts",
        description="Untagged (access) ports in this VLAN.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        data = handler(self)
        return {k: v for k, v in data.items() if v is not None}


class Switch(BaseModel):
    """Switch monitoring data (list item from get_all_switches)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    serial_number: str = Field(
        validation_alias="serialNumber",
        description="Unique serial number. Use as the primary key for all per-switch API calls.",
    )
    device_name: str | None = Field(
        default=None,
        validation_alias="deviceName",
        description="Hostname/display name of the switch.",
    )
    model: str | None = Field(default=None, description="Switch model number.")
    mac_address: str | None = Field(
        default=None,
        validation_alias="macAddress",
        description="MAC address of the switch.",
    )
    site_id: str | None = Field(
        default=None,
        validation_alias="siteId",
        description="ID of the site where the switch is located.",
    )
    site_name: str | None = Field(
        default=None,
        validation_alias="siteName",
        description="Name of the site where the switch is located.",
    )
    status: Literal["Online", "Offline"] | None = Field(
        default=None,
        description="Current switch status. Title-case: 'Online' or 'Offline'.",
    )
    deployment: str | None = Field(
        default=None,
        description="Deployment mode: 'Standalone', 'Stack', or 'VSX'.",
    )
    switch_role: str | None = Field(
        default=None,
        validation_alias="switchRole",
        description="Role in a stack or VSX pair: 'Standalone', 'Conductor', 'Standby', or 'Member'.",
    )
    switch_type: str | None = Field(
        default=None,
        validation_alias="switchType",
        description="Switch OS family: 'cx' (AOS-CX), 'tpd' (Cisco Catalyst), 'pvos' (ArubaOS-Switch).",
    )
    stack_id: str | None = Field(
        default=None,
        validation_alias="stackId",
        description="UUID of the stack this switch belongs to (null for standalone).",
    )
    stack_member_id: int | None = Field(
        default=None,
        validation_alias="stackMemberId",
        description="Stack member slot number (0 for standalone).",
    )
    firmware_version: str | None = Field(
        default=None,
        validation_alias="firmwareVersion",
        description="Firmware version currently running on the switch.",
    )
    ipv4: str | None = Field(default=None, description="IPv4 address of the switch.")
    ipv6: str | None = Field(default=None, description="IPv6 address of the switch.")
    public_ip: str | None = Field(
        default=None,
        validation_alias="publicIp",
        description="Public IP address of the switch.",
    )
    last_seen_at: int | None = Field(
        default=None,
        validation_alias="lastSeenAt",
        description="Unix timestamp (ms) when the switch was last seen (0 means currently online).",
    )
    uptime_in_millis: int | None = Field(
        default=None,
        validation_alias="uptimeInMillis",
        description="Switch uptime in milliseconds.",
    )
    j_number: str | None = Field(
        default=None,
        validation_alias="jNumber",
        description="J-number (Aruba license tracking number).",
    )
    switch_trends: list[SwitchTrend] | None = Field(
        default=None,
        validation_alias="switchTrends",
        description="Inline current-state snapshot (list of 1 item). Contains CPU/memory/PoE/power metrics.",
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Switch":
        """Normalise a raw get_all_switches list item into a Switch instance."""
        normalized = dict(raw)
        # Parse switchTrends items
        raw_trends = normalized.get("switchTrends")
        if isinstance(raw_trends, list):
            normalized["switchTrends"] = [SwitchTrend.from_api(t) for t in raw_trends]
        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        data = handler(self)
        return {k: v for k, v in data.items() if v is not None}


class SwitchDetail(Switch):
    """Rich single-switch detail, as returned by get_switch_details.

    Subclasses Switch and adds detail-only fields plus optional include sub-resources.
    Unlike get_ap_details, get_switch_details embeds NO sub-resources; all include
    keys are additive (fetched via separate API calls).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Detail-only scalar fields
    health: str | None = Field(
        default=None,
        description="Overall health status: 'Good', 'Fair', or 'Poor'.",
    )
    health_reasons: dict[str, Any] | None = Field(
        default=None,
        validation_alias="healthReasons",
        description="Health reason breakdown: {poorReasons: [...], fairReasons: [...]}.",
    )
    manufacturer: str | None = Field(
        default=None,
        description="Hardware manufacturer (e.g. 'Cisco', 'Aruba').",
    )
    last_restart_reason: str | None = Field(
        default=None,
        validation_alias="lastRestartReason",
        description="Reason for the last switch restart.",
    )
    config_status: str | None = Field(
        default=None,
        validation_alias="configStatus",
        description="Configuration sync status.",
    )
    switch_link_type: str | None = Field(
        default=None,
        validation_alias="switchLinkType",
        description="Switch link type (null for tpd/Cisco switches).",
    )
    last_config_change: int | str | None = Field(
        default=None,
        validation_alias="lastConfigChange",
        description="Timestamp of the last configuration change (epoch ms int or ISO string).",
    )

    # Optional sub-resource include fields
    interfaces: dict[str, Any] | None = Field(
        default=None,
        description="Switch interfaces (from get_switch_interfaces). Only present when include=['interfaces'] is passed.",
    )
    vlans: dict[str, Any] | None = Field(
        default=None,
        description="Switch VLANs (from get_switch_vlans). Only present when include=['vlans'] is passed.",
    )
    poe: dict[str, Any] | None = Field(
        default=None,
        description="PoE port data (from get_switch_interface_poe). Only present when include=['poe'] is passed.",
    )
    lag: dict[str, Any] | None = Field(
        default=None,
        description="LAG group data (from get_switch_lag). Only present when include=['lag'] is passed.",
    )
    vsx: dict[str, Any] | None = Field(
        default=None,
        description="VSX peer data (from get_switch_vsx). Set to {'error': '...'} on non-VSX platforms. Only present when include=['vsx'] is passed.",
    )
    stack_members: dict[str, Any] | None = Field(
        default=None,
        validation_alias="stack_members",
        description="Stack member details (from get_stack_members). Only present when include=['stack_members'] is passed.",
    )
    hardware: dict[str, Any] | None = Field(
        default=None,
        description="Hardware category health (from get_switch_hardware_categories). Only present when include=['hardware'] is passed.",
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "SwitchDetail":  # type: ignore[override]
        """Normalise a get_switch_details payload into a SwitchDetail instance."""
        normalized = dict(raw)
        # Parse switchTrends items
        raw_trends = normalized.get("switchTrends")
        if isinstance(raw_trends, list):
            normalized["switchTrends"] = [SwitchTrend.from_api(t) for t in raw_trends]
        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(  # type: ignore[override]
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        data = handler(self)
        return {k: v for k, v in data.items() if v is not None}


# --- Gateway monitoring (a20) ---


class GatewayPort(BaseModel):
    """Gateway wired port data structure (from get_all_gateway_ports)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    port_number: str = Field(
        validation_alias="portNumber",
        description="Port number string (e.g. '0'). Used as identifier for port trend queries.",
    )
    name: str | None = Field(
        default=None,
        description="Human-readable port label (e.g. 'GE 0/0/0').",
    )
    oper_state: str | None = Field(
        default=None,
        validation_alias="operState",
        description="Operational state: 'Up' or 'Down'.",
    )
    admin_state: str | None = Field(
        default=None,
        validation_alias="adminState",
        description="Administrative state: 'Enabled' or 'Disabled'.",
    )
    health: str | None = Field(
        default=None,
        description="Port health: 'Good' or 'Unknown'.",
    )
    speed: str | None = Field(
        default=None,
        description="Port speed (e.g. '1000', 'Auto').",
    )
    duplex: str | None = Field(
        default=None,
        description="Duplex mode: 'Full', 'Half', or 'Auto'.",
    )
    vlan: str | None = Field(
        default=None,
        description="VLAN assigned to this port (string).",
    )
    mtu: str | None = Field(
        default=None,
        description="MTU string (e.g. '1500 bytes').",
    )
    throughput: dict | None = Field(
        default=None,
        description="Current throughput: {received, sent} in bps.",
    )
    usage: dict | None = Field(
        default=None,
        description="Cumulative usage: {total, received, sent} in bytes.",
    )
    mac_address: str | None = Field(
        default=None,
        validation_alias="macAddress",
        description="MAC address of the port.",
    )
    port_type: str | None = Field(
        default=None,
        validation_alias="portType",
        description="Port type (e.g. 'Access').",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep port payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class GatewayTunnel(BaseModel):
    """Gateway tunnel data structure (from get_all_gateway_tunnels)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    tunnel_name: str = Field(
        validation_alias="tunnelName",
        description="Tunnel name (e.g. 'GW01:inet::AP04:inet'). Used as identifier for tunnel trend queries.",
    )
    tunnel_type: str | None = Field(
        default=None,
        validation_alias="tunnelType",
        description="Tunnel type: 'LAN' or 'WAN'.",
    )
    status: str | None = Field(
        default=None,
        description="Tunnel status: 'Up' or 'Down'.",
    )
    health: str | None = Field(
        default=None,
        description="Tunnel health: 'Good' or 'Poor'.",
    )
    encapsulation: str | None = Field(
        default=None,
        description="Encapsulation type: 'IPsec' or 'GRE'.",
    )
    mode: str | None = Field(
        default=None,
        description="Tunnel mode: 'Orchestrated' or 'Manual'.",
    )
    peer_type: str | None = Field(
        default=None,
        validation_alias="peerType",
        description="Peer type: 'AP', 'UNKNOWN', etc.",
    )
    destination_ip_address: str | None = Field(
        default=None,
        validation_alias="destinationIpAddress",
        description="Destination IP address of the tunnel.",
    )
    source_ip_address: str | None = Field(
        default=None,
        validation_alias="sourceIpAddress",
        description="Source IP address of the tunnel.",
    )
    uptime: str | None = Field(
        default=None,
        description="Human-readable tunnel uptime (e.g. '1M 24d').",
    )
    mtu: str | None = Field(
        default=None,
        description="MTU of the tunnel.",
    )
    vlan_id: int | None = Field(
        default=None,
        validation_alias="vlanId",
        description="VLAN ID associated with the tunnel.",
    )
    throughput: dict | None = Field(
        default=None,
        description="Current throughput: {received, sent} in bps.",
    )
    dropped_packets: int | None = Field(
        default=None,
        validation_alias="droppedPackets",
        description="Number of dropped packets.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep tunnel payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class GatewayVlan(BaseModel):
    """Gateway VLAN data structure (from get_all_gateway_vlans)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    vlan_id: int = Field(
        validation_alias="vlanId",
        description="VLAN ID (integer).",
    )
    name: str | None = Field(
        default=None,
        description="VLAN name (may be empty string).",
    )
    status: str | None = Field(
        default=None,
        description="Operational status: 'Up' or 'Down'.",
    )
    admin_status: str | None = Field(
        default=None,
        validation_alias="adminStatus",
        description="Administrative status: 'Up' or 'Down'.",
    )
    vlan_type: str | None = Field(
        default=None,
        validation_alias="vlanType",
        description="VLAN type (e.g. 'Static').",
    )
    ipv4: str | None = Field(
        default=None,
        description="IPv4 address assigned to this VLAN.",
    )
    ipv4_subnet: str | None = Field(
        default=None,
        validation_alias="ipv4Subnet",
        description="IPv4 subnet (e.g. '10.1.1.1/24'). Null when no IP is assigned.",
    )
    interfaces: str | None = Field(
        default=None,
        description="Interface(s) associated with this VLAN.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep VLAN payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class Gateway(BaseModel):
    """Gateway monitoring data structure (list item or detail shape)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    serial_number: str = Field(
        validation_alias="serialNumber",
        description="Unique serial number of the gateway.",
    )
    device_name: str | None = Field(
        default=None,
        validation_alias="deviceName",
        description="Display name of the gateway.",
    )
    model: str | None = Field(
        default=None,
        description="Gateway model (e.g. 'A7240XM', 'A9004').",
    )
    status: str | None = Field(
        default=None,
        description="Operational status: 'Online' or 'Offline' (title-case).",
    )
    ip_address: str | None = Field(
        default=None,
        validation_alias="ipAddress",
        description="IPv4 address of the gateway.",
    )
    site_id: str | None = Field(
        default=None,
        validation_alias="siteId",
        description="ID of the site where the gateway is located.",
    )
    site_name: str | None = Field(
        default=None,
        validation_alias="siteName",
        description="Name of the site where the gateway is located.",
    )
    cluster_name: str | None = Field(
        default=None,
        validation_alias="clusterName",
        description="Cluster name. Empty string when gateway is not in a cluster.",
    )
    role: str | None = Field(
        default=None,
        description="Gateway role: 'Member', 'Leader', 'Isoleader', or null when not in cluster.",
    )
    device_function: str | None = Field(
        default=None,
        validation_alias="deviceFunction",
        description="Device function: 'Unspecified', 'Mobility Gateway', etc.",
    )
    cpu_utilization: int | float | None = Field(
        default=None,
        validation_alias="cpuUtilization",
        description="Current CPU utilization percentage.",
    )
    memory_utilization: int | float | None = Field(
        default=None,
        validation_alias="memoryUtilization",
        description="Current memory utilization percentage.",
    )
    uptime_in_millis: int | None = Field(
        default=None,
        validation_alias="uptimeInMillis",
        description="Gateway uptime in milliseconds.",
    )
    firmware_version: str | None = Field(
        default=None,
        validation_alias="firmwareVersion",
        description="Current firmware version.",
    )
    mac_address: str | None = Field(
        default=None,
        validation_alias="macAddress",
        description="MAC address of the gateway.",
    )
    reboot_reason: str | None = Field(
        default=None,
        validation_alias="rebootReason",
        description="Reason for the last reboot.",
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Gateway":
        """Normalize raw Central gateway payload into a sparse MCP-friendly shape."""
        return cls(**raw)

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep gateway payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class GatewayUplink(BaseModel):
    """Gateway uplink data structure (from get_gateway_uplinks).

    NOTE: The uplink endpoint returns ``{items: [...], total: N}`` (not a flat
    list).  The ``link_tag`` field is the per-uplink trend identifier used with
    ``get_gateway_uplink_trends(link_tag=...)``.

    Shape is sourced from pycentral source code; no live uplinks were available
    in the capture account (``total: 0``).
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    link_tag: str | None = Field(
        default=None,
        validation_alias="linkTag",
        description="Uplink identifier used for trend queries (get_gateway_uplink_trends).",
    )
    name: str | None = Field(
        default=None,
        description="Human-readable uplink name.",
    )
    status: str | None = Field(
        default=None,
        description="Uplink operational status.",
    )
    uplink_type: str | None = Field(
        default=None,
        validation_alias="uplinkType",
        description="Uplink type (e.g. 'wired', 'cellular').",
    )
    ip_address: str | None = Field(
        default=None,
        validation_alias="ipAddress",
        description="IP address of the uplink.",
    )
    gateway: str | None = Field(
        default=None,
        description="Gateway device name associated with the uplink.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep uplink payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class GatewayDHCPPool(BaseModel):
    """DHCP pool configured on a gateway."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    pool_name: str = Field(
        validation_alias="poolName", description="Name of the gateway DHCP pool."
    )
    vlan_id: int = Field(
        validation_alias="vlanId", description="VLAN ID served by the DHCP pool."
    )
    vlan_name: str = Field(
        validation_alias="vlanName", description="Name of the VLAN served by the pool."
    )
    subnet: str = Field(description="IPv4 subnet allocated by the DHCP pool.")
    lease_duration: int = Field(
        validation_alias="leaseDuration",
        description="Configured DHCP lease duration in seconds.",
    )
    pool_size: int = Field(
        validation_alias="poolSize",
        description="Total number of addresses in the DHCP pool.",
    )
    current_leases: int = Field(
        validation_alias="currentLeases",
        description="Number of currently active leases in the DHCP pool.",
    )
    utilization: int = Field(description="Current DHCP pool utilization percentage.")
    available_addresses: int = Field(
        validation_alias="availableAddresses",
        description="Number of addresses currently available in the DHCP pool.",
    )


class GatewayDHCPLease(BaseModel):
    """DHCP lease reported by a gateway."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    pool_name: str = Field(
        validation_alias="poolName",
        description="Name of the pool that issued the lease.",
    )
    ip_address: str = Field(
        validation_alias="ipAddress", description="IPv4 address assigned to the client."
    )
    mac_address: str = Field(
        validation_alias="macAddress", description="MAC address of the leased client."
    )
    client_site_id: str = Field(
        validation_alias="clientSiteId",
        description="Central site ID associated with the leased client.",
    )
    client_serial: str = Field(
        validation_alias="clientSerial",
        description="Central serial identifier associated with the leased client.",
    )
    infra_type: str | None = Field(
        validation_alias="infraType",
        description="Infrastructure type reported for the leased client, when available.",
    )
    host_name: str = Field(
        validation_alias="hostName", description="Hostname reported by the DHCP client."
    )
    client_device_type: str = Field(
        validation_alias="clientDeviceType",
        description="Device type or vendor class reported by the DHCP client.",
    )
    start_time: int | float | str = Field(
        validation_alias="startTime", description="Timestamp when the DHCP lease began."
    )
    expiration_time: int | float | str = Field(
        validation_alias="expirationTime",
        description="Timestamp when the DHCP lease expires.",
    )
    remaining_time: str = Field(
        validation_alias="remainingTime",
        description="Remaining DHCP lease time as reported by Central.",
    )
    reservation: str = Field(
        description="Whether the DHCP lease is backed by a reservation."
    )


class GatewayDetail(Gateway):
    """Gateway detail snapshot with optional include sub-resources.

    NOTE: get_gateway_details returns the SAME shape as a list item (no
    additional embedded sub-resources). Pass ``include`` to central_get_gateway_details
    to add richer sub-resource data via dedicated API calls.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # Sub-resources populated only when requested via include=
    ports: list[GatewayPort] | None = Field(
        default=None,
        description="List of gateway wired ports (only when 'ports' is included).",
    )
    tunnels: list[GatewayTunnel] | None = Field(
        default=None,
        description="List of gateway tunnels (only when 'tunnels' is included).",
    )
    uplinks: list[GatewayUplink] | None = Field(
        default=None,
        description="List of gateway uplinks (only when 'uplinks' is included).",
    )
    dhcp_pools: list[GatewayDHCPPool] | None = Field(
        default=None,
        description="Gateway DHCP pools (only when 'dhcp' is included).",
    )
    dhcp_leases: list[GatewayDHCPLease] | None = Field(
        default=None,
        description="Gateway DHCP leases (only when 'dhcp' is included).",
    )
    vlans: list[GatewayVlan] | None = Field(
        default=None,
        description="List of gateway VLANs (only when 'vlans' is included).",
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "GatewayDetail":  # type: ignore[override]
        """Normalize a gateway detail payload into a GatewayDetail instance."""
        normalized: dict[str, Any] = dict(raw)

        raw_ports = normalized.pop("ports", None)
        if isinstance(raw_ports, list):
            normalized["ports"] = [GatewayPort(**p) for p in raw_ports]

        raw_tunnels = normalized.pop("tunnels", None)
        if isinstance(raw_tunnels, list):
            normalized["tunnels"] = [GatewayTunnel(**t) for t in raw_tunnels]

        raw_uplinks = normalized.pop("uplinks", None)
        if isinstance(raw_uplinks, list):
            normalized["uplinks"] = [GatewayUplink(**u) for u in raw_uplinks]

        raw_dhcp_pools = normalized.pop("dhcp_pools", None)
        if isinstance(raw_dhcp_pools, list):
            normalized["dhcp_pools"] = [
                GatewayDHCPPool(**pool) for pool in raw_dhcp_pools
            ]

        raw_dhcp_leases = normalized.pop("dhcp_leases", None)
        if isinstance(raw_dhcp_leases, list):
            normalized["dhcp_leases"] = [
                GatewayDHCPLease(**lease) for lease in raw_dhcp_leases
            ]

        raw_vlans = normalized.pop("vlans", None)
        if isinstance(raw_vlans, list):
            normalized["vlans"] = [GatewayVlan(**v) for v in raw_vlans]

        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(  # type: ignore[override]
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep detail payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class ClusterMember(BaseModel):
    """Cluster member data structure (from get_all_cluster_members).

    NOTE: Cluster member status uses ALL-CAPS 'ONLINE'/'OFFLINE', unlike the
    gateway list which uses title-case 'Online'/'Offline'.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    serial_number: str = Field(
        validation_alias="serialNumber",
        description="Serial number of the cluster member gateway.",
    )
    device_name: str | None = Field(
        default=None,
        validation_alias="deviceName",
        description="Display name of the gateway.",
    )
    cluster_name: str | None = Field(
        default=None,
        validation_alias="clusterName",
        description="Name of the cluster.",
    )
    role: str | None = Field(
        default=None,
        description="Role in the cluster: 'Member', 'Leader', 'Isoleader'.",
    )
    status: str | None = Field(
        default=None,
        description="Operational status: 'ONLINE' or 'OFFLINE' (all-caps — differs from gateway list).",
    )
    model: str | None = Field(
        default=None,
        description="Gateway model.",
    )
    ipv4: str | None = Field(
        default=None,
        description="IPv4 address of the gateway.",
    )
    site_id: str | None = Field(
        default=None,
        validation_alias="siteId",
        description="Site ID.",
    )
    site_name: str | None = Field(
        default=None,
        validation_alias="siteName",
        description="Site name.",
    )
    firmware_version: str | None = Field(
        default=None,
        validation_alias="firmwareVersion",
        description="Firmware version.",
    )
    mac_address: str | None = Field(
        default=None,
        validation_alias="macAddress",
        description="MAC address.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep member payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class CapacityTrendSample(BaseModel):
    """Normalized client or device capacity sample for a gateway cluster."""

    model_config = ConfigDict(extra="allow")

    capacity_type: str = Field(
        description="Capacity series type: client_capacity or device_capacity."
    )
    timestamp: str = Field(description="RFC 3339 timestamp for the capacity sample.")
    active_client_count: int | float | None = Field(
        default=None, description="Active clients handled by the cluster."
    )
    standby_client_count: int | float | None = Field(
        default=None, description="Standby clients tracked by the cluster."
    )
    cluster_client_max_capacity: int | float | None = Field(
        default=None, description="Maximum client capacity for the cluster."
    )
    active_client_percentage: int | float | None = Field(
        default=None, description="Active client utilization percentage."
    )
    standby_client_percentage: int | float | None = Field(
        default=None, description="Standby client utilization percentage."
    )
    active_ap_count: int | float | None = Field(
        default=None, description="Active access points handled by the cluster."
    )
    standby_ap_count: int | float | None = Field(
        default=None, description="Standby access points tracked by the cluster."
    )
    active_sw_count: int | float | None = Field(
        default=None, description="Active switches handled by the cluster."
    )
    standby_sw_count: int | float | None = Field(
        default=None, description="Standby switches tracked by the cluster."
    )
    active_ap_percentage: int | float | None = Field(
        default=None, description="Active access-point utilization percentage."
    )
    standby_ap_percentage: int | float | None = Field(
        default=None, description="Standby access-point utilization percentage."
    )
    active_sw_percentage: int | float | None = Field(
        default=None, description="Active switch utilization percentage."
    )
    standby_sw_percentage: int | float | None = Field(
        default=None, description="Standby switch utilization percentage."
    )
    cluster_device_max_capacity: int | float | None = Field(
        default=None, description="Maximum AP and switch capacity for the cluster."
    )
    device_max_capacity: int | float | None = Field(
        default=None,
        description="Maximum capacity reported by a selected cluster member.",
    )

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop metrics that do not belong to this capacity series."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class GatewayCluster(ConciseProjectable):
    """Gateway cluster snapshot with members and tunnel health summary."""

    concise_omit: ClassVar[frozenset[str]] = frozenset(
        {"tunnels", "vlan_mismatch", "connectivity", "capacity"}
    )

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    cluster_name: str = Field(description="Name of the cluster.")
    members: list[ClusterMember] = Field(
        default_factory=list,
        description="List of cluster member gateways.",
    )
    tunnel_health_summary: list[dict] | dict | None = Field(
        default=None,
        description=(
            "Cluster tunnel health summary per member "
            "(list of {serialNumber, deviceName, tunnelHealth: {good, fair, poor}})."
        ),
    )
    # Optional include fields
    tunnels: list[dict] | None = Field(
        default=None,
        description="All cluster tunnels (only when 'tunnels' is included).",
    )
    vlan_mismatch: dict | None = Field(
        default=None,
        description="VLAN mismatch summary (only when 'vlan_mismatch' is included).",
    )
    connectivity: dict | None = Field(
        default=None,
        description="Cluster connectivity graph (only when 'connectivity' is included).",
    )
    capacity: list[CapacityTrendSample] | None = Field(
        default=None,
        description="Capacity trend samples (only when 'capacity' is included).",
    )

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "GatewayCluster":
        """Build a GatewayCluster from a fetch_cluster_snapshot result dict."""
        normalized: dict[str, Any] = dict(raw)
        raw_members = normalized.pop("members", [])
        if isinstance(raw_members, list):
            normalized["members"] = [ClusterMember(**m) for m in raw_members]
        return cls(**normalized)

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        """Drop null fields to keep cluster payloads compact."""
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class GatewayClusterEnvelope(CentralEnvelope):
    """Typed response envelope for gateway cluster snapshots."""

    items: list[GatewayCluster] = Field(
        description="Gateway cluster snapshots returned by the selected view."
    )


# --- Client analytics -------------------------------------------------------


def coerce_number(value: object) -> int | float | None:
    """Turn Central's stringified analytics numbers into numbers.

    Central returns counts and percentages as strings (``"1624"``, ``"76.97%"``)
    and uses ``-1`` as a no-data sentinel; the sentinel becomes ``None``.
    """
    if value is None or isinstance(value, bool):
        return None if value is None else int(value)
    if isinstance(value, str):
        text = value.strip().rstrip("%")
        if text == "":
            return None
        try:
            value = float(text) if "." in text else int(text)
        except ValueError as exc:
            raise ValueError(f"expected a numeric value, got {value!r}") from exc
    if value == -1:
        return None
    return value


CentralCount = Annotated[int | None, BeforeValidator(coerce_number)]
CentralScore = Annotated[float | None, BeforeValidator(coerce_number)]


def _lower(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


OnboardingStage = Annotated[str, BeforeValidator(_lower)]


class ClientUsageSample(BaseModel):
    """One timestamped TX/RX byte-usage sample."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["usage_sample"] = "usage_sample"
    timestamp: str = Field(
        validation_alias=AliasChoices("ts", "timestamp"),
        description="RFC 3339 timestamp for this sample.",
    )
    data: list[int | float] = Field(
        default_factory=list,
        description="Values ordered to match the analytics keys.",
    )
    keys: list[str] = Field(description="Names corresponding to each sample value.")
    interval: str = Field(description="Sampling interval selected by Central.")


class TopClientUsage(BaseModel):
    """One client ranked by total byte usage."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["top_client_usage"] = "top_client_usage"
    client_name: str = Field(alias="clientName", description="Client display name.")
    mac_address: str = Field(alias="macAddress", description="Client MAC address.")
    usage: int = Field(description="Total usage in bytes.")
    connection_type: str = Field(
        alias="clientConnectionType",
        description="Client connection type.",
    )
    site_name: str | None = Field(
        default=None,
        alias="siteName",
        description="Site display name.",
    )
    site_id: str | int | None = Field(
        default=None,
        alias="siteId",
        description="Site identifier.",
    )


class ClientTrendSample(BaseModel):
    """One timestamped client-count sample grouped by category."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["client_trend_sample"] = "client_trend_sample"
    timestamp: str = Field(
        validation_alias=AliasChoices("ts", "timestamp"),
        description="RFC 3339 timestamp for this sample.",
    )
    data: list[int | float] = Field(
        default_factory=list,
        description="Values ordered to match the trend keys.",
    )
    keys: list[str] = Field(description="Categories corresponding to sample values.")
    interval: str = Field(description="Sampling interval selected by Central.")


class ClientMobilityEvent(BaseModel):
    """One wireless client roaming transition."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["mobility_event"] = "mobility_event"
    occurred_at: str | None = Field(default=None, alias="occurredAt")
    roam_time: str | None = Field(default=None, alias="roamTime")
    wlan_name: str | None = Field(default=None, alias="wlanName")
    source_ap: str | None = Field(default=None, alias="sourceAp")
    destination_ap: str | None = Field(default=None, alias="destinationAp")
    from_channel: str | None = Field(default=None, alias="fromChannel")
    to_channel: str | None = Field(default=None, alias="toChannel")
    from_bssid: str | None = Field(default=None, alias="fromBssid")
    to_bssid: str | None = Field(default=None, alias="toBssid")
    rssi: str | None = Field(default=None)
    radio_band: str | None = Field(default=None, alias="radioBand")
    roam_protocol: str | None = Field(default=None, alias="roamProtocol")


class OnboardingStageDimensions(BaseModel):
    """Top-five dimensions behind one stage's failed or delayed attempts."""

    clients: list[str] = Field(default_factory=list, description="Client MACs.")
    access_devices: list[str] = Field(
        default_factory=list, description="Access device MACs."
    )
    wlans: list[str] = Field(default_factory=list, description="WLAN names.")
    band: list[str] = Field(default_factory=list, description="Radio bands.")
    servers: list[str] = Field(
        default_factory=list,
        description="Auth, DHCP, or DNS servers involved, by stage.",
    )


class OnboardingStageSummary(ConciseProjectable):
    """Attempt outcome counts for one onboarding stage."""

    concise_omit: ClassVar[frozenset[str]] = frozenset({"failed", "delayed"})

    kind: Literal["onboarding_summary"] = "onboarding_summary"
    stage: OnboardingStage = Field(description="assoc, auth, dhcp, or dns.")
    attempts: CentralCount = Field(default=None)
    failures: CentralCount = Field(default=None)
    success: CentralCount = Field(default=None)
    delays: CentralCount = Field(default=None)
    success_percent: float | None = Field(
        default=None,
        description="success / attempts as a percentage; null without attempts.",
    )
    failure_reasons: list[str] = Field(
        default_factory=list, description="Top failure reasons."
    )
    delay_reasons: list[str] = Field(
        default_factory=list, description="Top delay reasons."
    )
    failed: OnboardingStageDimensions | None = Field(
        default=None, description="Top dimensions behind failed attempts."
    )
    delayed: OnboardingStageDimensions | None = Field(
        default=None, description="Top dimensions behind delayed attempts."
    )

    @model_validator(mode="after")
    def _derive_success_percent(self) -> "OnboardingStageSummary":
        if self.attempts and self.success is not None:
            self.success_percent = round(self.success / self.attempts * 100, 2)
        return self


class OnboardingStageReasons(BaseModel):
    """Top onboarding reasons for one stage."""

    kind: Literal["onboarding_reasons"] = "onboarding_reasons"
    stage: OnboardingStage = Field(alias="type", description="Onboarding stage.")
    reasons: list[str] = Field(default_factory=list)


class OnboardingCountDatum(BaseModel):
    """One grouped onboarding count."""

    value: str
    field: str
    count: int
    stage: OnboardingStage


class OnboardingStageCounts(BaseModel):
    """Grouped onboarding counts for one stage."""

    kind: Literal["onboarding_count"] = "onboarding_count"
    stage: OnboardingStage = Field(alias="type", description="Onboarding stage.")
    data: list[OnboardingCountDatum] = Field(default_factory=list)


ClientAnalyticsItem = (
    ClientUsageSample
    | TopClientUsage
    | ClientTrendSample
    | ClientMobilityEvent
    | OnboardingStageSummary
    | OnboardingStageReasons
    | OnboardingStageCounts
)


class ClientAnalyticsEnvelope(CentralEnvelope):
    """Typed response envelope for client usage, mobility, and onboarding analytics."""

    items: list[ClientAnalyticsItem] = Field(
        description="Analytics records selected by metric and view."
    )
    overall_score: float | None = Field(
        default=None,
        description=(
            "Overall onboarding experience score, 0-100, the product of the "
            "per-stage success rates; null outside the onboarding summary view "
            "or when Central reports no attempts."
        ),
    )
