"""Report status graph. Kept free of model imports so it is trivially testable."""

# Status values are spelled out (not Report.Status) to avoid a circular import with models.
ALLOWED: dict[str, frozenset[str]] = {
    "draft": frozenset({"pending", "withdrawn"}),
    "pending": frozenset({"approved", "rejected", "needs_info", "merged"}),
    "needs_info": frozenset({"pending", "rejected", "withdrawn"}),
    "approved": frozenset({"rejected", "merged"}),  # approved -> rejected only via appeal/reopen
    "rejected": frozenset({"pending"}),  # moderator reopen
    "merged": frozenset(),
    "withdrawn": frozenset(),
}


class InvalidTransition(Exception):
    pass


def check_transition(src: str, dst: str) -> None:
    if dst not in ALLOWED.get(src, frozenset()):
        raise InvalidTransition(f"{src} -> {dst} is not allowed")
