import React, { useState } from 'react';
import { NavLink, Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Boxes,
  FlaskConical,
  History,
  Settings,
  HelpCircle,
  Menu,
  X,
  ShieldCheck,
  Plus
} from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
  onOpenNewExperiment?: () => void;
}

export const Layout: React.FC<LayoutProps> = ({ children, onOpenNewExperiment }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const location = useLocation();

  const navigation = [
    { name: 'Overview', href: '/', icon: LayoutDashboard },
    { name: 'Applications', href: '/applications', icon: Boxes },
    { name: 'Experiments', href: '/experiments', icon: FlaskConical },
    { name: 'Experiment History', href: '/history', icon: History },
    { name: 'Settings', href: '/settings', icon: Settings },
    { name: 'Help & Docs', href: '/help', icon: HelpCircle }
  ];

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#F7F5EF] text-[#343832]">
      {/* Mobile Header Bar */}
      <div className="md:hidden flex items-center justify-between px-4 py-3 bg-[#FDFCFA] border-b border-[#E5E1D7] sticky top-0 z-40">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 rounded-lg bg-[#879B83] flex items-center justify-center text-white shadow-xs">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <span className="font-serif font-bold text-base tracking-tight text-[#343832]">QueueProof</span>
            <span className="block text-[10px] text-[#777A72] uppercase tracking-wider font-mono">Reliability Harness</span>
          </div>
        </div>
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="p-2 text-[#777A72] hover:text-[#343832] rounded-md hover:bg-[#EFEEE7] transition-colors"
          aria-label="Toggle navigation"
        >
          {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-50 bg-[#343832]/30 backdrop-blur-xs flex">
          <div className="w-72 bg-[#FDFCFA] h-full p-5 flex flex-col shadow-xl border-r border-[#E5E1D7]">
            <div className="flex items-center justify-between pb-4 border-b border-[#E5E1D7] mb-4">
              <div className="flex items-center space-x-2.5">
                <div className="w-8 h-8 rounded-lg bg-[#879B83] flex items-center justify-center text-white">
                  <ShieldCheck className="w-5 h-5" />
                </div>
                <div>
                  <span className="font-serif font-bold text-base text-[#343832]">QueueProof</span>
                  <span className="block text-[10px] text-[#777A72] font-mono">Job Reliability</span>
                </div>
              </div>
              <button
                onClick={() => setMobileMenuOpen(false)}
                className="p-1.5 text-[#777A72] hover:text-[#343832] rounded-md"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <nav className="space-y-1 flex-1">
              {navigation.map((item) => {
                const Icon = item.icon;
                const isActive = location.pathname === item.href;
                return (
                  <Link
                    key={item.name}
                    to={item.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className={`flex items-center gap-3 px-3.5 py-2.5 text-sm font-medium rounded-lg transition-colors ${
                      isActive
                        ? 'bg-[#879B83]/15 text-[#343832] font-semibold border-l-3 border-[#879B83]'
                        : 'text-[#777A72] hover:bg-[#EFEEE7] hover:text-[#343832]'
                    }`}
                  >
                    <Icon className={`w-4 h-4 ${isActive ? 'text-[#5f745b]' : 'text-[#777A72]'}`} />
                    {item.name}
                  </Link>
                );
              })}
            </nav>
            <div className="pt-4 border-t border-[#E5E1D7]">
              <div className="px-3 py-2 bg-[#EFEEE7]/80 rounded-lg text-xs text-[#777A72]">
                <p className="font-medium text-[#343832]">Test Sandbox Mode</p>
                <p className="text-[11px] mt-0.5">Isolated mock worker harness</p>
              </div>
            </div>
          </div>
          <div className="flex-1" onClick={() => setMobileMenuOpen(false)} />
        </div>
      )}

      {/* Desktop Sidebar (approx 250px) */}
      <aside className="hidden md:flex flex-col w-[256px] shrink-0 min-h-screen bg-[#FDFCFA] border-r border-[#E5E1D7] select-none">
        {/* Brand Area */}
        <div className="p-6 pb-5 border-b border-[#E5E1D7]">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="w-9 h-9 rounded-lg bg-[#879B83] group-hover:bg-[#778b73] transition-colors flex items-center justify-center text-white shadow-2xs">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <div className="font-serif font-bold text-lg text-[#343832] leading-tight tracking-tight">QueueProof</div>
              <div className="text-[11px] text-[#777A72] tracking-wide font-medium mt-0.5">Background Job Reliability</div>
            </div>
          </Link>
        </div>

        {/* Quick Action */}
        <div className="px-4 pt-4 pb-2">
          {onOpenNewExperiment ? (
            <button
              onClick={onOpenNewExperiment}
              className="w-full flex items-center justify-center gap-2 px-3.5 py-2.5 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all active:scale-[0.98]"
            >
              <Plus className="w-4 h-4" />
              New Experiment
            </button>
          ) : (
            <Link
              to="/experiments?action=create"
              className="w-full flex items-center justify-center gap-2 px-3.5 py-2.5 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all active:scale-[0.98]"
            >
              <Plus className="w-4 h-4" />
              New Experiment
            </Link>
          )}
        </div>

        {/* Main Navigation */}
        <nav className="flex-1 px-3 py-3 space-y-1">
          {navigation.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.href || (item.href !== '/' && location.pathname.startsWith(item.href));
            return (
              <NavLink
                key={item.name}
                to={item.href}
                className={({ isActive: exactActive }) => {
                  const active = item.href === '/' ? exactActive : isActive;
                  return `flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-all duration-150 ${
                    active
                      ? 'bg-[#879B83]/18 text-[#262c24] font-semibold border-l-3 border-[#879B83] pl-[10px]'
                      : 'text-[#61655b] hover:bg-[#EFEEE7] hover:text-[#343832] font-normal'
                  }`;
                }}
              >
                <Icon className="w-4 h-4 shrink-0 text-[#777A72]" />
                <span>{item.name}</span>
              </NavLink>
            );
          })}
        </nav>

        {/* Workspace Summary & Visual-only Profile Area */}
        <div className="p-4 border-t border-[#E5E1D7] bg-[#FAF8F3]">
          <div className="mb-3 px-2 py-1.5 rounded bg-[#EFEEE7]/80 text-[11px] text-[#777A72] flex items-center justify-between">
            <span className="font-mono">Cluster: Staging-US</span>
            <span className="inline-block w-2 h-2 rounded-full bg-[#879B83] animate-pulse" />
          </div>

          <div className="flex items-center gap-3 pt-1">
            <div className="w-8 h-8 rounded-full bg-[#D8C8AE] flex items-center justify-center text-xs font-medium text-[#463f35] font-serif">
              EM
            </div>
            <div className="truncate">
              <div className="text-xs font-medium text-[#343832] truncate">Elena Miller</div>
              <div className="text-[10px] text-[#777A72] truncate">Staff Reliability Engineer</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Viewport */}
      <main className="flex-1 min-w-0 flex flex-col overflow-y-auto">
        {children}
      </main>
    </div>
  );
};