import React, { Suspense } from 'react';
import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';

const Home = React.lazy(() => import('./src/pages/Home'));
const Applications = React.lazy(() => import('./src/pages/Applications'));
const Experiments = React.lazy(() => import('./src/pages/Experiments'));
const ExperimentDetail = React.lazy(() => import('./src/pages/ExperimentDetail'));
const ExperimentHistory = React.lazy(() => import('./src/pages/ExperimentHistory'));
const Settings = React.lazy(() => import('./src/pages/Settings'));
const HelpDocs = React.lazy(() => import('./src/pages/HelpDocs'));
const NotFound = React.lazy(() => import('./src/pages/NotFound'));

const LoadingFallback: React.FC = () => (
  <div className="min-h-screen bg-[#F7F5EF] flex items-center justify-center text-xs text-[#777A72] font-mono">
    Loading QueueProof Harness...
  </div>
);

const App: React.FC = () => {
  return (
    <Theme appearance="light" radius="medium" scaling="100%">
      <Router future={{ v7_relativeSplatPath: true }}>
        <Suspense fallback={<LoadingFallback />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/applications" element={<Applications />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/experiments/:id" element={<ExperimentDetail />} />
            <Route path="/history" element={<ExperimentHistory />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/help" element={<HelpDocs />} />
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
    </Theme>
  );
};

export default App;