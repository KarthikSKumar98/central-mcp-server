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
