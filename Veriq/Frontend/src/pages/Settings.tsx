import React, { useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  KeyRound,
  Server,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { useApiResource } from '../hooks/useApiResource';
import { ApiError, api, API_BASE_URL, API_ROOT } from '../api/client';
import {
  ErrorState,
  LoadingState,
  PageHeader,
  Pill,
  SectionCard,
  StatusBadge,
} from '../components/ui';

const ENDPOINTS: Array<{ method: string; path: string; auth: string; purpose: string }> = [
  { method: 'GET', path: '/applications', auth: 'none', purpose: 'List registered applications' },
  { method: 'POST', path: '/applications', auth: 'none', purpose: 'Register an application (returns API key once)' },
  { method: 'POST', path: '/applications/{id}/api-key', auth: 'none', purpose: 'Rotate the API key' },
  { method: 'DELETE', path: '/applications/{id}', auth: 'none', purpose: 'Delete an application' },
  { method: 'GET', path: '/registered-tasks', auth: 'none', purpose: 'Task catalog with aggregates' },
  { method: 'PATCH', path: '/registered-tasks/{id}/observation', auth: 'none', purpose: 'Enable/disable telemetry per task' },
  { method: 'GET', path: '/workers', auth: 'none', purpose: 'Worker inventory and queues' },
  { method: 'GET', path: '/task-executions', auth: 'none', purpose: 'Execution history' },
  { method: 'GET', path: '/task-executions/{id}', auth: 'none', purpose: 'Execution with its event timeline' },
  { method: 'GET', path: '/experiments', auth: 'none', purpose: 'Experiment definitions' },
  { method: 'POST', path: '/tasks/discovery', auth: 'X-API-Key', purpose: 'SDK task discovery' },
  { method: 'POST', path: '/workers/events', auth: 'X-API-Key', purpose: 'SDK worker lifecycle + queues' },
  { method: 'POST', path: '/task-executions/events', auth: 'X-API-Key', purpose: 'SDK execution lifecycle events' },
  { method: 'POST', path: '/experiments/{id}/runs', auth: 'X-API-Key', purpose: 'Runner creates a run' },
  { method: 'GET', path: '/experiment-runs/{id}/events', auth: 'X-API-Key', purpose: 'Runner/SDK experiment events' },
];

export const Settings: React.FC = () => {
  const loadHealth = useCallback(async () => {
    try {
      return await api.health();
    } catch (cause) {
      // /health returns 503 with a body when the database is unavailable; that
      // is still useful status information for this page rather than an error.
      if (cause instanceof ApiError && cause.status === 503) {
        return { status: 'degraded', database: 'unavailable' };
      }
      throw cause;
    }
  }, []);

  const { data: health, loading, error, reload } = useApiResource(loadHealth);

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-5xl w-full mx-auto space-y-6">
        <PageHeader
          title="Workspace & Connection"
          description="VeriQ has no user accounts or persisted dashboard preferences yet. This page shows the connection this dashboard is using and what the backend currently supports."
          actions={
            <a
              href={`${API_BASE_URL}/docs`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] rounded-lg hover:bg-[#EFEEE7] transition-colors"
            >
              OpenAPI docs <ExternalLink className="w-3.5 h-3.5" />
            </a>
          }
        />

        <SectionCard
          title="Backend connection"
          description="Resolved from VITE_API_URL, falling back to the local development backend"
          icon={<Server className="w-4 h-4 text-[#8297AC]" />}
          actions={
            <button
              onClick={reload}
              className="text-xs font-medium text-[#5f745b] hover:text-[#343832]"
            >
              Re-check
            </button>
          }
        >
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7] min-w-0">
                <span className="text-[11px] text-[#777A72] block">Base URL</span>
                <span className="font-mono text-[11.5px] text-[#343832] break-all">{API_BASE_URL}</span>
              </div>
              <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7] min-w-0">
                <span className="text-[11px] text-[#777A72] block">API root</span>
                <span className="font-mono text-[11.5px] text-[#343832] break-all">{API_ROOT}</span>
              </div>
            </div>

            {loading && !health ? (
              <LoadingState label="Checking /api/v1/health…" />
            ) : error ? (
              <ErrorState message={error} onRetry={reload} />
            ) : (
              <div className="flex flex-wrap items-center gap-3 p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7]">
                <span className="text-[11px] text-[#777A72] flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5" /> Database
                </span>
                <StatusBadge
                  status={health?.database === 'connected' ? 'ONLINE' : 'OFFLINE'}
                  label={health?.database ?? 'unknown'}
                />
                <span className="text-[11px] text-[#777A72] ml-auto font-mono">
                  /api/v1/health → {health?.status ?? 'unknown'}
                </span>
              </div>
            )}

            <p className="text-[11px] text-[#777A72] leading-relaxed">
              If the dashboard reports a network error, confirm the backend is running and that{' '}
              <span className="font-mono">VITE_API_URL</span> (or the backend{' '}
              <span className="font-mono">CORS_ORIGINS</span>) allows this origin.
            </p>
          </div>
        </SectionCard>

        <SectionCard
          title="Authentication model"
          description="How the dashboard and the SDK authenticate today"
          icon={<ShieldCheck className="w-4 h-4 text-[#879B83]" />}
        >
          <div className="space-y-3 text-xs text-[#61655b] leading-relaxed">
            <div className="p-3 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg">
              <span className="font-semibold text-[#343832] flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5 text-[#8297AC]" /> SDK ingestion
              </span>
              <p className="mt-1">
                Every SDK write uses <span className="font-mono">X-API-Key</span>. The key is scoped to one
                target application, stored as a SHA-256 hash, shown once on creation or rotation, and never
                persisted by this dashboard.
              </p>
            </div>
            <div className="p-3 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg">
              <span className="font-semibold text-[#343832] flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-[#A46F70]" /> Dashboard reads
              </span>
              <p className="mt-1">
                Control reads (applications, tasks, workers, executions, experiments) are currently
                unauthenticated in the backend. There are no user accounts, sessions, teams or per-user
                scoping, so this dashboard does not offer sign-in or access control.
              </p>
            </div>
          </div>
        </SectionCard>

        <SectionCard
          title="API surface"
          description="Endpoints this dashboard uses or documents"
          icon={<Terminal className="w-4 h-4 text-[#8297AC]" />}
          bodyClassName="p-0"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#FAF8F3] text-[10px] uppercase tracking-wider text-[#777A72]">
                <tr>
                  <th className="px-5 py-2.5 font-semibold">Method</th>
                  <th className="px-3 py-2.5 font-semibold">Path</th>
                  <th className="px-3 py-2.5 font-semibold">Auth</th>
                  <th className="px-3 py-2.5 font-semibold">Purpose</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E5E1D7]">
                {ENDPOINTS.map((endpoint) => (
                  <tr key={`${endpoint.method}-${endpoint.path}`} className="bg-white">
                    <td className="px-5 py-2 font-mono text-[10.5px] text-[#52564e]">{endpoint.method}</td>
                    <td className="px-3 py-2 font-mono text-[10.5px] text-[#343832]">{endpoint.path}</td>
                    <td className="px-3 py-2">
                      <Pill tone={endpoint.auth === 'none' ? 'muted' : 'beige'}>{endpoint.auth}</Pill>
                    </td>
                    <td className="px-3 py-2 text-[#61655b]">{endpoint.purpose}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard
          title="Not yet supported"
          description="Capabilities intentionally absent from the current backend"
          icon={<CheckCircle2 className="w-4 h-4 text-[#777A72]" />}
        >
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-[#61655b]">
            {[
              'User accounts, sign-in and teams',
              'Dashboard run listing per experiment',
              'Failure injection and runner control',
              'Invariant verification results',
              'Worker restart / stop / kill operations',
              'Task activation or scheduling controls',
              'Alerts, notifications and retention settings',
              'Non-Celery queue integrations',
            ].map((item) => (
              <li key={item} className="p-2.5 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg">
                {item}
              </li>
            ))}
          </ul>
          <Link
            to="/integration"
            className="inline-flex items-center gap-1.5 mt-3 text-xs font-medium text-[#5f745b] hover:text-[#343832]"
          >
            <Terminal className="w-3.5 h-3.5" /> SDK integration guide
          </Link>
        </SectionCard>
      </div>
    </Layout>
  );
};

export default Settings;
