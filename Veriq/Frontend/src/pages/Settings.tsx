import React, { useState } from 'react';
import { Layout } from '../components/Layout';
import { ShieldCheck, Server, Bell, Database, HardDrive, Key } from 'lucide-react';
import { toast } from 'react-toastify';

export const Settings: React.FC = () => {
  const [defaultTimeout, setDefaultTimeout] = useState(15);
  const [logRetentionDays, setLogRetentionDays] = useState(30);
  const [enableTelemetryWebhook, setEnableTelemetryWebhook] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    toast.success('Settings preferences saved locally');
  };

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-4xl w-full mx-auto space-y-6">
        <div className="pb-4 border-b border-[#E5E1D7]">
          <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">
            Settings & Harness Preferences
          </h1>
          <p className="text-xs md:text-sm text-[#777A72] mt-1">
            Configure local sandbox boundaries, default experiment timeouts, and audit verifiers.
          </p>
        </div>

        <form onSubmit={handleSave} className="space-y-6">
          <div className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-6 shadow-2xs space-y-4">
            <h2 className="font-serif font-bold text-base text-[#343832] flex items-center gap-2">
              <Server className="w-4 h-4 text-[#879B83]" />
              Simulation Runtime Limits
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wider text-[#777A72] mb-1">
                  Default Timeout Threshold (seconds)
                </label>
                <input
                  type="number"
                  min="5"
                  max="180"
                  value={defaultTimeout}
                  onChange={(e) => setDefaultTimeout(Number(e.target.value))}
                  className="w-full px-3.5 py-2 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-1 focus:ring-[#879B83]"
                />
                <span className="text-[10px] text-[#777A72] mt-1 block">
                  Simulated worker is marked inconclusive if verification doesn't complete within this window.
                </span>
              </div>

              <div>
                <label className="block text-[11px] font-semibold uppercase tracking-wider text-[#777A72] mb-1">
                  Run History Retention (days)
                </label>
                <input
                  type="number"
                  min="7"
                  max="365"
                  value={logRetentionDays}
                  onChange={(e) => setLogRetentionDays(Number(e.target.value))}
                  className="w-full px-3.5 py-2 bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-1 focus:ring-[#879B83]"
                />
                <span className="text-[10px] text-[#777A72] mt-1 block">
                  Local cache prune threshold for execution traces.
                </span>
              </div>
            </div>
          </div>

          <div className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-6 shadow-2xs space-y-4">
            <h2 className="font-serif font-bold text-base text-[#343832] flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-[#879B83]" />
              Fault Injection Policy
            </h2>

            <div className="p-3 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7] text-xs text-[#52564e] leading-relaxed">
              <span className="font-semibold text-[#343832] block">Crash-After-Commit Safety Harness</span>
              QueueProof requires that experiments only target staging, development, or ephemeral canary environments. Production execution requires an explicit break-glass override token.
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              className="px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all"
            >
              Save Preferences
            </button>
          </div>
        </form>
      </div>
    </Layout>
  );
};

export default Settings;