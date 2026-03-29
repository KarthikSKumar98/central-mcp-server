from models import Alert


def clean_alert_data(alerts: list[dict]) -> list[Alert]:
    cleaned_alerts = []
    for alert in alerts:
        cleaned_alerts.append(
            Alert(
                summary=alert.get("summary"),
                cleared_reason=alert.get("clearedReason"),
                created_at=alert.get("createdAt"),
                priority=alert.get("priority"),
                updated_at=alert.get("updatedAt"),
                device_type=alert.get("deviceType"),
                updated_by=alert.get("updatedBy"),
                name=alert.get("name"),
                status=alert.get("status"),
                category=alert.get("category"),
                severity=alert.get("severity"),
            )
        )
    return cleaned_alerts
