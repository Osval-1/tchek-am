from .models import AuditLog


def audit(actor, action, obj=None, ip=None, **meta) -> AuditLog:
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=obj._meta.label_lower if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        metadata=meta,
        ip=ip,
    )
