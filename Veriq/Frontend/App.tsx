import React, { Suspense } from 'react';
import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ApplicationProvider } from './src/context/ApplicationContext';
import { useApplication } from './src/context/application-context';

const Home = React.lazy(() => import('./src/pages/Home'));
const Applications = React.lazy(() => import('./src/pages/Applications'));
const ApplicationOverview = React.lazy(() => import('./src/pages/ApplicationOverview'));
const Tasks = React.lazy(() => import('./src/pages/Tasks'));
const Workers = React.lazy(() => import('./src/pages/Workers'));
const Executions = React.lazy(() => import('./src/pages/Executions'));
const ExecutionDetail = React.lazy(() => import('./src/pages/ExecutionDetail'));
const Experiments = React.lazy(() => import('./src/pages/Experiments'));
const ExperimentDetail = React.lazy(() => import('./src/pages/ExperimentDetail'));
const Reliability = React.lazy(() => import('./src/pages/Reliability'));
const ReliabilityTask = React.lazy(() => import('./src/pages/ReliabilityTask'));
const ReliabilityPlan = React.lazy(() => import('./src/pages/ReliabilityPlan'));
const TestRuns = React.lazy(() => import('./src/pages/TestRuns'));
const TestRunDetail = React.lazy(() => import('./src/pages/TestRunDetail'));
const Integration = React.lazy(() => import('./src/pages/Integration'));
const Settings = React.lazy(() => import('./src/pages/Settings'));
const NotFound = React.lazy(() => import('./src/pages/NotFound'));

const LoadingFallback: React.FC = () => (
  <div className="min-h-screen bg-[#F7F5EF] flex items-center justify-center text-xs text-[#777A72] font-mono">
    Loading VeriQ dashboard…
  </div>
);

/** Legacy bookmark: send the user to the selected application's experiments. */
const ExperimentsRedirect: React.FC = () => {
  const { selectedApplication, loading } = useApplication();
  if (loading) return <LoadingFallback />;
  if (!selectedApplication) return <Navigate to="/applications" replace />;
  return <Navigate to={`/applications/${selectedApplication.id}/experiments`} replace />;
};

const App: React.FC = () => {
  return (
    <Theme appearance="light" radius="medium" scaling="100%">
      <ApplicationProvider>
        <Router future={{ v7_relativeSplatPath: true }}>
          <Suspense fallback={<LoadingFallback />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/applications" element={<Applications />} />
              <Route path="/applications/:appId" element={<ApplicationOverview />} />
              <Route path="/applications/:appId/tasks" element={<Tasks />} />
              <Route path="/applications/:appId/workers" element={<Workers />} />
              <Route path="/applications/:appId/executions" element={<Executions />} />
              <Route
                path="/applications/:appId/executions/:executionId"
                element={<ExecutionDetail />}
              />
              <Route path="/applications/:appId/experiments" element={<Experiments />} />
              <Route
                path="/applications/:appId/experiments/:experimentId"
                element={<ExperimentDetail />}
              />
              <Route path="/applications/:appId/reliability" element={<Reliability />} />
              <Route
                path="/applications/:appId/reliability/tasks/:taskId"
                element={<ReliabilityTask />}
              />
              <Route path="/applications/:appId/reliability/runs" element={<TestRuns />} />
              <Route
                path="/applications/:appId/reliability/runs/:runId"
                element={<TestRunDetail />}
              />
              <Route
                path="/applications/:appId/reliability/:planId"
                element={<ReliabilityPlan />}
              />
              <Route path="/integration" element={<Integration />} />
              <Route path="/settings" element={<Settings />} />

              {/* Legacy QueueProof-era routes */}
              <Route path="/experiments" element={<ExperimentsRedirect />} />
              <Route path="/experiments/:id" element={<ExperimentsRedirect />} />
              <Route path="/history" element={<ExperimentsRedirect />} />
              <Route path="/help" element={<Navigate to="/integration" replace />} />

              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
          <ToastContainer
            position="bottom-right"
            autoClose={2800}
            hideProgressBar={false}
            newestOnTop
            closeOnClick
            pauseOnHover
            theme="light"
          />
        </Router>
      </ApplicationProvider>
    </Theme>
  );
};

export default App;
