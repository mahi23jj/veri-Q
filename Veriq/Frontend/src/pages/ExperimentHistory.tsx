import React, { useState, useMemo } from 'react';
import { Layout } from '../components/Layout';
import { INITIAL_RUNS, INITIAL_APPLICATIONS, INITIAL_EXPERIMENTS } from '../mockData';
import type { ExperimentRun, Verdict } from '../types';
import { VerdictBadge } from '../components/VerdictBadge';
import { useNavigate } from 'react-router-dom';
import {
  History,
  Search,
  Filter,
  ArrowUpDown,
  ExternalLink,
  ChevronRight,
  Download
} from 'lucide-react';
import { toast } from 'react-toastify';

export const ExperimentHistory: React.FC = () => {
  const navigate = useNavigate();
  const [runs] = useState<ExperimentRun[]>(INITIAL_RUNS);
  const [apps] = useState(INITIAL_APPLICATIONS);
  const [experiments] = useState(INITIAL_EXPERIMENTS);

  // Filters
  const [selectedApp, setSelectedApp] = useState<string>('all');
  const [selectedVerdict, setSelectedVerdict] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  const filteredRuns = useMemo(() => {
    return runs.filter(run => {
      if (selectedApp !== 'all' && run.applicationId !== selectedApp) return false;
      if (selectedVerdict !== 'all' && run.verdict !== selectedVerdict) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesId = run.id.toLowerCase().includes(q);
        const matchesName = run.experimentName.toLowerCase().includes(q);
        const matchesApp = run.applicationName.toLowerCase().includes(q);
        const matchesOpId = run.logicalOperationId.toLowerCase().includes(q);
        if (!matchesId && !matchesName && !matchesApp && !matchesOpId) return false;
      }
      return true;
    });
  }, [runs, selectedApp, selectedVerdict, searchQuery]);

  const handleExportCSV = () => {
    toast.info('Exported filtered experiment history (CSV snapshot)');
  };

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-7xl w-full mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#E5E1D7]">
          <div>
            <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">
              Experiment Run History
            </h1>
            <p className="text-xs md:text-sm text-[#777A72] mt-1">
              Historical ledger of failure simulations, invariant verifications, and anomalous redeliveries.
            </p>
          </div>
          <button
            onClick={handleExportCSV}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-[#52564e] bg-white border border-[#E5E1D7] hover:bg-[#EFEEE7] rounded-lg transition-colors"
          >
            <Download className="w-3.5 h-3.5 text-[#777A72]" />
            Export Log
          </button>
        </div>

        {/* Filter Controls Row */}
        <div className="bg-[#FDFCFA] p-4 rounded-xl border border-[#E5E1D7] grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Filter by Application
            </label>
            <select
              value={selectedApp}
              onChange={(e) => setSelectedApp(e.target.value)}
              className="w-full px-3 py-1.5 text-xs bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-1 focus:ring-[#879B83]"
            >
              <option value="all">All Applications</option>
              {apps.map(app => (
                <option key={app.id} value={app.id}>
                  {app.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Filter by Verdict
            </label>
            <select
              value={selectedVerdict}
              onChange={(e) => setSelectedVerdict(e.target.value)}
              className="w-full px-3 py-1.5 text-xs bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-1 focus:ring-[#879B83]"
            >
              <option value="all">All Verdicts</option>
              <option value="passed">Passed</option>
              <option value="failed">Failed</option>
              <option value="inconclusive">Inconclusive</option>
              <option value="cancelled">Cancelled</option>
              <option value="error">Error</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#777A72] mb-1">
              Search Runs
            </label>
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[#777A72] absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search run ID or op ID..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg focus:outline-none focus:ring-1 focus:ring-[#879B83]"
              />
            </div>
          </div>
        </div>

        {/* History Table */}
        <div className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] shadow-2xs overflow-hidden">
          {filteredRuns.length === 0 ? (
            <div className="p-12 text-center text-xs text-[#777A72]">
              No runs match the selected criteria.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#FAF8F3] border-b border-[#E5E1D7] text-[#777A72] uppercase font-semibold text-[10px] tracking-wider">
                  <tr>
                    <th className="py-3 px-4">Run Identifier</th>
                    <th className="py-3 px-4">Experiment</th>
                    <th className="py-3 px-4">Application</th>
                    <th className="py-3 px-4">Start Time</th>
                    <th className="py-3 px-4">Duration</th>
                    <th className="py-3 px-4">Worker Node</th>
                    <th className="py-3 px-4">Verdict</th>
                    <th className="py-3 px-4 text-right">Inspect</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E5E1D7]">
                  {filteredRuns.map(run => (
                    <tr
                      key={run.id}
                      onClick={() => navigate(`/experiments/${run.experimentId}?runId=${run.id}`)}
                      className="hover:bg-[#FAF8F3]/80 transition-colors cursor-pointer group"
                    >
                      <td className="py-3.5 px-4">
                        <div className="font-mono font-semibold text-[#343832] group-hover:text-[#5f745b] transition-colors">
                          {run.id}
                        </div>
                        <div className="text-[10px] text-[#777A72] font-mono">
                          Run #{run.runNumber}
                        </div>
                      </td>

                      <td className="py-3.5 px-4 font-medium text-[#343832]">
                        {run.experimentName}
                      </td>

                      <td className="py-3.5 px-4">
                        <span className="font-mono text-[11px] text-[#52564e] bg-[#EFEEE7] px-2 py-0.5 rounded">
                          {run.applicationName}
                        </span>
                      </td>

                      <td className="py-3.5 px-4 font-mono text-[#777A72]">
                        {run.startTime}
                      </td>

                      <td className="py-3.5 px-4 font-mono text-[#343832]">
                        {run.duration}
                      </td>

                      <td className="py-3.5 px-4 font-mono text-[#777A72]">
                        {run.workerNode}
                      </td>

                      <td className="py-3.5 px-4">
                        <VerdictBadge verdict={run.verdict} size="sm" />
                      </td>

                      <td className="py-3.5 px-4 text-right">
                        <ChevronRight className="w-4 h-4 text-[#777A72] ml-auto group-hover:text-[#343832] transition-colors" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
};

export default ExperimentHistory;