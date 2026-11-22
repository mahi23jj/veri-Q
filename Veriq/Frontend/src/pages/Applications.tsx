import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  Boxes,
  Plus,
  Trash2,
  KeyRound,
  ExternalLink,
  Calendar,
  ChevronRight,
  Server,
  Activity,
  Terminal,
  FlaskConical,
  ListChecks,
} from 'lucide-react';
import { Layout } from '../components/Layout';
import { RegisterAppModal } from '../components/RegisterAppModal';
import { ApiKeyModal } from '../components/ApiKeyModal';
import { ConfirmationDialog } from '../components/ConfirmationDialog';
import { EmptyState, ErrorState, LoadingState, PageHeader, Pill } from '../components/ui';
import { useApplication } from '../context/application-context';
import { api } from '../api/client';
import type { TargetApplicationWithKey } from '../api/types';
import { formatDate, shortId } from '../lib/format';

export const Applications: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    applications,
    loading,
    error,
    selectedApplication,
    selectApplication,
    reload,
  } = useApplication();

  const [isRegisterOpen, setIsRegisterOpen] = useState(false);
  const [deleting, setDeleting] = useState<{ id: string; name: string } | null>(null);
  const [rotating, setRotating] = useState<{ id: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [apiKeyState, setApiKeyState] = useState<{
    applicationName: string;
    apiKey: string;
    rotated: boolean;
  } | null>(null);

  useEffect(() => {
    if (searchParams.get('action') === 'register') {
      setIsRegisterOpen(true);
    }
  }, [searchParams]);

  const closeRegister = () => {
    setIsRegisterOpen(false);
    if (searchParams.get('action')) {
      setSearchParams({}, { replace: true });
    }
  };

  const handleCreated = async (created: TargetApplicationWithKey) => {
    closeRegister();
    await reload();
    selectApplication(created.id);
    setApiKeyState({
      applicationName: created.name,
      apiKey: created.api_key,
      rotated: false,
    });
    toast.success(`Application "${created.name}" registered`);
  };

  const handleDelete = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.deleteApplication(deleting.id);
      toast.info(`Application "${deleting.name}" removed`);
      setDeleting(null);
      await reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not delete application');
    } finally {
      setBusy(false);
    }
  };

  const handleRotate = async () => {
    if (!rotating) return;
    setBusy(true);
    try {
      const rotated = await api.rotateApiKey(rotating.id);
      setApiKeyState({
        applicationName: rotated.name,
        apiKey: rotated.api_key,
        rotated: true,
      });
      setRotating(null);
      toast.success('New API key issued — the previous key no longer works');
      await reload();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not rotate API key');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        <PageHeader
          title="Target Applications"
          description="Register each Celery application you want VeriQ to observe. An application scopes its tasks, workers, executions and experiments."
          actions={
            <button
              onClick={() => setIsRegisterOpen(true)}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg shadow-2xs transition-all active:scale-[0.98]"
            >
              <Plus className="w-4 h-4" />
              Register Application
            </button>
          }
        />

        {error && <ErrorState message={error} onRetry={() => void reload()} />}

        {loading && applications.length === 0 ? (
          <LoadingState label="Loading applications…" />
        ) : applications.length === 0 ? (
          <EmptyState
            icon={<Boxes className="w-5 h-5" />}
            title="No target applications yet"
            description="Register your first Celery application to receive an API key. Then install the SDK and start a worker to discover tasks and executions."
            action={
              <button
                onClick={() => setIsRegisterOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg transition-all"
              >
                <Plus className="w-4 h-4" /> Register Application
              </button>
            }
          />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Applications list */}
            <div className="lg:col-span-5 space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] px-1">
                Registered Applications ({applications.length})
              </h2>

              {applications.map((app) => {
                const isSelected = selectedApplication?.id === app.id;
                return (
                  <div
                    key={app.id}
                    onClick={() => selectApplication(app.id)}
                    className={`p-4 rounded-xl border cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-[#000000] border-[#C9D1D9] shadow-xs ring-1 ring-[#C9D1D9]/30'
                        : 'bg-[#000000] border-[#30363D] hover:border-[#C9D1D9] hover:bg-[#000000]'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h3 className="font-serif font-bold text-base text-[#F0F6FC] truncate">
                          {app.name}
                        </h3>
                        <div className="flex items-center gap-2 mt-1">
                          <Pill tone="sage">{app.environment}</Pill>
                          <Pill tone="muted" title={app.id}>
                            {shortId(app.id, 10)}
                          </Pill>
                        </div>
                      </div>
                      <ChevronRight
                        className={`w-4 h-4 mt-1 shrink-0 ${isSelected ? 'text-[#C9D1D9]' : 'text-[#9CA3AF]'}`}
                      />
                    </div>

                    <p className="text-xs text-[#B1BAC4] mt-2.5 line-clamp-2 leading-relaxed">
                      {app.description || 'No description provided.'}
                    </p>

                    <div className="mt-3 pt-3 border-t border-[#30363D]/70 flex items-center justify-between text-[11px] text-[#B1BAC4]">
                      <span>Registered {formatDate(app.created_at)}</span>
                      <span className="font-mono">{shortId(app.id, 8)}</span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Detail */}
            <div className="lg:col-span-7">
              {selectedApplication ? (
                <div className="bg-[#000000] rounded-xl border border-[#30363D] shadow-2xs overflow-hidden">
                  <div className="p-6 border-b border-[#30363D] bg-[#000000] flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <h2 className="font-serif font-bold text-xl text-[#F0F6FC]">
                          {selectedApplication.name}
                        </h2>
                        <Pill tone="sage">{selectedApplication.environment}</Pill>
                      </div>
                      <p className="text-xs text-[#B1BAC4] mt-1">
                        {selectedApplication.description || 'No description provided.'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => setRotating({ id: selectedApplication.id, name: selectedApplication.name })}
                        className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-[#C9D1D9] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#161B22] transition-colors"
                        title="Rotate the SDK API key"
                      >
                        <KeyRound className="w-3.5 h-3.5" /> Rotate key
                      </button>
                      <button
                        onClick={() => setDeleting({ id: selectedApplication.id, name: selectedApplication.name })}
                        className="p-2 text-[#F85149] hover:text-[#FF7B72] bg-[#000000] border border-[#30363D] rounded-lg hover:bg-[#F85149]/10 transition-colors"
                        title="Delete application"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  <div className="p-6 border-b border-[#30363D] space-y-3">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-[#B1BAC4]">
                      Registration details
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                      <div className="p-3 bg-[#000000] rounded-lg border border-[#30363D]">
                        <span className="text-[#B1BAC4] block text-[11px]">Application ID</span>
                        <span className="font-mono text-[#F0F6FC] mt-0.5 block break-all">
                          {selectedApplication.id}
                        </span>
                      </div>
                      <div className="p-3 bg-[#000000] rounded-lg border border-[#30363D]">
                        <span className="text-[#B1BAC4] block text-[11px] flex items-center gap-1">
                          <Calendar className="w-3 h-3" /> Created
                        </span>
                        <span className="text-[#F0F6FC] mt-0.5 block">
                          {formatDate(selectedApplication.created_at)}
                        </span>
                      </div>
                      <div className="p-3 bg-[#000000] rounded-lg border border-[#30363D] sm:col-span-2">
                        <span className="text-[#B1BAC4] block text-[11px]">API key</span>
                        <span className="text-[#F0F6FC] mt-0.5 block">
                          Stored only as a SHA-256 hash. If you lost the plaintext key, rotate it to
                          issue a new one.
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="p-6 border-b border-[#30363D]">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-[#B1BAC4] mb-3">
                      Inspect this application
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {[
                        {
                          to: `/applications/${selectedApplication.id}`,
                          icon: Server,
                          title: 'Overview',
                          description: 'Workers, tasks, recent executions',
                        },
                        {
                          to: `/applications/${selectedApplication.id}/tasks`,
                          icon: ListChecks,
                          title: 'Tasks',
                          description: 'Discovered Celery task catalog',
                        },
                        {
                          to: `/applications/${selectedApplication.id}/workers`,
                          icon: Server,
                          title: 'Workers',
                          description: 'Heartbeats, queues, registered tasks',
                        },
                        {
                          to: `/applications/${selectedApplication.id}/executions`,
                          icon: Activity,
                          title: 'Executions',
                          description: 'Attempt history and event timelines',
                        },
                        {
                          to: `/applications/${selectedApplication.id}/experiments`,
                          icon: FlaskConical,
                          title: 'Experiments',
                          description: 'Reliability experiment definitions',
                        },
                        {
                          to: '/integration',
                          icon: Terminal,
                          title: 'SDK integration',
                          description: 'Install, wire Celery, start workers',
                        },
                      ].map((item) => (
                        <Link
                          key={item.to}
                          to={item.to}
                          className="flex items-start gap-2.5 p-3 rounded-lg border border-[#30363D] hover:border-[#C9D1D9] hover:bg-[#000000] transition-colors"
                        >
                          <item.icon className="w-3.5 h-3.5 text-[#C9D1D9] mt-0.5 shrink-0" />
                          <div className="min-w-0">
                            <div className="text-xs font-medium text-[#F0F6FC]">{item.title}</div>
                            <div className="text-[10px] text-[#B1BAC4] mt-0.5">{item.description}</div>
                          </div>
                        </Link>
                      ))}
                    </div>
                  </div>

                  <div className="p-6 flex flex-wrap items-center justify-between gap-3">
                    <button
                      onClick={() => navigate(`/applications/${selectedApplication.id}`)}
                      className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg transition-all"
                    >
                      Open application <ExternalLink className="w-3.5 h-3.5" />
                    </button>
                    <span className="text-[11px] text-[#B1BAC4]">
                      Application context scopes every dashboard request.
                    </span>
                  </div>
                </div>
              ) : (
                <EmptyState
                  title="Select an application"
                  description="Choose an application from the list to inspect its registration details."
                />
              )}
            </div>
          </div>
        )}
      </div>

      <RegisterAppModal
        isOpen={isRegisterOpen}
        onClose={closeRegister}
        onCreated={(created) => void handleCreated(created)}
      />

      <ApiKeyModal
        isOpen={!!apiKeyState}
        applicationName={apiKeyState?.applicationName ?? ''}
        apiKey={apiKeyState?.apiKey ?? ''}
        rotated={apiKeyState?.rotated}
        onClose={() => setApiKeyState(null)}
      />

      <ConfirmationDialog
        isOpen={!!deleting}
        title="Remove Application"
        message={`Delete "${deleting?.name}"? Applications referenced by experiments cannot be deleted (the backend returns 409). This does not delete the target application itself.`}
        confirmLabel="Delete Application"
        isBusy={busy}
        onConfirm={handleDelete}
        onCancel={() => setDeleting(null)}
      />

      <ConfirmationDialog
        isOpen={!!rotating}
        title="Rotate API Key"
        message={`Issue a new API key for "${rotating?.name}"? The previous key stops working immediately and every target application using it must be updated.`}
        confirmLabel="Rotate Key"
        isDestructive={false}
        isBusy={busy}
        onConfirm={handleRotate}
        onCancel={() => setRotating(null)}
      />
    </Layout>
  );
};

export default Applications;
