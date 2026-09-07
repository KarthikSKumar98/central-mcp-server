from scripts.measure_tool_tokens import measure


def test_tool_descriptions_stay_within_hard_budget() -> None:
    over_budget = [
        f"{cost.name}: {cost.description_tokens} tokens"
        for cost in measure()
        if cost.description_tokens > 200
    ]
    assert not over_budget, "Tool descriptions exceed 200 tokens:\n" + "\n".join(
        over_budget
    )
