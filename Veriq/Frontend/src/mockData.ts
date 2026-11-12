import type { Application, Experiment, ExperimentRun, ActivityItem } from './types';

export const INITIAL_APPLICATIONS: Application[] = [
  {
    id: 'app-inv-01',
    name: 'Inventory Service',
    description: 'Manages multi-warehouse stock allocations, SKU reservations, and ledger state commits.',
    environment: 'staging',
    framework: 'Celery 5.3 (Redis Broker)',
    importPath: 'services.inventory.tasks:commit_stock_reservation',
    defaultTask: 'reserve_warehouse_sku',
    experimentCount: 6,
    createdAt: '2025-01-12',
    status: 'healthy'
  },
  {
    id: 'app-pharma-02',
    name: 'Pharmacy Backend',
    description: 'Processes digital e-prescriptions, DEA audit validations, and insurance pre-authorizations.',
    environment: 'staging',
    framework: 'BullMQ 4.12 (IORedis)',
    importPath: 'apps.rx.workers:process_rx_fulfillment',
    defaultTask: 'fulfill_digital_prescription',
    experimentCount: 4,
    createdAt: '2025-02-04',
    status: 'healthy'
  },
  {
    id: 'app-notify-03',
    name: 'Notification Service',
    description: 'High-throughput transactional SMS, urgent push broadcasts, and clinician notification fan-out.',
    environment: 'staging',
    framework: 'Sidekiq 7.2 (Dragonfly)',
    importPath: 'workers.notify:dispatch_urgent_patient_sms',
    defaultTask: 'dispatch_batch_sms',
    experimentCount: 3,
    createdAt: '2025-02-18',
    status: 'idle'
  }
];

export const INITIAL_RUNS: ExperimentRun[] = [
  {
    id: 'run-8821',
    experimentId: 'exp-inv-commit',
    experimentName: 'Crash after stock ledger commit',
    applicationId: 'app-inv-01',
    applicationName: 'Inventory Service',
    runNumber: 14,
    startTime: '2025-02-28 14:22:10',
    duration: '1.42s',
    status: 'completed',
    verdict: 'passed',
    workerNode: 'worker-inv-stg-03',
    attemptNumber: 2,
    maxAttempts: 3,
    logicalOperationId: 'tx_alloc_88194a2f',
    events: [
      {
        id: 'ev-1',
        timestamp: '14:22:10.012',
        type: 'setup',
        source: 'orchestrator',
        title: 'Sandbox harness initialized',
        description: 'Allocated isolated Redis queue queueproof-inv-sandbox and injected fault listener.',
        outcome: 'ok',
        payload: { isolated_db: 'redis://10.2.14.8/3', isolation_level: 'ephemeral' }
      },
      {
        id: 'ev-2',
        timestamp: '14:22:10.140',
        type: 'submission',
        source: 'orchestrator',
        title: 'Task enqueued with operation idempotency key',
        description: 'Submitted task reserve_warehouse_sku with operationId tx_alloc_88194a2f and items=[SKU-7721: 2].',
        outcome: 'ok',
        payload: { args: { sku: 'SKU-7721', qty: 2, customer_id: 'cust_9021' } }
      },
      {
        id: 'ev-3',
        timestamp: '14:22:10.260',
        type: 'execution',
        source: 'worker-node-1',
        title: 'Worker acquired task [Attempt 1]',
        description: 'Process pid:4102 locked job lock:tx_alloc_88194a2f and began database ledger debit.',
        outcome: 'ok'
      },
      {
        id: 'ev-4',
        timestamp: '14:22:10.420',
        type: 'checkpoint',
        source: 'worker-node-1',
        title: 'Checkpoint reached: DB_TRANSACTION_COMMITTED',
        description: 'Worker successfully executed SQL COMMIT on stock_allocations table for quantity 2.',
        outcome: 'ok',
        payload: { committed_row_id: 'alloc_row_99182', tx_state: 'COMMITTED' }
      },
      {
        id: 'ev-5',
        timestamp: '14:22:10.428',
        type: 'failure_injection',
        source: 'orchestrator',
        title: 'Simulated fault triggered: SIGKILL (Crash after commit)',
        description: 'Orchestrator intercepted checkpoint and terminated worker pid:4102 prior to queue broker ACK.',
        outcome: 'injected_fault',
        payload: { signal: 'SIGKILL', exit_code: 137, ack_sent: false }
      },
      {
        id: 'ev-6',
        timestamp: '14:22:10.950',
        type: 'redelivery',
        source: 'queue-broker',
        title: 'Broker visibility timeout expired; task redelivered',
        description: 'Unacknowledged job redelivered to available pool with redelivery_count=1.',
        outcome: 'ok'
      },
      {
        id: 'ev-7',
        timestamp: '14:22:11.080',
        type: 'execution',
        source: 'worker-node-2',
        title: 'Worker acquired redelivered task [Attempt 2]',
        description: 'Worker pid:5211 inspected logical operation ID tx_alloc_88194a2f in deduplication store.',
        outcome: 'ok'
      },
      {
        id: 'ev-8',
        timestamp: '14:22:11.390',
        type: 'verification',
        source: 'verifier',
        title: 'Invariant audit executed against warehouse ledger',
        description: 'Verified stock inventory did not double-decrement and exactly 1 reservation receipt exists.',
        outcome: 'ok'
      }
    ],
    invariants: [
      {
        id: 'inv-1',
        name: 'Single Stock Decrement Invariant',
        description: 'The ledger row must deduct exactly the requested quantity once, despite worker redelivery.',
        expected: 'Allocated count == 2 (Balance remaining: 98)',
        actual: 'Allocated count == 2 (Balance remaining: 98)',
        passed: true,
        explanation: 'Worker idemp-lock guarded database row insertion. Redelivery detected existing committed transaction ID and skipped re-execution gracefully.'
      },
      {
        id: 'inv-2',
        name: 'Idempotency Key Receipt State',
        description: 'A persisted idempotent completion record must be discoverable by calling services.',
        expected: 'Status: COMPLETED with matching operation checksum',
        actual: 'Status: COMPLETED with matching operation checksum',
        passed: true,
        explanation: 'The application persisted the receipt inside the same atomic boundary as the stock ledger change.'
      }
    ]
  },
  {
    id: 'run-8819',
    experimentId: 'exp-pharma-auth',
    experimentName: 'Crash after DEA validation pre-auth',
    applicationId: 'app-pharma-02',
    applicationName: 'Pharmacy Backend',
    runNumber: 7,
    startTime: '2025-02-28 11:05:44',
    duration: '2.18s',
    status: 'completed',
    verdict: 'failed',
    workerNode: 'worker-pharma-stg-01',
    attemptNumber: 2,
    maxAttempts: 3,
    logicalOperationId: 'rx_ord_552199b',
    events: [
      {
        id: 'ev-p1',
        timestamp: '11:05:44.008',
        type: 'setup',
        source: 'orchestrator',
        title: 'Test isolation container ready',
        description: 'Mock DEA endpoint and prescription store provisioned.',
        outcome: 'ok'
      },
      {
        id: 'ev-p2',
        timestamp: '11:05:44.200',
        type: 'submission',
        source: 'orchestrator',
        title: 'Fulfillment job queued',
        description: 'Scheduled prescription RX-4982 with patient ID P-9081.',
        outcome: 'ok'
      },
      {
        id: 'ev-p3',
        timestamp: '11:05:44.420',
        type: 'checkpoint',
        source: 'worker-node-1',
        title: 'Checkpoint reached: DEA_AUDIT_LOGGED',
        description: 'DEA audit authorization recorded in external compliance registry.',
        outcome: 'ok'
      },
      {
        id: 'ev-p4',
        timestamp: '11:05:44.430',
        type: 'failure_injection',
        source: 'orchestrator',
        title: 'Simulated fault: Worker process crashed',
        description: 'Injected host kill after external DEA call returned HTTP 200.',
        outcome: 'injected_fault'
      },
      {
        id: 'ev-p5',
        timestamp: '11:05:45.890',
        type: 'redelivery',
        source: 'queue-broker',
        title: 'Task redelivered upon timeout',
        description: 'Worker node 2 picked up the prescription retry.',
        outcome: 'ok'
      },
      {
        id: 'ev-p6',
        timestamp: '11:05:46.120',
        type: 'execution',
        source: 'worker-node-2',
        title: 'Retry called external DEA endpoint again',
        description: 'Notice: Non-idempotent HTTP request sent without deduplication header.',
        outcome: 'warning'
      },
      {
        id: 'ev-p7',
        timestamp: '11:05:46.180',
        type: 'verification',
        source: 'verifier',
        title: 'Compliance log verification failed',
        description: 'Found duplicate DEA pre-authorization records for same prescription ID.',
        outcome: 'failure'
      }
    ],
    invariants: [
      {
        id: 'inv-p1',
        name: 'Single External DEA Pre-Auth Authorization',
        description: 'The national prescription register must receive exactly one authorization record per e-prescription.',
        expected: '1 compliance record created',
        actual: '2 compliance records created (Duplicate authorization #DA-99120 and #DA-99121)',
        passed: false,
        explanation: 'Worker does not attach client idempotency tokens to the third-party DEA compliance API. Redelivery caused a duplicate pre-authorization bill and alert flag.'
      }
    ]
  },
  {
    id: 'run-8815',
    experimentId: 'exp-notify-batch',
    experimentName: 'Crash after SMS provider HTTP send',
    applicationId: 'app-notify-03',
    applicationName: 'Notification Service',
    runNumber: 3,
    startTime: '2025-02-27 18:40:12',
    duration: '3.04s',
    status: 'completed',
    verdict: 'failed',
    workerNode: 'worker-sms-04',
    attemptNumber: 2,
    maxAttempts: 3,
    logicalOperationId: 'sms_batch_1192',
    events: [
      {
        id: 'ev-s1',
        timestamp: '18:40:12.000',
        type: 'setup',
        source: 'orchestrator',
        title: 'Mock SMS gateway wired',
        description: 'Ready to observe Twilio mock webhook acknowledgments.',
        outcome: 'ok'
      },
      {
        id: 'ev-s2',
        timestamp: '18:40:12.300',
        type: 'checkpoint',
        source: 'worker-node-1',
        title: 'Checkpoint reached: HTTP_PAYLOAD_DISPATCHED',
        description: 'External provider confirmed 202 Accepted for 1 SMS.',
        outcome: 'ok'
      },
      {
        id: 'ev-s3',
        timestamp: '18:40:12.310',
        type: 'failure_injection',
        source: 'orchestrator',
        title: 'Simulated fault: Process killed prior to database status update',
        description: 'Database status remained PENDING despite external send.',
        outcome: 'injected_fault'
      },
      {
        id: 'ev-s4',
        timestamp: '18:40:14.200',
        type: 'redelivery',
        source: 'queue-broker',
        title: 'Task redelivered to worker 2',
        description: 'Worker 2 resent the SMS to end-user phone number +1-555-0192.',
        outcome: 'warning'
      }
    ],
    invariants: [
      {
        id: 'inv-s1',
        name: 'Patient Message Frequency Cap',
        description: 'Patients must never receive duplicate urgent dispatch alerts within 15 minutes.',
        expected: '1 outbound SMS delivered to +1-555-0192',
        actual: '2 outbound SMS delivered to +1-555-0192',
        passed: false,
        explanation: 'Worker failed to persist the external message SID before queue ACK. Redelivery caused duplicate SMS delivery.'
      }
    ]
  },
  {
    id: 'run-8810',
    experimentId: 'exp-inv-commit',
    experimentName: 'Crash after stock ledger commit',
    applicationId: 'app-inv-01',
    applicationName: 'Inventory Service',
    runNumber: 13,
    startTime: '2025-02-26 09:12:02',
    duration: '1.38s',
    status: 'completed',
    verdict: 'passed',
    workerNode: 'worker-inv-stg-01',
    attemptNumber: 2,
    maxAttempts: 3,
    logicalOperationId: 'tx_alloc_771800a',
    events: [],
    invariants: [
      {
        id: 'inv-8810-1',
        name: 'Single Stock Decrement Invariant',
        description: 'Stock deductions must be strictly idempotent under redelivery.',
        expected: 'Single ledger mutation confirmed',
        actual: 'Single ledger mutation confirmed',
        passed: true,
        explanation: 'Unique constraint on operation_id in Postgres prevented second commit.'
      }
    ]
  },
  {
    id: 'run-8802',
    experimentId: 'exp-inv-timeout',
    experimentName: 'Worker lock expiry during long reindex',
    applicationId: 'app-inv-01',
    applicationName: 'Inventory Service',
    runNumber: 2,
    startTime: '2025-02-25 16:30:19',
    duration: '5.10s',
    status: 'completed',
    verdict: 'inconclusive',
    workerNode: 'worker-inv-stg-02',
    attemptNumber: 1,
    maxAttempts: 2,
    logicalOperationId: 'idx_run_4911',
    events: [],
    invariants: [
      {
        id: 'inv-inc-1',
        name: 'Index State Coherence',
        description: 'Search index documents match primary datastore.',
        expected: 'Index sync score == 1.0',
        actual: 'Index sync score == 0.84 (Partial sync detected before timeout)',
        passed: false,
        explanation: 'Task timed out before verification probe completed. Test verdict inconclusive due to incomplete telemetry trace.'
      }
    ]
  },
  {
    id: 'run-8795',
    experimentId: 'exp-notify-batch',
    experimentName: 'Crash after SMS provider HTTP send',
    applicationId: 'app-notify-03',
    applicationName: 'Notification Service',
    runNumber: 2,
    startTime: '2025-02-24 13:00:15',
    duration: '0.40s',
    status: 'completed',
    verdict: 'cancelled',
    workerNode: 'worker-sms-01',
    attemptNumber: 1,
    maxAttempts: 3,
    logicalOperationId: 'sms_batch_1180',
    events: [],
    invariants: []
  }
];

export const INITIAL_EXPERIMENTS: Experiment[] = [
  {
    id: 'exp-inv-commit',
    name: 'Crash after stock ledger commit',
    applicationId: 'app-inv-01',
    applicationName: 'Inventory Service',
    task: 'services.inventory.tasks:commit_stock_reservation',
    status: 'active',
    failureScenario: 'Crash after commit',
    checkpoint: 'DB_TRANSACTION_COMMITTED',
    logicalOperationIdTemplate: 'tx_alloc_{uuid}',
    timeoutSeconds: 15,
    environment: 'staging',
    description: 'Simulates worker host abrupt termination (SIGKILL) right after SQL COMMIT succeeded but before Redis broker task acknowledgment.',
    lastRun: {
      date: '2025-02-28 14:22',
      verdict: 'passed',
      runId: 'run-8821'
    },
    totalRuns: 14,
    createdAt: '2025-01-15'
  },
  {
    id: 'exp-pharma-auth',
    name: 'Crash after DEA validation pre-auth',
    applicationId: 'app-pharma-02',
    applicationName: 'Pharmacy Backend',
    task: 'apps.rx.workers:process_rx_fulfillment',
    status: 'active',
    failureScenario: 'Crash after commit',
    checkpoint: 'DEA_AUDIT_LOGGED',
    logicalOperationIdTemplate: 'rx_ord_{uuid}',
    timeoutSeconds: 20,
    environment: 'staging',
    description: 'Assesses whether duplicate DEA billing entries or double prescription fulfillment occur if the worker dies after outbound HTTP dispatch.',
    lastRun: {
      date: '2025-02-28 11:05',
      verdict: 'failed',
      runId: 'run-8819'
    },
    totalRuns: 7,
    createdAt: '2025-02-05'
  },
  {
    id: 'exp-notify-batch',
    name: 'Crash after SMS provider HTTP send',
    applicationId: 'app-notify-03',
    applicationName: 'Notification Service',
    task: 'workers.notify:dispatch_urgent_patient_sms',
    status: 'active',
    failureScenario: 'Crash after commit',
    checkpoint: 'HTTP_PAYLOAD_DISPATCHED',
    logicalOperationIdTemplate: 'sms_batch_{uuid}',
    timeoutSeconds: 10,
    environment: 'staging',
    description: 'Validates that patient phones do not receive duplicate SMS alerts when workers die before local state syncs with carrier receipt.',
    lastRun: {
      date: '2025-02-27 18:40',
      verdict: 'failed',
      runId: 'run-8815'
    },
    totalRuns: 3,
    createdAt: '2025-02-20'
  },
  {
    id: 'exp-inv-timeout',
    name: 'Worker lock expiry during long reindex',
    applicationId: 'app-inv-01',
    applicationName: 'Inventory Service',
    task: 'services.inventory.tasks:reindex_warehouse_skus',
    status: 'active',
    failureScenario: 'Crash after commit',
    checkpoint: 'INDEX_CHUNK_WRITTEN',
    logicalOperationIdTemplate: 'idx_run_{uuid}',
    timeoutSeconds: 30,
    environment: 'staging',
    lastRun: {
      date: '2025-02-25 16:30',
      verdict: 'inconclusive',
      runId: 'run-8802'
    },
    totalRuns: 2,
    createdAt: '2025-02-22',
    description: 'Investigates race conditions if distributed lock lease lapses while child items are half-indexed.'
  },
  {
    id: 'exp-pharma-audit-draft',
    name: 'Controlled network partition during narcotics check',
    applicationId: 'app-pharma-02',
    applicationName: 'Pharmacy Backend',
    task: 'apps.rx.workers:verify_controlled_substances',
    status: 'draft',
    failureScenario: 'Crash after commit',
    checkpoint: 'AUDIT_RECORD_PENDING',
    logicalOperationIdTemplate: 'rx_narc_{uuid}',
    timeoutSeconds: 15,
    environment: 'development',
    totalRuns: 0,
    createdAt: '2025-02-27',
    description: 'Draft configuration for investigating database disconnect handling when narcotics validation is in-flight.'
  }
];

export const INITIAL_ACTIVITIES: ActivityItem[] = [
  {
    id: 'act-1',
    timestamp: 'Today at 14:22',
    title: 'Run #14 finished for "Crash after stock ledger commit"',
    description: 'All 2 invariant verifications passed. Database ledger deduplication held true under simulated worker crash.',
    type: 'run_completed',
    entityId: 'run-8821',
    badge: { label: 'Passed', verdict: 'passed' }
  },
  {
    id: 'act-2',
    timestamp: 'Today at 11:05',
    title: 'Run #7 finished for "Crash after DEA validation pre-auth"',
    description: 'Invariant violation detected: duplicate DEA external compliance record created on redelivery.',
    type: 'run_completed',
    entityId: 'run-8819',
    badge: { label: 'Failed', verdict: 'failed' }
  },
  {
    id: 'act-3',
    timestamp: 'Yesterday at 18:40',
    title: 'Run #3 finished for "Crash after SMS provider HTTP send"',
    description: 'Duplicate patient SMS dispatch occurred following worker redelivery.',
    type: 'run_completed',
    entityId: 'run-8815',
    badge: { label: 'Failed', verdict: 'failed' }
  },
  {
    id: 'act-4',
    timestamp: 'Yesterday at 15:10',
    title: 'Draft experiment saved',
    description: 'New draft "Controlled network partition during narcotics check" created for Pharmacy Backend.',
    type: 'draft_saved',
    entityId: 'exp-pharma-audit-draft'
  },
  {
    id: 'act-5',
    timestamp: 'Feb 26 at 09:12',
    title: 'Application registered: Notification Service',
    description: 'Target worker pool configured using Sidekiq 7.2 on Dragonfly Redis.',
    type: 'application_added',
    entityId: 'app-notify-03'
  }
];