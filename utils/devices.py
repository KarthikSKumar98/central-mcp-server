from models import Device


def clean_device_data(devices: list[dict]) -> list[Device]:
    """Remove duplicate fields from device inventory data.

    Removes:
    - 'softwareVersion' (keeping 'firmwareVersion')
    - 'id' (keeping 'serialNumber')

    Args:
        devices: List of device dictionaries from API

    Returns:
        List of cleaned device dictionaries

    """
    cleaned_devices = []
    for device in devices:
        if isinstance(device, dict):
            cleaned_devices.append(
                Device(
                    serial_number=device.get("serialNumber"),
                    mac_address=device.get("macAddress"),
                    device_type=device.get("deviceType"),
                    model=device.get("model"),
                    part_number=device.get("partNumber"),
                    name=device.get("deviceName"),
                    function=device.get("deviceFunction"),
                    status=device.get("status"),
                    is_provisioned=device.get("isProvisioned", "").lower() == "yes",
                    role=device.get("role"),
                    deployment=device.get("deployment"),
                    tier=device.get("tier"),
                    firmware_version=device.get("firmwareVersion"),
                    site_id=device.get("siteId"),
                    site_name=device.get("siteName"),
                    device_group_name=device.get("deviceGroupName"),
                    scope_id=device.get("scopeId"),
                    ipv4=device.get("ipv4"),
                    stack_id=device.get("stackId"),
                )
            )
    return cleaned_devices


def process_device_status(devices: list[dict], device_status: str | None) -> list[dict]:
    """Process a list of devices to filter by connectivity status to Central.

    Args:
        devices: List of Device objects
        device_status: The status to filter by ("ONLINE" or "OFFLINE")

    Returns:
        List of devices filtered by the specified status
    Returns:
        Dictionary with counts of 'ONLINE' and 'OFFLINE' devices

    """
    if device_status == "ONLINE":
        devices = [d for d in devices if d.get("status") == "ONLINE"]
    elif device_status == "OFFLINE":
        devices = [d for d in devices if d.get("status") == "OFFLINE"]
    return devices
