import React from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ExternalLink,
  KeyRound,
  ListChecks,
  Play,
  Server,
  Terminal,
  TriangleAlert,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useApplication } from '../context/application-context';
import { API_BASE_URL } from '../api/client';
import { CodeBlock, PageHeader, Pill, SectionCard } from '../components/ui';

const STEPS = [
  { id: 'install', label: 'Install', icon: Terminal },
  { id: 'configure', label: 'Configure', icon: KeyRound },
  { id: 'integrate', label: 'Integrate', icon: BookOpen },
  { id: 'workers', label: 'Run workers', icon: Server },
  { id: 'discovery', label: 'Discovery', icon: ListChecks },
  { id: 'executions', label: 'Executions', icon: Play },
];

const installCode = `# Inside the target application's environment
pip install "veriq[celery]"

# Or, when working from this repository:
pip install -e "Backend/sdk[celery]"`;

const configureCode = `import os
from veriq import VeriQ

veriq = VeriQ(
    api_url=os.environ["VERIQ_API_URL"],   # e.g. http://localhost:8000
    api_key=os.environ["VERIQ_API_KEY"],   # shown once at registration
    timeout=10.0,                          # optional, 0 < timeout <= 120
)`;

const envCode = `# .env — never commit this file or bake the key into an image
VERIQ_API_URL=http://localhost:8000
VERIQ_API_KEY=vq_...`;

const integrateCode = `from app.celery_app import celery_app
from veriq import VeriQ
from veriq.celery import integrate

veriq = VeriQ(
    api_url=os.environ["VERIQ_API_URL"],
    api_key=os.environ["VERIQ_API_KEY"],
)

# Install Celery signal handlers once per process.
# Safe to call twice: it returns the existing integration.
integrate(celery_app, veriq)`;

const workerCode = `# The VeriQ integration is installed by importing a module that does not
# drop privileges before Celery forks. That is why the entrypoint is a module:
#   worker.py
from app.celery_app import celery_app
from app.veriq_setup import integrate_celery

integrate_celery()           # no-op when VERIQ_API_URL/KEY are unset

celery -A app.worker worker -Q normal --concurrency=2
celery -A app.worker worker -Q veriq.test --concurrency=1 --hostname=veriq@%h`;

const checkpointCode = `from app.veriq_setup import checkpoint

def charge_order(order_id: str, amount_cents: int) -> dict:
    # ... commit business state ...
    checkpoint("payment_charged", {"order_id": order_id})
    # Report-only: never pauses, waits or terminates anything.
    return {"order_id": order_id, "charged": amount_cents}`;

const verifyCode = `# Confirmed by the SDK at startup:
#   POST /api/v1/tasks/discovery      -> registered task names
#   POST /api/v1/workers/events       -> worker start / heartbeat / shutdown
#   POST /api/v1/task-executions/events -> TASK_STARTED / SUCCEEDED / FAILED / ...
#
# Dashboard reads for these are unauthenticated:
curl -s '${API_BASE_URL}/api/v1/registered-tasks?limit=100'
curl -s '${API_BASE_URL}/api/v1/workers?limit=100'
curl -s '${API_BASE_URL}/api/v1/task-executions?limit=20'`;

export const Integration: React.FC = () => {
  const { selectedApplication, applications } = useApplication();
  const base = selectedApplication ? `/applications/${selectedApplication.id}` : '/applications';

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-5xl w-full mx-auto space-y-6">
        <PageHeader
          title="SDK Integration"
          description="Connect a Celery application to VeriQ. VeriQ is report-only: the SDK observes Celery signals and never starts, pauses or stops a worker."
          eyebrow={
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone="sage">veriq[celery]</Pill>
              <Pill tone="muted">Python 3.9+</Pill>
              <Pill tone="muted">httpx only dependency</Pill>
            </div>
          }
          actions={
            <Link
              to="/applications?action=register"
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg shadow-2xs transition-all"
            >
              <KeyRound className="w-3.5 h-3.5" /> Get an API key
            </Link>
          }
        />

        {selectedApplication ? (
          <div className="p-4 bg-[#C9D1D9]/10 border border-[#C9D1D9]/30 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
            <div>
              <span className="text-[10px] uppercase tracking-wider font-semibold text-[#B1BAC4] block">
                Integrating
              </span>
              <span className="font-serif font-bold text-base text-[#F0F6FC]">
                {selectedApplication.name}
              </span>
              <span className="text-[#B1BAC4] ml-2 font-mono">{selectedApplication.id}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                to={base}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
              >
                Open application <ArrowRight className="w-3.5 h-3.5" />
              </Link>
              <Link
                to="/applications"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
              >
                Switch application
              </Link>
            </div>
          </div>
        ) : (
          <div className="p-4 bg-[#C9D1D9]/25 border border-[#C9D1D9]/60 rounded-xl text-xs text-[#C9D1D9] flex items-start gap-2">
            <TriangleAlert className="w-4 h-4 mt-0.5 shrink-0" />
            <p>
              No application selected. Register one first — the API key is returned once by{' '}
              <span className="font-mono">POST /api/v1/applications</span>.
              {applications.length > 0 && ' Apps exist; pick one from the sidebar.'}
            </p>
          </div>
        )}

        <nav className="bg-[#000000] border border-[#30363D] rounded-xl p-3 flex flex-wrap gap-2">
          {STEPS.map((step, index) => (
            <a
              key={step.id}
              href={`#${step.id}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
            >
              <step.icon className="w-3.5 h-3.5 text-[#B1BAC4]" />
              {index + 1}. {step.label}
            </a>
          ))}
        </nav>

        <section id="install">
          <SectionCard
            title="1. Install the SDK"
            description="Optional Celery extra; the core client needs only httpx"
            icon={<Terminal className="w-4 h-4 text-[#C9D1D9]" />}
          >
            <div className="space-y-3">
              <CodeBlock code={installCode} label="bash" />
              <p className="text-xs text-[#B1BAC4] leading-relaxed">
                The SDK never reads environment variables itself — the host application passes values
                explicitly. Keep the SDK version pinned in the target application's dependencies.
              </p>
            </div>
          </SectionCard>
        </section>

        <section id="configure">
          <SectionCard
            title="2. Configure the client"
            description="Create one client per process and reuse it"
            icon={<KeyRound className="w-4 h-4 text-[#C9D1D9]" />}
          >
            <div className="space-y-3">
              <CodeBlock code={configureCode} label="python" />
              <CodeBlock code={envCode} label=".env" />
              <ul className="text-xs text-[#B1BAC4] space-y-1.5 leading-relaxed">
                <li className="flex gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#C9D1D9] mt-0.5 shrink-0" />
                  <span>
                    <span className="font-mono">api_url</span> accepts a trailing slash or{' '}
                    <span className="font-mono">/api/v1</span>; both are normalized. Credentials in the URL
                    are rejected.
                  </span>
                </li>
                <li className="flex gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#C9D1D9] mt-0.5 shrink-0" />
                  <span>
                    The key is sent only in the <span className="font-mono">X-API-Key</span> header. It is
                    redacted from <span className="font-mono">repr()</span> and every error message.
                  </span>
                </li>
                <li className="flex gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#C9D1D9] mt-0.5 shrink-0" />
                  <span>
                    Lost keys cannot be recovered. Rotate the key from the application's detail panel and
                    redeploy the environment variable.
                  </span>
                </li>
              </ul>
            </div>
          </SectionCard>
        </section>

        <section id="integrate">
          <SectionCard
            title="3. Wire Celery signals"
            description="One call per process installs task and worker reporting"
            icon={<BookOpen className="w-4 h-4 text-[#C9D1D9]" />}
          >
            <div className="space-y-3">
              <CodeBlock code={integrateCode} label="python" />
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs border border-[#30363D] rounded-lg overflow-hidden">
                  <thead className="bg-[#000000] text-[10px] uppercase tracking-wider text-[#B1BAC4]">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Celery signal</th>
                      <th className="px-3 py-2 font-semibold">VeriQ event</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#30363D]">
                    {[
                      ['task_prerun', 'TASK_STARTED'],
                      ['task_postrun (success)', 'TASK_SUCCEEDED'],
                      ['task_failure', 'TASK_FAILED'],
                      ['task_retry', 'TASK_RETRY_REQUESTED'],
                      ['worker_ready', 'WORKER_STARTED + task/queue discovery'],
                      ['heartbeat_sent (30s throttle)', 'WORKER_HEARTBEAT'],
                      ['worker_shutdown', 'WORKER_SHUTTING_DOWN'],
                    ].map(([signal, event]) => (
                      <tr key={signal} className="bg-[#000000]">
                        <td className="px-3 py-2 font-mono text-[11px] text-[#F0F6FC]">{signal}</td>
                        <td className="px-3 py-2 font-mono text-[11px] text-[#C9D1D9]">{event}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-[#B1BAC4] leading-relaxed">
                Each attempt gets its own <span className="font-mono">execution_id</span>, even when Celery
                reuses a <span className="font-mono">celery_task_id</span>. Eager calls are skipped, and
                reporting errors are logged and swallowed so monitoring can never change a task's outcome.
              </p>
            </div>
          </SectionCard>
        </section>

        <section id="workers">
          <SectionCard
            title="4. Start the application and workers"
            description="Integration must be installed before Celery forks"
            icon={<Server className="w-4 h-4 text-[#C9D1D9]" />}
          >
            <div className="space-y-3">
              <CodeBlock code={workerCode} label="bash" />
              <p className="text-xs text-[#B1BAC4] leading-relaxed">
                Use a distinct queue for experiment traffic (for example{' '}
                <span className="font-mono">veriq.test</span>) and keep{' '}
                <span className="font-mono">--concurrency=1</span> on that worker. VeriQ does not control
                which queues a worker consumes; that stays in your deployment configuration.
              </p>
              <CodeBlock code={checkpointCode} label="python — report-only checkpoints" />
            </div>
          </SectionCard>
        </section>

        <section id="discovery">
          <SectionCard
            title="5. Trigger and verify discovery"
            description="Starting an instrumented process reports task names and worker state"
            icon={<ListChecks className="w-4 h-4 text-[#C9D1D9]" />}
          >
            <div className="space-y-3">
              <p className="text-xs text-[#B1BAC4] leading-relaxed">
                There is no dashboard button to trigger discovery — it happens when the SDK starts. Import
                your Celery app and call <span className="font-mono">integrate()</span> in the API process
                and in each worker entrypoint.
              </p>
              <CodeBlock code={verifyCode} label="bash" />
              <div className="flex flex-wrap gap-2">
                <Link
                  to={`${base}/tasks`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                >
                  <ListChecks className="w-3.5 h-3.5" /> Task catalog
                </Link>
                <Link
                  to={`${base}/workers`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                >
                  <Server className="w-3.5 h-3.5" /> Workers & queues
                </Link>
                <a
                  href={`${API_BASE_URL}/docs`}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                >
                  OpenAPI docs <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            </div>
          </SectionCard>
        </section>

        <section id="executions">
          <SectionCard
            title="6. See execution events"
            description="Run a task and follow its lifecycle in the dashboard"
            icon={<Play className="w-4 h-4 text-[#C9D1D9]" />}
          >
            <div className="space-y-3 text-xs text-[#B1BAC4] leading-relaxed">
              <p>
                Enqueue a task normally. When the worker picks it up,{' '}
                <span className="font-mono">TASK_STARTED</span>, optional{' '}
                <span className="font-mono">TASK_CHECKPOINT</span> and a terminal event are reported.
                Failures and retries appear as separate attempts linked by the Celery task id.
              </p>
              <div className="flex flex-wrap gap-2">
                <Link
                  to={`${base}/executions`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg"
                >
                  Open execution history <ArrowRight className="w-3.5 h-3.5" />
                </Link>
                <Link
                  to={`${base}/experiments`}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22]"
                >
                  Experiments
                </Link>
              </div>
              <div className="p-3 bg-[#000000] border border-[#30363D] rounded-lg text-[#B1BAC4]">
                Experiment runs are created by the runner through{' '}
                <span className="font-mono">POST /api/v1/experiments/&#123;id&#125;/runs</span> and require
                the application API key. The dashboard does not create or drive runs.
              </div>
            </div>
          </SectionCard>
        </section>
      </div>
    </Layout>
  );
};

export default Integration;
