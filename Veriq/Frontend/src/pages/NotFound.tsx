import React from 'react';
import { Link } from 'react-router-dom';
import { ShieldAlert, ArrowLeft } from 'lucide-react';

export const NotFound: React.FC = () => {
  return (
    <div className="min-h-screen bg-[#000000] flex items-center justify-center p-6 text-[#F0F6FC]">
      <div className="max-w-md w-full bg-[#000000] rounded-2xl border border-[#30363D] p-8 text-center shadow-xs">
        <div className="w-12 h-12 rounded-full bg-[#F85149]/15 text-[#F85149] flex items-center justify-center mx-auto mb-4">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <h1 className="font-serif font-bold text-xl text-[#F0F6FC]">Page Not Found</h1>
        <p className="text-xs text-[#B1BAC4] mt-2 mb-6 leading-relaxed">
          The requested route does not exist in the VeriQ dashboard.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-black bg-[#FFFFFF] hover:bg-[#E5E7EB] rounded-lg transition-all"
        >
          <ArrowLeft className="w-4 h-4" />
          Return to Overview
        </Link>
      </div>
    </div>
  );
};

export default NotFound;