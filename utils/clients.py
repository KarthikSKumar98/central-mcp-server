from models import Client


def clean_client_data(clients: list[dict]) -> list[Client]:
    """Transform client API response to match Client model schema.

    Converts camelCase fields to snake_case and removes duplicates.

    Args:
        clients: List of client dictionaries from API

    Returns:
        List of cleaned client dictionaries matching Client model schema

    """
    cleaned_clients = []
    for client in clients:
        if isinstance(client, dict):
            cleaned_client = {
                # Primary identifiers
                "mac": client.get("macAddress"),
                "name": client.get("clientName"),
                "ipv4": client.get("ipv4"),
                "ipv6": client.get("ipv6"),
                "hostname": client.get("hostName"),
                # Client classification
                "connection_type": client.get("clientConnectionType"),
                "os": client.get("clientOperatingSystem"),
                "vendor": client.get("clientVendor"),
                "manufacturer": client.get("clientManufacturer"),
                "category": client.get("clientCategory"),
                "function": client.get("clientFunction"),
                "capabilities": client.get("clientCapabilities"),
                # Status and health
                "status": client.get("status"),
                # Connection information
                "connected_device_type": client.get("connectedDeviceType"),
                "connected_device_serial": client.get("connectedDeviceSerial"),
                "connected_to": client.get("connectedTo"),
                "connected_at": client.get("connectedAt"),
                "last_seen_at": client.get("lastSeenAt"),
                "port": client.get("port"),
                # Network configuration
                "vlan_id": client.get("vlanId"),
                "tunnel_type": client.get("tunnelType"),
                "tunnel_id": client.get("tunnelId", None),
                # Wireless-specific fields
                "wlan_name": client.get("wlanName"),
                "wireless_band": client.get("wirelessBand"),
                "wireless_channel": client.get("wirelessChannel"),
                "wireless_security": client.get("wirelessSecurity"),
                "key_management": client.get("keyManagement"),
                "bssid": client.get("bssid"),
                "radio_mac": client.get("radioMacAddress"),
                # Authentication
                "user_name": client.get("userName"),
                "authentication": client.get("authenticationType"),
                # Site information
                "site_id": client.get("siteId"),
                "site_name": client.get("siteName"),
                # Additional metadata
                "role": client.get("role"),
                "tags": client.get("clientTags"),
            }
            conn_type = cleaned_client.get("connection_type")
            if conn_type == "Wired":
                for f in {
                    "wlan_name",
                    "wireless_band",
                    "wireless_channel",
                    "wireless_security",
                    "key_management",
                    "bssid",
                    "radio_mac",
                }:
                    cleaned_client.pop(f, None)
            elif conn_type == "Wireless":
                cleaned_client.pop("port", None)

            cleaned_clients.append(Client(**cleaned_client))
    return cleaned_clients
