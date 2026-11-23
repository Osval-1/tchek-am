# Operator lookup by national-number prefix (the 9 digits after +237).
# The prefix table is transcribed from the brief and MUST be verified against the regulator's
# (ART) current numbering plan before it is relied on: allocations change over time.
_PREFIXES: dict[str, tuple[str, ...]] = {
    "MTN": ("67", *(f"65{d}" for d in range(5)), *(f"68{d}" for d in range(10))),
    "Orange": ("69", *(f"65{d}" for d in range(5, 10)), "640"),
    "Nexttel": ("66",),
    "Camtel": ("62", "2"),
}


def operator_for(e164: str) -> str:
    """Return the operator for a normalised "+237..." number, or "Unknown"."""
    national = e164.removeprefix("+237")
    for operator, prefixes in _PREFIXES.items():
        if national.startswith(prefixes):
            return operator
    return "Unknown"
