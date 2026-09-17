export function MutationNotice({ success, error }: { success?: string | null; error?: Error | null }) {
  if (error) return <div className="error-banner" role="alert">{error.message}</div>;
  if (success) return <div className="success-banner" role="status">{success}</div>;
  return null;
}
