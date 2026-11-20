"""Adapter type catalogue.

An adapter *type* is what VeriQ supports. An application-configured adapter is
a row that uses one of these types (or an application-defined custom type).

Capabilities are declarative: an adapter type advertises what it could do, not
what it currently proves. Registration of an adapter never makes it
operational — see :mod:`app.services.adapter_registry_service`.
"""

from __future__ import annotations

from dataclasses import dataclass

CAPABILITY_DEPENDENCY_OBSERVATION = "dependency_observation"
CAPABILITY_FAILURE_TRIGGER = "failure_trigger"
CAPABILITY_EFFECT_MEASUREMENT = "effect_measurement"
CAPABILITY_FIXTURE_PREPARATION = "fixture_preparation"
CAPABILITY_RESOURCE_CLEANUP = "resource_cleanup"
CAPABILITY_ENVIRONMENT_VALIDATION = "environment_validation"

ADAPTER_CAPABILITIES: tuple[str, ...] = (
    CAPABILITY_DEPENDENCY_OBSERVATION,
    CAPABILITY_FAILURE_TRIGGER,
    CAPABILITY_EFFECT_MEASUREMENT,
    CAPABILITY_FIXTURE_PREPARATION,
    CAPABILITY_RESOURCE_CLEANUP,
    CAPABILITY_ENVIRONMENT_VALIDATION,
)

ADAPTER_CATEGORIES: tuple[str, ...] = ("http", "database", "broker", "storage", "custom")


@dataclass(frozen=True)
class AdapterTypeDefinition:
    """One adapter type supported by VeriQ (built-in or custom)."""

    slug: str
    name: str
    category: str
    description: str
    capabilities: tuple[str, ...]
    supported_triggers: tuple[str, ...] = ()
    version: str = "1.0"
    builtin: bool = True

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "supported_triggers": list(self.supported_triggers),
            "version": self.version,
            "builtin": self.builtin,
        }


BUILTIN_ADAPTER_TYPES: tuple[AdapterTypeDefinition, ...] = (
    AdapterTypeDefinition(
        slug="http",
        name="HTTP dependency adapter",
        category="http",
        description=(
            "Observes outgoing HTTP calls and declares timeout / lost-response "
            "fault injection. Actual proxying is implemented by the future runner."
        ),
        capabilities=(
            CAPABILITY_DEPENDENCY_OBSERVATION,
            CAPABILITY_FAILURE_TRIGGER,
            CAPABILITY_EFFECT_MEASUREMENT,
            CAPABILITY_ENVIRONMENT_VALIDATION,
        ),
        supported_triggers=("timeout_simulation", "lost_response_simulation"),
    ),
    AdapterTypeDefinition(
        slug="database",
        name="Database adapter",
        category="database",
        description=(
            "Validates a test database target, prepares fixtures, measures row "
            "effects and declares connection-interruption injection."
        ),
        capabilities=(
            CAPABILITY_ENVIRONMENT_VALIDATION,
            CAPABILITY_FIXTURE_PREPARATION,
            CAPABILITY_EFFECT_MEASUREMENT,
            CAPABILITY_FAILURE_TRIGGER,
        ),
        supported_triggers=("connection_interruption",),
    ),
    AdapterTypeDefinition(
        slug="broker",
        name="Broker adapter",
        category="broker",
        description=(
            "Observes message delivery/acknowledgement configuration and declares "
            "duplicate-delivery injection. Redelivery is never assumed: the ack "
            "policy is recorded as a precondition."
        ),
        capabilities=(
            CAPABILITY_ENVIRONMENT_VALIDATION,
            CAPABILITY_DEPENDENCY_OBSERVATION,
            CAPABILITY_FAILURE_TRIGGER,
        ),
        supported_triggers=("duplicate_delivery",),
    ),
    AdapterTypeDefinition(
        slug="object_storage",
        name="Object storage adapter",
        category="storage",
        description=(
            "Inspects objects written to a test bucket, measures storage effects "
            "and cleans up test-owned objects."
        ),
        capabilities=(
            CAPABILITY_ENVIRONMENT_VALIDATION,
            CAPABILITY_FIXTURE_PREPARATION,
            CAPABILITY_EFFECT_MEASUREMENT,
            CAPABILITY_RESOURCE_CLEANUP,
        ),
    ),
)


def adapter_type(slug: str) -> AdapterTypeDefinition | None:
    """Return the built-in type with ``slug``, or ``None``."""
    for definition in BUILTIN_ADAPTER_TYPES:
        if definition.slug == slug:
            return definition
    return None
