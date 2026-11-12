import React from 'react';
import { Layout } from '../components/Layout';
import { BookOpen, ShieldAlert, Cpu, Terminal, CheckCircle2, AlertOctagon } from 'lucide-react';

export const HelpDocs: React.FC = () => {
  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-4xl w-full mx-auto space-y-8">
        <div className="pb-4 border-b border-[#E5E1D7]">
          <h1 className="font-serif font-bold text-2xl md:text-3xl text-[#343832] tracking-tight">
            QueueProof Documentation
          </h1>
          <p className="text-xs md:text-sm text-[#777A72] mt-1">
            Understanding controlled background job failure testing and business invariant verification.
          </p>
        </div>

        {/* Section 1 */}
        <section className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-6 shadow-2xs space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#879B83]/15 text-[#3e563a] flex items-center justify-center">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <h2 className="font-serif font-bold text-base text-[#343832]">
                The "Crash After Commit" Problem
              </h2>
              <span className="text-xs text-[#777A72]">Why conventional distributed systems double-execute</span>
            </div>
          </div>

          <p className="text-xs text-[#52564e] leading-relaxed">
            In standard background job architectures (Celery, BullMQ, Sidekiq), a worker dequeues a job, commits state changes to a primary database, and finally acknowledges the job to the broker (ACK). If the worker crashes, loses power, or suffers an out-of-memory SIGKILL <em>after the database commit but before the broker ACK</em>, the broker will redeliver the unacknowledged job to another worker.
          </p>

          <div className="p-3.5 bg-[#FAF8F3] rounded-lg border border-[#E5E1D7] text-xs text-[#52564e]">
            <span className="font-semibold text-[#343832]">QueueProof's Methodology:</span>
            <p className="mt-1">
              QueueProof injects a checkpoint hook directly after your commit statement. At that microsecond, the testing harness terminates the simulated worker process. Upon queue redelivery, the verifier audits database records and external API calls to guarantee no double-charge or duplicate allocation occurred.
            </p>
          </div>
        </section>

        {/* Section 2 */}
        <section className="bg-[#FDFCFA] rounded-xl border border-[#E5E1D7] p-6 shadow-2xs space-y-4">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#8297AC]/15 text-[#3b5168] flex items-center justify-center">
              <Terminal className="w-4 h-4" />
            </div>
            <div>
              <h2 className="font-serif font-bold text-base text-[#343832]">
                Recommended Remediation Patterns
              </h2>
              <span className="text-xs text-[#777A72]">How to make tasks resilient to redelivery</span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            <div className="p-4 bg-white rounded-lg border border-[#E5E1D7]">
              <span className="font-semibold text-[#343832] block">1. Database-Level Unique Constraint</span>
              <p className="text-[#61655b] mt-1 leading-relaxed">
                Include an <code className="font-mono text-[11px] bg-[#EFEEE7] px-1 py-0.5 rounded">operation_id</code> column with a unique index. A retry will raise an integrity error rather than creating duplicate state.
              </p>
            </div>

            <div className="p-4 bg-white rounded-lg border border-[#E5E1D7]">
              <span className="font-semibold text-[#343832] block">2. Outbox Transaction Pattern</span>
              <p className="text-[#61655b] mt-1 leading-relaxed">
                Persist external events into a database table within the same transaction. A separate relay handles carrier/third-party API calls with dedup keys.
              </p>
            </div>
          </div>
        </section>
      </div>
    </Layout>
  );
};

export default HelpDocs;