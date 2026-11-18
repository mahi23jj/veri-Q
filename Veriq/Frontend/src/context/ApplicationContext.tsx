import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { TargetApplication } from '../api/types';
import { ApplicationContext } from './application-context';

const SELECTED_APPLICATION_KEY = 'veriq.selectedApplicationId';

export const ApplicationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [applications, setApplications] = useState<TargetApplication[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(SELECTED_APPLICATION_KEY);
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listApplications({ limit: 1000 });
      setApplications(response.items);
      setSelectedId((current) => {
        if (current && response.items.some((app) => app.id === current)) {
          return current;
        }
        return response.items[0]?.id ?? null;
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not load applications');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    try {
      if (selectedId) {
        localStorage.setItem(SELECTED_APPLICATION_KEY, selectedId);
      } else {
        localStorage.removeItem(SELECTED_APPLICATION_KEY);
      }
    } catch {
      // Storage may be unavailable (private mode); selection still works in memory.
    }
  }, [selectedId]);

  const selectApplication = useCallback((applicationId: string | null) => {
    setSelectedId(applicationId);
  }, []);

  const selectedApplication = useMemo(
    () => applications.find((app) => app.id === selectedId) ?? null,
    [applications, selectedId],
  );

  const value = useMemo(
    () => ({
      applications,
      loading,
      error,
      selectedApplication,
      selectApplication,
      reload,
    }),
    [applications, loading, error, selectedApplication, selectApplication, reload],
  );

  return <ApplicationContext.Provider value={value}>{children}</ApplicationContext.Provider>;
};
