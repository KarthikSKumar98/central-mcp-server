from models import App


def _flatten_experience(experience: dict | None) -> dict[str, int] | None:
    if not experience:
        return None
    return {g["name"]: g["count"] for g in experience.get("groups", [])}


def _flatten_dest_location(dest_location: list[dict] | None) -> list[str] | None:
    if not dest_location:
        return None
    return [loc["countryCode"] for loc in dest_location if loc.get("countryCode")]


def clean_app_data(raw: list[dict]) -> list[App]:
    """Map raw API app records into App models, normalizing empty strings to None."""
    result = []
    for item in raw:
        normalized = {k: (v if v != "" else None) for k, v in item.items()}
        normalized.pop("type", None)
        if "experience" in normalized:
            normalized["experience"] = _flatten_experience(normalized["experience"])
        if "destLocation" in normalized:
            normalized["destLocation"] = _flatten_dest_location(
                normalized["destLocation"]
            )
        result.append(App(**normalized))
    return result
