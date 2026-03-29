from fastmcp import Context
from typing import List, Optional, Literal
from models import Device, ErrorResult
from utils import clean_device_data, build_odata_filter, FilterField, retry_pycentral_method
from pycentral.new_monitoring import MonitoringDevices
from tools import READ_ONLY

# API field definitions — update allowed_values when Central adds/removes enum options
DEVICE_FILTER_FIELDS: dict[str, FilterField] = {
    "site_id": FilterField("siteId"),
    "device_type": FilterField("deviceType", ["Access Point", "Switch", "Gateway"]),
    "device_name": FilterField("deviceName"),
    "serial_number": FilterField("serialNumber"),
    "model": FilterField("model"),
    "device_function": FilterField("deviceFunction"),
    "is_provisioned": FilterField("isProvisioned"),
}


def register(mcp):

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_devices(
        ctx: Context,
        site_id: Optional[str] = None,
        device_type: Optional[Literal["Access Point", "Switch", "Gateway"]] = None,
        device_name: Optional[str] = None,
        serial_number: Optional[str] = None,
        model: Optional[str] = None,
        device_function: Optional[str] = None,
        is_provisioned: Optional[bool] = None,
        site_assigned: Optional[bool] = None,
        sort: Optional[str] = None,
    ) -> List[Device] | ErrorResult:
        """
        Returns a filtered list of devices from Central using OData v4.0 filter syntax.

        Prefer this over any full-inventory fetch for targeted queries by site, type, model,
        or status. Call central_get_site_name_id_mapping first to obtain site_id values for filtering.

        Parameters:
        - site_id: Exact site ID or comma-separated list of IDs.
        - device_type: "Access Point", "Switch", or "Gateway". Comma-separated for multiple.
        - device_name: Device display name. Comma-separated for multiple.
        - serial_number: Device serial number. Comma-separated for multiple.
        - model: Device model (e.g., AP-735-RWF1). Comma-separated for multiple.
        - device_function: Device function classification. Comma-separated for multiple.
        - is_provisioned: True returns only provisioned devices (sending Monitoring data to New Central).
          False returns only unprovisioned devices.
        - site_assigned: True returns only devices assigned to a site. False returns only devices not assigned to a site.
        - sort: Comma-separated sort expressions (e.g., 'deviceName asc, model desc').
          Supported fields: siteId, model, siteName, serialNumber, macAddress, deviceType,
          ipv4, deviceFunction, deviceName.
        """
        raw_pairs = [
            ("site_id", site_id),
            ("device_type", device_type),
            ("device_name", device_name),
            ("serial_number", serial_number),
            ("model", model),
            ("device_function", device_function),
        ]
        pairs = [(DEVICE_FILTER_FIELDS[k], v) for k, v in raw_pairs if v is not None]

        if is_provisioned is not None:
            pairs.append(
                (
                    DEVICE_FILTER_FIELDS["is_provisioned"],
                    "Yes" if is_provisioned else "No",
                )
            )

        filter_str = build_odata_filter(pairs)

        # normalize site_assigned: True -> "ASSIGNED", False -> "UNASSIGNED", None -> None
        site_assigned = (
            None
            if site_assigned is None
            else ("ASSIGNED" if site_assigned else "UNASSIGNED")
        )

        try:
            devices = retry_pycentral_method(
                MonitoringDevices.get_all_device_inventory,
                central_conn=ctx.lifespan_context["conn"],
                filter_str=filter_str,
                site_assigned=site_assigned,
                sort=sort,
            )
        except Exception as e:
            return ErrorResult(error="Error fetching devices", detail=str(e))

        if not devices:
            return ErrorResult(error="No devices found matching the specified criteria.")
        return clean_device_data(devices)

    @mcp.tool(annotations=READ_ONLY)
    async def central_find_device(
        ctx: Context,
        serial_number: Optional[str] = None,
        device_name: Optional[str] = None,
    ) -> Device | ErrorResult:
        """
        Find a single device by unique identifier. Returns the device if exactly one match is found, otherwise returns an error message.

        Parameters:
        - serial_number: Device serial number (preferred — most reliable unique identifier).
        - device_name: Device display name. Use only if serial number is unknown.
        """
        if not serial_number and not device_name:
            return ErrorResult(error="Please provide at least one unique identifier: serial_number or device_name.")

        if serial_number and device_name:
            return ErrorResult(error="Please provide only one unique identifier: either serial_number or device_name, not both.")

        pairs = [
            (DEVICE_FILTER_FIELDS[k], v)
            for k, v in [("device_name", device_name), ("serial_number", serial_number)]
            if v is not None
        ]
        filter_str = build_odata_filter(pairs)
        try:
            device_resp = retry_pycentral_method(
                MonitoringDevices.get_device_inventory,
                central_conn=ctx.lifespan_context["conn"],
                filter_str=filter_str,
            )
        except Exception as e:
            return ErrorResult(error="Error occurred while fetching device data", detail=str(e))
        if "items" not in device_resp:
            return ErrorResult(error="Unexpected API error response", detail=str(device_resp))

        if len(device_resp["items"]) == 0:
            return ErrorResult(error="No device found matching the provided criteria.")
        if len(device_resp["items"]) > 1:
            return ErrorResult(error="Multiple devices found matching the criteria. Use serial_number for a unique match.")
        return clean_device_data(device_resp["items"])[0]
