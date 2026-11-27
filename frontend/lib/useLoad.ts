"use client";

import { useCallback, useEffect, useState } from "react";

import { errorText } from "./api";

export interface Loaded<T> {
  data: T | undefined;
  error: string | undefined;
  reload: () => void;
  setData: (data: T) => void;
}

/** Load data on mount (and on `reload`). `load` must be a stable function. */
export function useLoad<T>(load: () => Promise<T>): Loaded<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    load().then(
      (result) => {
        if (active) {
          setData(result);
          setError(undefined);
        }
      },
      (failure: unknown) => {
        if (active) setError(errorText(failure));
      },
    );
    return () => {
      active = false;
    };
  }, [load, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, reload, setData };
}
