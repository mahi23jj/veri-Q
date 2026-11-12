import React from 'react';
import type { Verdict } from '../types';
import { CheckCircle2, XCircle, AlertTriangle, HelpCircle, Ban } from 'lucide-react';

interface VerdictBadgeProps {
  verdict: Verdict;
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
}

export const VerdictBadge: React.FC<VerdictBadgeProps> = ({
  verdict,
  size = 'md',
  showIcon = true
}) => {
  const getStyles = () => {
    switch (verdict) {
      case 'passed':
        return {
          bg: 'bg-[#879B83]/15 text-[#3e563a] border-[#879B83]/30',
          icon: <CheckCircle2 className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
          label: 'Passed'
        };
      case 'failed':
        return {
          bg: 'bg-[#A46F70]/15 text-[#733e3f] border-[#A46F70]/30',
          icon: <XCircle className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
          label: 'Failed'
        };
      case 'inconclusive':
        return {
          bg: 'bg-[#8297AC]/15 text-[#3b5168] border-[#8297AC]/30',
          icon: <AlertTriangle className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
          label: 'Inconclusive'
        };
      case 'error':
        return {
          bg: 'bg-[#A46F70]/20 text-[#843132] border-[#A46F70]/40',
          icon: <HelpCircle className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
          label: 'Error'
        };
      case 'cancelled':
        return {
          bg: 'bg-[#777A72]/15 text-[#4e5149] border-[#777A72]/30',
          icon: <Ban className={size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'} />,
          label: 'Cancelled'
        };
      default:
        return {
          bg: 'bg-stone-100 text-stone-700 border-stone-200',
          icon: null,
          label: verdict
        };
    }
  };

  const { bg, icon, label } = getStyles();

  const sizeClass = {
    sm: 'text-xs px-2 py-0.5 gap-1 font-medium',
    md: 'text-xs px-2.5 py-1 gap-1.5 font-medium',
    lg: 'text-sm px-3 py-1.5 gap-2 font-medium'
  }[size];

  return (
    <span className={`inline-flex items-center rounded-full border ${bg} ${sizeClass} transition-colors tracking-tight`}>
      {showIcon && icon}
      <span>{label}</span>
    </span>
  );
};