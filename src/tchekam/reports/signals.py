from django.dispatch import Signal

# Sent after the transaction that changed a report's status commits (never on rollback).
# Kwargs: report, from_status, to_status. Lets other apps (reputation) react without
# reports importing them.
report_status_changed = Signal()
