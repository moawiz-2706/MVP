import { useQuery } from "@tanstack/react-query";
import { api } from "./client";
import type { PwaBootstrapResponse } from "./types";

/** Shell identity and permissions; shared with AppShell through the query cache. */
export function usePwaBootstrap() {
  return useQuery({
    queryKey: ["pwa-bootstrap"],
    queryFn: () => api<PwaBootstrapResponse>("/pwa/bootstrap"),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
  });
}

export function useHasPermission(permission: string): boolean {
  return Boolean(usePwaBootstrap().data?.permissions.includes(permission));
}
