import React, { useState } from 'react';
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Boxes,
  FlaskConical,
  Menu,
  X,
  ShieldCheck,
  Plus,
  ListChecks,
  Server,
  Activity,
  Terminal,
  Settings,
  ChevronRight,
} from 'lucide-react';
import { useApplication } from '../context/application-context';
import { API_BASE_URL } from '../api/client';

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { applications, selectedApplication, selectApplication, loading } = useApplication();

  const workspaceNavigation = [
    { name: 'Overview', href: '/', icon: LayoutDashboard, exact: true },
    { name: 'Applications', href: '/applications', icon: Boxes },
    { name: 'Integration', href: '/integration', icon: Terminal },
    { name: 'Settings', href: '/settings', icon: Settings },
  ];

  const applicationNavigation = selectedApplication
    ? [
        {
          name: 'Application overview',
          href: `/applications/${selectedApplication.id}`,
          icon: LayoutDashboard,
          exact: true,
        },
        { name: 'Tasks', href: `/applications/${selectedApplication.id}/tasks`, icon: ListChecks },
        { name: 'Workers', href: `/applications/${selectedApplication.id}/workers`, icon: Server },
        { name: 'Executions', href: `/applications/${selectedApplication.id}/executions`, icon: Activity },
        {
          name: 'Experiments',
          href: `/applications/${selectedApplication.id}/experiments`,
          icon: FlaskConical,
        },
      ]
    : [];

  const isActive = (href: string, exact?: boolean) =>
    exact ? location.pathname === href : location.pathname === href || location.pathname.startsWith(`${href}/`);

  const handleApplicationChange = (applicationId: string) => {
    if (!applicationId) return;
    selectApplication(applicationId);
    navigate(`/applications/${applicationId}`);
    setMobileMenuOpen(false);
  };

  const renderLink = (item: {
    name: string;
    href: string;
    icon: typeof LayoutDashboard;
    exact?: boolean;
  }) => {
    const Icon = item.icon;
    return (
      <NavLink
        key={item.href}
        to={item.href}
        onClick={() => setMobileMenuOpen(false)}
        className={
          isActive(item.href, item.exact)
            ? 'flex items-center gap-3 px-3 py-2 text-sm rounded-lg bg-[#879B83]/18 text-[#262c24] font-semibold border-l-3 border-[#879B83] pl-[10px] transition-all'
            : 'flex items-center gap-3 px-3 py-2 text-sm rounded-lg text-[#61655b] hover:bg-[#EFEEE7] hover:text-[#343832] font-normal transition-all'
        }
      >
        <Icon className="w-4 h-4 shrink-0 text-[#777A72]" />
        <span className="truncate">{item.name}</span>
      </NavLink>
    );
  };

  const brand = (
    <>
      <div className="w-9 h-9 rounded-lg bg-[#879B83] flex items-center justify-center text-white shadow-2xs">
        <ShieldCheck className="w-5 h-5" />
      </div>
      <div>
        <div className="font-serif font-bold text-lg text-[#343832] leading-tight tracking-tight">VeriQ</div>
        <div className="text-[11px] text-[#777A72] tracking-wide font-medium mt-0.5">
          Background Job Reliability
        </div>
      </div>
    </>
  );

  const applicationSelector = (
    <div className="px-3 pt-3">
      <label
        className="block text-[10px] font-semibold uppercase tracking-wider text-[#777A72] px-1 mb-1.5"
        htmlFor="active-application"
      >
        Active application
      </label>
      {applications.length > 0 ? (
        <div className="relative">
          <select
            id="active-application"
            value={selectedApplication?.id ?? ''}
            onChange={(event) => handleApplicationChange(event.target.value)}
            className="w-full appearance-none pl-3 pr-8 py-2 text-xs font-medium bg-[#FAF8F3] border border-[#E5E1D7] rounded-lg text-[#343832] focus:outline-none focus:ring-2 focus:ring-[#879B83]"
            disabled={loading}
          >
            {applications.map((app) => (
              <option key={app.id} value={app.id}>
                {app.name} ({app.environment})
              </option>
            ))}
          </select>
          <ChevronRight className="w-3.5 h-3.5 text-[#777A72] absolute right-2.5 top-1/2 -translate-y-1/2 rotate-90 pointer-events-none" />
        </div>
      ) : (
        <Link
          to="/applications"
          onClick={() => setMobileMenuOpen(false)}
          className="block px-3 py-2 text-[11px] text-[#777A72] bg-[#FAF8F3] border border-dashed border-[#E5E1D7] rounded-lg hover:border-[#D8C8AE] transition-colors"
        >
          {loading ? 'Loading applications…' : 'No application yet — register one'}
        </Link>
      )}
      {selectedApplication && (
        <div className="mt-1.5 flex items-center gap-1.5 px-1">
          <span className="w-1.5 h-1.5 rounded-full bg-[#879B83]" />
          <span className="text-[10px] text-[#777A72] font-mono uppercase tracking-wide">
            {selectedApplication.environment}
          </span>
        </div>
      )}
    </div>
  );

  const navigation = (
    <>
      <div className="px-3 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[#777A72] px-4">
        Workspace
      </div>
      <nav className="px-3 space-y-1">{workspaceNavigation.map(renderLink)}</nav>

      {selectedApplication ? (
        <>
          <div className="px-4 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-wider text-[#777A72]">
            Application
          </div>
          <nav className="px-3 space-y-1">{applicationNavigation.map(renderLink)}</nav>
        </>
      ) : (
        <div className="mx-3 mt-4 p-3 rounded-lg bg-[#FAF8F3] border border-dashed border-[#E5E1D7] text-[11px] text-[#777A72] leading-relaxed">
          Register a target application to see tasks, workers, executions and experiments in its
          context.
        </div>
      )}
    </>
  );

  const footer = (
    <div className="p-4 border-t border-[#E5E1D7] bg-[#FAF8F3]">
      <div className="mb-2 px-2 py-1.5 rounded bg-[#EFEEE7]/80 text-[10px] text-[#777A72] flex items-center justify-between gap-2">
        <span className="font-mono truncate" title={API_BASE_URL}>
          API: {API_BASE_URL.replace(/^https?:\/\//, '')}
        </span>
        <span className="inline-block w-2 h-2 rounded-full bg-[#879B83] shrink-0" />
      </div>
      <div className="px-2 text-[10px] text-[#777A72] leading-relaxed">
        Dashboard reads are currently unauthenticated. SDK ingestion uses an application API key.
      </div>
    </div>
  );

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#F7F5EF] text-[#343832]">
      {/* Mobile Header Bar */}
      <div className="md:hidden flex items-center justify-between px-4 py-3 bg-[#FDFCFA] border-b border-[#E5E1D7] sticky top-0 z-40">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 rounded-lg bg-[#879B83] flex items-center justify-center text-white shadow-xs">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <span className="font-serif font-bold text-base tracking-tight text-[#343832]">VeriQ</span>
            <span className="block text-[10px] text-[#777A72] uppercase tracking-wider font-mono">
              Reliability
            </span>
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
          <div className="w-72 bg-[#FDFCFA] h-full flex flex-col shadow-xl border-r border-[#E5E1D7] overflow-y-auto">
            <div className="flex items-center justify-between p-5 pb-4 border-b border-[#E5E1D7]">
              <div className="flex items-center space-x-2.5">{brand}</div>
              <button
                onClick={() => setMobileMenuOpen(false)}
                className="p-1.5 text-[#777A72] hover:text-[#343832] rounded-md"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            {applicationSelector}
            <div className="flex-1 py-2">{navigation}</div>
            {footer}
          </div>
          <div className="flex-1" onClick={() => setMobileMenuOpen(false)} />
        </div>
      )}

      {/* Desktop Sidebar */}
      <aside className="hidden md:flex flex-col w-[256px] shrink-0 min-h-screen bg-[#FDFCFA] border-r border-[#E5E1D7] select-none">
        <div className="p-6 pb-4 border-b border-[#E5E1D7]">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="w-9 h-9 rounded-lg bg-[#879B83] group-hover:bg-[#778b73] transition-colors flex items-center justify-center text-white">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <div className="font-serif font-bold text-lg text-[#343832] leading-tight tracking-tight">
                VeriQ
              </div>
              <div className="text-[11px] text-[#777A72] tracking-wide font-medium mt-0.5">
                Background Job Reliability
              </div>
            </div>
          </Link>
        </div>

        <div className="px-3 pt-4 pb-1">
          <Link
            to="/applications?action=register"
            className="w-full flex items-center justify-center gap-2 px-3.5 py-2.5 text-xs font-semibold uppercase tracking-wider text-white bg-[#879B83] hover:bg-[#788c74] rounded-lg shadow-2xs transition-all active:scale-[0.98]"
          >
            <Plus className="w-4 h-4" />
            Register Application
          </Link>
        </div>

        {applicationSelector}

        <div className="flex-1 py-2 overflow-y-auto">{navigation}</div>
        {footer}
      </aside>

      {/* Main Content Viewport */}
      <main className="flex-1 min-w-0 flex flex-col overflow-y-auto">{children}</main>
    </div>
  );
};
