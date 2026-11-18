import { createContext, useContext, useEffect } from 'react';
import type { TargetApplication } from '../api/types';

export interface ApplicationContextValue {
  applications: TargetApplication[];
  loading: boolean;
  error: string | null;
  selectedApplication: TargetApplication | null;
  selectApplication: (applicationId: string | null) => void;
  reload: () => Promise<void>;
}

export const ApplicationContext = createContext<ApplicationContextValue | undefined>(undefined);

export function useApplication(): ApplicationContextValue {
  const context = useContext(ApplicationContext);
  if (!context) {
    throw new Error('useApplication must be used inside ApplicationProvider');
  }
  return context;
}

/** Resolve the application from a route param and keep the global selection in sync. */
export function useScopedApplication(routeApplicationId: string | undefined) {
  const appContext = useApplication();

  useEffect(() => {
    if (routeApplicationId && routeApplicationId !== appContext.selectedApplication?.id) {
      appContext.selectApplication(routeApplicationId);
    }
  }, [routeApplicationId, appContext]);

  const application =
    appContext.applications.find((app) => app.id === routeApplicationId) ??
    (appContext.selectedApplication?.id === routeApplicationId
      ? appContext.selectedApplication
      : null);

  return { ...appContext, application };
}
