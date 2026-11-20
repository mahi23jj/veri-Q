# VeriQ reliability-test planning engine

This stage adds **planning** to VeriQ: a developer can describe how a registered
Celery task can be tested safely, select reusable failure scenarios, run a
deterministic compatibility check, generate a reproducible scenario matrix and
approve a test plan revision.

It does **not** execute anything. There is no isolated runner, no failure
injection, no worker termination, no broker manipulation and no task
scheduling. Approval authorises a plan for the future runner; it never starts,
pauses or modifies the target application.

## 1. Boundaries that are preserved

| Concern | Where it lives | Unchanged by this stage |
|---|---|---|
| Ordinary task telemetry | `task_executions`, `execution_events` | Stored exactly as before; no experiment or plan required |
| Checkpoint reporting | `veriq.checkpoint(...)` → `TASK_CHECKPOINT` event | Still report-only, never blocks or pauses a task |
| Execution status vs verdict | `task_executions.status` / `experiment_runs.verdict` | Still independent |
| Experiment evidence | `experiments`, `experiment_runs`, `experiment_events` | Not modified; plans do not write experiment events |
| Task discovery | `registered_tasks` (SDK/Celery) | The single task registry; checkpoints attach to it |

Checkpoint discovery is additive planning metadata: the same SDK event is
stored as telemetry, and the backend additionally upserts a
`task_checkpoints` row. Reliability configuration is never read while handling
a normal checkpoint event, so it cannot affect production execution.

## 2. Data model (migration `0004_planning`)

All tables use UUID primary keys and are scoped to `target_apps`.

| Table | Purpose | Key constraints |
|---|---|---|
| `task_checkpoints` | Discovered checkpoint of one task | UNIQUE `(registered_task_id, name)`; `first_seen_at`, `last_seen_at`, `report_count`, bounded `checkpoint_metadata`, `reliability_enabled` |
| `task_scenario_selections` | Task-level automatic scenario opt-in/opt-out | UNIQUE `(registered_task_id, scenario_id)` |
| `checkpoint_scenario_selections` | Scenario enabled at one checkpoint + assertion overrides | UNIQUE `(checkpoint_id, scenario_id)` |
| `task_test_contracts` | Active contract for one task | UNIQUE `registered_task_id`; `version`, `payload`, `validation` |
| `task_test_contract_versions` | Immutable contract revisions | UNIQUE `(contract_id, version)` |
| `adapter_definitions` | Custom adapter type metadata | UNIQUE `(target_app_id, slug)` |
| `application_adapters` | Adapter configured for an application | UNIQUE `(target_app_id, name)`; `status` in `CONFIGURED/VALIDATED/INVALID` |
| `test_plans` | Reviewable plan | `status` in `DRAFT/VALIDATING/NEEDS_CHANGES/READY_FOR_REVIEW/APPROVED`; `current_revision`, `approved_revision` |
| `test_plan_revisions` | Immutable matrix revision + configuration snapshot | UNIQUE `(test_plan_id, revision)`; `approved_at`, `invalidated_at` |
| `test_plan_test_cases` | Generated matrix rows | UNIQUE `(test_plan_revision_id, case_key)`; `status` in `READY/BLOCKED` |

## 3. Task Test Contract

A contract belongs to one registered task and is reusable across experiments and
plans. Updating it appends a version; historical plans keep referencing the
version they were generated from.

```json
{
  "safe_input": { "document_id": "test-document-001" },
  "input_fixture_ref": null,
  "effect_measurements": [
    {
      "id": "documents_row",
      "description": "Rows owned by this test document",
      "adapter_id": "<configured database adapter id>",
      "measurement_type": "row_count",
      "config": { "table": "documents", "where": { "document_id": "test-document-001" } },
      "authoritative": true
    }
  ],
  "assertions": [
    {
      "id": "exactly_one_document",
      "description": "Exactly one document row exists after retries",
      "type": "effect_count",
      "measurement_id": "documents_row",
      "expected": 1
    },
    {
      "id": "terminal_state",
      "description": "The execution reaches a terminal state",
      "type": "execution_status",
      "expected": "SUCCEEDED"
    }
  ],
  "cleanup": {
    "mode": "adapter_managed",
    "adapter_id": "<configured storage/database adapter id>",
    "resource_scope": "test_owned",
    "description": "Delete rows and objects created for this document"
  },
  "notes": "Test data uses the test-document- prefix."
}
```

Rules enforced:

* `safe_input` is structured JSON only, at most 50 keys, depth 5 and ~8 KB; keys
  that look like credentials (`password`, `secret`, `token`, `api_key`, ...) are
  rejected. Contracts never store secrets — adapters use an opaque
  `configuration_ref` instead.
* Assertion types are a closed set — `effect_exists`, `effect_count`,
  `effect_absent`, `effect_value`, `execution_status`. There is no expression
  evaluator. Measurement-backed assertions must reference a declared
  measurement; descriptive expectations belong in `description`/`notes`.
* A measurement's adapter must be configured for the application and declare
  the `effect_measurement` capability.
* `adapter_managed` cleanup requires an adapter declaring `resource_cleanup`, and
  the scope is fixed to `test_owned`.
* One active contract per task (`409` on a second create; `PATCH` versions it).
* Saving a contract never executes the task.

## 4. Adapter registry

An adapter **type** is what VeriQ supports; a configured adapter is a row for one
application; `VALIDATED` means the configuration metadata is complete — never
that connectivity or injection is proven. The compatibility engine additionally
checks whether the adapter can satisfy the specific scenario.

| Type | Category | Capabilities | Declared triggers |
|---|---|---|---|
| `http` | http | `dependency_observation`, `failure_trigger`, `effect_measurement`, `environment_validation` | `timeout_simulation`, `lost_response_simulation` |
| `database` | database | `environment_validation`, `fixture_preparation`, `effect_measurement`, `failure_trigger` | `connection_interruption` |
| `broker` | broker | `environment_validation`, `dependency_observation`, `failure_trigger` | `duplicate_delivery` |
| `object_storage` | storage | `environment_validation`, `fixture_preparation`, `effect_measurement`, `resource_cleanup` | — |
| custom | any | declared by the application (subset of known capabilities) | declared by the application |

Validation returns machine-readable checks, including
`connectivity_verification: false / deferred_to_runner` and
`"operational": false`. Changing an adapter's triggers or reference resets it to
`CONFIGURED`.

## 5. Scenario catalogue (`2026.11`, all `PLANNING_ONLY`)

Scenarios describe general failure patterns and never contain business logic or
task names.

| Scenario | Category | Modes | Requires |
|---|---|---|---|
| `dependency_timeout` | dependency | automatic | HTTP adapter + `timeout_simulation`; safe input; assertions. Effect measurement optional (warning) |
| `successful_operation_lost_response` | dependency | automatic | HTTP adapter + `lost_response_simulation`; safe input; **authoritative** effect measurement; assertions |
| `duplicate_message_delivery` | messaging | automatic, checkpoint | broker adapter + `duplicate_delivery`; safe input; **authoritative** measurement; assertions |
| `database_connection_interruption` | database | automatic, checkpoint | database adapter + `connection_interruption`; safe input; assertions; measurement optional |
| `worker_termination` | runtime | automatic, checkpoint | broker adapter with `dependency_observation`; safe input. Warns that redelivery depends on Celery acknowledgement settings |

Each definition also declares preconditions, a configuration schema (validated
with a small declarative validator), applicable task conditions, measurement
requirements and expected recovery characteristics.

## 6. Checkpoints and configuration inheritance

* Checkpoint identity is `(registered_task_id, name)`; the same name in two tasks
  is two checkpoints. Repeated reports increment `report_count` and refresh
  `last_seen_at`; every checkpoint event is also stored as ordinary telemetry.
* `reliability_enabled` is planning configuration only. A checkpoint-triggered
  scenario requires it; nothing else reads it.
* Automatic selections: a stored row always wins (including opt-out). Without a
  row, a scenario is recommended and enabled **only if currently COMPATIBLE**.
* Checkpoint selections are opt-in and independent of automatic selections.
  Selecting a scenario at one checkpoint never changes another checkpoint or the
  task-level automatic list.
* Assertions are inherited from the contract; checkpoint
  `assertion_overrides` replace entries with the same `id` and add new ones.
  The contract never has to be repeated per checkpoint.

Checkpoint semantics are preserved in descriptions and matrix rows: a checkpoint
named `after_database_save` means the save already happened; `before_...` means
it has not.

## 7. Compatibility engine

Pure function in `app/domain/compatibility/engine.py`; deterministic, with
stable reason ordering.

Statuses: `COMPATIBLE`, `NEEDS_CONFIGURATION`, `UNSUPPORTED`. Severity decides the
status (`unsupported` wins over `configuration`); warnings never block.
Every result includes `execution_available: false` and an explicit note.

Example — HTTP configured with timeout injection, contract complete:

```json
{
  "status": "COMPATIBLE",
  "reasons": [
    { "code": "SCENARIO_WARNING", "severity": "warning",
      "message": "A connection timeout is not the same as a lost response; ..." }
  ],
  "selected_adapters": [
    { "adapter_id": "...", "adapter_name": "target-http", "category": "http",
      "trigger": "timeout_simulation" }
  ],
  "execution_available": false
}
```

Example — lost response selected with only timeout enabled and an advisory
measurement:

```json
{
  "status": "NEEDS_CONFIGURATION",
  "reasons": [
    { "code": "TRIGGER_CAPABILITY_NOT_ENABLED", "severity": "configuration",
      "message": "The http adapter 'target-http' does not have the 'lost_response_simulation' trigger enabled." },
    { "code": "NON_AUTHORITATIVE_MEASUREMENT", "severity": "configuration",
      "message": "The scenario needs an authoritative effect measurement ..." }
  ]
}
```

Other reason codes include `CONTRACT_MISSING`, `CONTRACT_INVALID`,
`MISSING_SAFE_INPUT`, `MISSING_ASSERTIONS`, `MISSING_EFFECT_MEASUREMENT`,
`ADAPTER_NOT_CONFIGURED`, `ADAPTER_NOT_VALIDATED`, `CHECKPOINT_NOT_ENABLED`,
`CHECKPOINT_NOT_SELECTED`, `CLEANUP_ADAPTER_NOT_CONFIGURED`,
`TRIGGER_MODE_UNSUPPORTED`, `SCENARIO_UNSUPPORTED`.

## 8. Scenario matrix

A row is task + scenario + trigger type + injection point + configuration
snapshot. Automatic and checkpoint rows differ by `trigger_type`/
`checkpoint_name`, so both are kept intentionally. Identical configurations are
deduplicated by SHA-256 fingerprint and reported in `summary.duplicates`.

Each case stores: `case_key`, task/scenario/version, trigger, checkpoint,
contract id + version, adapter refs, safe input or fixture reference, merged
assertions, cleanup, compatibility result and configuration fingerprint.
Blocked selections are kept (never silently dropped) with `status: BLOCKED`.

Revision snapshots record scenario catalogue version, per-task contract
versions, checkpoint state, adapter configuration and the generated-at
timestamp, so historical revisions stay reproducible.

## 9. Test plan lifecycle

```text
DRAFT --generate--> VALIDATING --submit--> READY_FOR_REVIEW --approve--> APPROVED
          |                                  ^                        |
          +--> NEEDS_CHANGES --------------- |                        |
                       ^                                              |
                       +------- validate (drift / blocked) ----------+
APPROVED --revoke--> READY_FOR_REVIEW
APPROVED --contract change detected by validate--> NEEDS_CHANGES (approval cleared)
```

* `generate` always creates a new immutable revision and clears any approval.
* `validate` re-evaluates the current configuration, reports `drift` (cases that
  changed or disappeared) and `blocking_issues`; drift clears approval.
* `submit` requires a valid revision; `409` for `NEEDS_CHANGES`.
* `approve` requires `READY_FOR_REVIEW`, the exact current revision number and no
  blocked cases.
* `PATCH` on plan content while approved clears approval and returns to `DRAFT`.
* `ready_for_execution` is true only for the exact approved revision;
  `execution_available` is always false in this phase.

## 10. API

| Group | Endpoints |
|---|---|
| Catalog | `GET /scenarios`, `GET /scenarios/{id}`, `GET /adapter-types` |
| Adapters | `GET/POST /applications/{app}/adapters`, `PATCH/DELETE /applications/{app}/adapters/{id}`, `POST .../validate`, `GET /applications/{app}/adapter-types`, `POST /applications/{app}/adapter-definitions` |
| Contracts | `POST/GET /applications/{app}/registered-tasks/{task}/contract`, `GET /applications/{app}/contracts`, `GET/PATCH /applications/{app}/contracts/{id}`, `POST .../validate`, `GET .../versions` |
| Checkpoints | `GET /applications/{app}/checkpoints`, `GET/PATCH .../{checkpoint}`, `GET/PUT .../{checkpoint}/scenarios/{scenario}` |
| Task selection | `GET/PUT /applications/{app}/registered-tasks/{task}/scenarios`, `GET .../reliability` |
| Compatibility | `POST /applications/{app}/compatibility/evaluate` |
| Plans | `POST/GET /applications/{app}/test-plans`, `GET/PATCH .../{plan}`, `POST .../{plan}/generate|validate|submit|approve|revoke`, `GET .../{plan}/revisions/{n}`, `GET .../revisions/{n}/test-cases` |

Every application-scoped resource is resolved against the application in the
path; foreign ids return `404` rather than leaking existence. Read/control
routes follow the existing dashboard convention (no API key); SDK ingestion
still uses `X-API-Key`.

## 11. Deferred to the runner phase

Isolated runner orchestration, Docker execution, worker lifecycle control, real
process termination, HTTP proxy injection, database outage injection, broker
duplicate delivery, scheduling, retry orchestration, checkpoint runtime control,
AI scenarios and randomized injection. The catalog already declares the
capabilities and triggers those features will consume, so the planning surface
does not need redesign.
