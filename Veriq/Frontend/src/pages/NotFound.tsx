import React from 'react';
import { Link } from 'react-router-dom';
import { ShieldAlert, ArrowLeft } from 'lucide-react';

export const NotFound: React.FC = () => {
  return (
    <div className="min-h-screen bg-[#F7F5EF] flex items-center justify-center p-6 text-[#343832]">
      <div className="max-w-md w-full bg-[#FDFCFA] rounded-2xl border border-[#E5E1D7] p-8 text-center shadow-xs">
        <div className="w-12 h-12 rounded-full bg-[#A46F70]/15 text-[#A46F70] flex items-center justify-center mx-auto mb-4">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <h1 className="font-serif font-bold text-xl text-[#343832]">Page Not Found</h1>
        <p className="text-xs text-[#777A72] mt-2 mb-6 leading-relaxed">
          The requested route does not exist in the QueueProof harness.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg transition-all"
        >
          <ArrowLeft className="w-4 h-4" />
          Return to Overview
        </Link>
      </div>
    </div>
  );
};

export default NotFound;