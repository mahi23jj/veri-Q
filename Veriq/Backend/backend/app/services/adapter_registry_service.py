"""Adapter registry: supported types, application configuration, validation.

The registry deliberately distinguishes four things:

* adapter *type* supported by VeriQ (code catalogue or a registered custom type),
* adapter *configured* for an application (a row exists),
* adapter *available* in the test environment (``status == VALIDATED``),
* adapter *capable* of satisfying a scenario (compatibility engine).

Configuration validation checks metadata only. It never contacts an external
system, so ``VALIDATED`` means "well-formed configuration", not "connectivity
proven". Operational verification belongs to the future runner.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.adapters.catalog import ADAPTER_CAPABILITIES, AdapterTypeDefinition, adapter_type
from app.models import AdapterDefinition, ApplicationAdapter, TargetApp
from app.schemas.planning import AdapterCreate, AdapterDefinitionCreate, AdapterUpdate


class AdapterTypeNotFoundError(Exception):
    pass


class AdapterNotFoundError(Exception):
    pass


class DuplicateAdapterNameError(Exception):
    pass


class DuplicateAdapterTypeError(Exception):
    pass


class InvalidAdapterConfigurationError(Exception):
    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _custom_definition(row: AdapterDefinition) -> AdapterTypeDefinition:
    return AdapterTypeDefinition(
        slug=row.slug,
        name=row.name,
        category=row.category,
        description=row.description or "",
        capabilities=tuple(row.capabilities or []),
        supported_triggers=tuple(row.supported_triggers or []),
        version=row.version,
        builtin=False,
    )


def list_adapter_types(
    db: Session, *, target_app_id: uuid.UUID | None = None
) -> list[AdapterTypeDefinition]:
    """Built-in types plus (optionally) one application's custom types."""
    from app.domain.adapters.catalog import BUILTIN_ADAPTER_TYPES

    definitions = list(BUILTIN_ADAPTER_TYPES)
    if target_app_id is not None:
        rows = db.scalars(
            select(AdapterDefinition)
            .where(AdapterDefinition.target_app_id == target_app_id)
            .order_by(AdapterDefinition.slug)
        ).all()
        definitions.extend(_custom_definition(row) for row in rows)
    return definitions


def resolve_adapter_type(
    db: Session, target_app_id: uuid.UUID, slug: str
) -> AdapterTypeDefinition | None:
    builtin = adapter_type(slug)
    if builtin is not None:
        return builtin
    row = db.scalar(
        select(AdapterDefinition).where(
            AdapterDefinition.target_app_id == target_app_id,
            AdapterDefinition.slug == slug,
        )
    )
    return _custom_definition(row) if row is not None else None


def register_definition(
    db: Session, target_app: TargetApp, payload: AdapterDefinitionCreate
) -> AdapterDefinition:
    """Register custom adapter type metadata for one application."""
    if adapter_type(payload.slug) is not None:
        raise DuplicateAdapterTypeError(payload.slug)
    row = AdapterDefinition(
        target_app_id=target_app.id,
        slug=payload.slug,
        name=payload.name,
        category=payload.category,
        description=payload.description,
        capabilities=list(payload.capabilities),
        supported_triggers=list(payload.supported_triggers),
        version=payload.version,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAdapterTypeError(payload.slug) from exc
    db.refresh(row)
    return row


def create_adapter(
    db: Session, target_app: TargetApp, payload: AdapterCreate
) -> ApplicationAdapter:
    definition = resolve_adapter_type(db, target_app.id, payload.adapter_type)
    if definition is None:
        raise AdapterTypeNotFoundError(payload.adapter_type)

    capabilities = (
        list(payload.capabilities) if payload.capabilities is not None else list(definition.capabilities)
    )
    issues: list[str] = []
    unknown_capabilities = sorted(set(capabilities) - set(ADAPTER_CAPABILITIES))
    if unknown_capabilities:
        issues.append(f"unknown capabilities: {', '.join(unknown_capabilities)}")
    unsupported = sorted(set(capabilities) - set(definition.capabilities))
    if unsupported:
        issues.append(
            f"adapter type '{definition.slug}' does not provide: {', '.join(unsupported)}"
        )
    bad_triggers = sorted(set(payload.enabled_triggers) - set(definition.supported_triggers))
    if bad_triggers:
        issues.append(
            f"adapter type '{definition.slug}' does not support triggers: "
            f"{', '.join(bad_triggers)}"
        )
    if issues:
        raise InvalidAdapterConfigurationError(issues)

    adapter = ApplicationAdapter(
        target_app_id=target_app.id,
        name=payload.name,
        adapter_type=definition.slug,
        category=definition.category,
        capabilities=sorted(set(capabilities)),
        enabled_triggers=sorted(set(payload.enabled_triggers)),
        configuration_ref=payload.configuration_ref,
        status="CONFIGURED",
    )
    db.add(adapter)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateAdapterNameError(payload.name) from exc
    db.refresh(adapter)
    return adapter


def get_adapter(
    db: Session, adapter_id: uuid.UUID, *, target_app_id: uuid.UUID
) -> ApplicationAdapter:
    adapter = db.get(ApplicationAdapter, adapter_id)
    if adapter is None or adapter.target_app_id != target_app_id:
        raise AdapterNotFoundError(str(adapter_id))
    return adapter


def list_adapters(db: Session, target_app_id: uuid.UUID) -> list[ApplicationAdapter]:
    return list(
        db.scalars(
            select(ApplicationAdapter)
            .where(ApplicationAdapter.target_app_id == target_app_id)
            .order_by(ApplicationAdapter.name)
        ).all()
    )


def update_adapter(
    db: Session, adapter: ApplicationAdapter, payload: AdapterUpdate
) -> ApplicationAdapter:
    definition = resolve_adapter_type(db, adapter.target_app_id, adapter.adapter_type)
    if definition is None:  # pragma: no cover - defensive; type is validated on create
        raise AdapterTypeNotFoundError(adapter.adapter_type)

    if payload.enabled_triggers is not None:
        bad = sorted(set(payload.enabled_triggers) - set(definition.supported_triggers))
        if bad:
            raise InvalidAdapterConfigurationError(
                [f"adapter type '{definition.slug}' does not support triggers: {', '.join(bad)}"]
            )
        adapter.enabled_triggers = sorted(set(payload.enabled_triggers))
    if payload.configuration_ref is not None:
        adapter.configuration_ref = payload.configuration_ref or None

    # Configuration changed: a previous validation no longer describes this row.
    adapter.status = "CONFIGURED"
    adapter.validation = None
    adapter.validated_at = None
    db.commit()
    db.refresh(adapter)
    return adapter


def validate_adapter(db: Session, adapter: ApplicationAdapter) -> ApplicationAdapter:
    """Check configuration metadata; never claim connectivity was proven."""
    checks: list[dict[str, Any]] = []
    definition = resolve_adapter_type(db, adapter.target_app_id, adapter.adapter_type)

    checks.append(
        {
            "check": "adapter_type_supported",
            "ok": definition is not None,
            "severity": "error",
            "detail": f"type '{adapter.adapter_type}'",
        }
    )
    declared_capabilities = set(adapter.capabilities or [])
    checks.append(
        {
            "check": "capabilities_declared",
            "ok": bool(declared_capabilities),
            "severity": "error",
            "detail": ", ".join(sorted(declared_capabilities)) or "none",
        }
    )
    if definition is not None:
        checks.append(
            {
                "check": "capabilities_provided_by_type",
                "ok": declared_capabilities <= set(definition.capabilities),
                "severity": "error",
                "detail": ", ".join(sorted(declared_capabilities - set(definition.capabilities)))
                or "all declared",
            }
        )
        checks.append(
            {
                "check": "triggers_supported_by_type",
                "ok": set(adapter.enabled_triggers or []) <= set(definition.supported_triggers),
                "severity": "error",
                "detail": ", ".join(sorted(adapter.enabled_triggers or [])) or "none",
            }
        )
    checks.append(
        {
            "check": "configuration_reference_present",
            "ok": bool(adapter.configuration_ref),
            "severity": "warning",
            "detail": "opaque reference only; credentials are never stored",
        }
    )
    checks.append(
        {
            "check": "connectivity_verification",
            "ok": False,
            "severity": "info",
            "detail": "deferred_to_runner: this phase validates metadata only",
        }
    )

    valid = all(check["ok"] for check in checks if check["severity"] == "error")
    adapter.validation = {
        "valid": valid,
        "checks": checks,
        "verified_at": _now().isoformat(),
        "operational": False,
        "note": "VALIDATED means the configuration is complete, not that a fault can be injected.",
    }
    adapter.status = "VALIDATED" if valid else "INVALID"
    adapter.validated_at = _now()
    db.commit()
    db.refresh(adapter)
    return adapter


def delete_adapter(db: Session, adapter: ApplicationAdapter) -> None:
    db.delete(adapter)
    db.commit()
