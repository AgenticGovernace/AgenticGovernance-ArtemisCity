import { useCallback, useEffect, useRef } from 'react';

/**
 * Own one abort controller per page loader.
 *
 * Starting a new load cancels the previous one, and leaving the route cancels
 * the active request automatically. This keeps route transitions from
 * allowing an older response to overwrite the next page's state.
 */
export const useRequestController = () => {
  const controllerRef = useRef<AbortController | null>(null);

  const createController = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    return controller;
  }, []);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    },
    []
  );

  return createController;
};

export default useRequestController;
