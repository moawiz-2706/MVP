import { useEffect, useState } from "react";

type Operation = {
  method: string;
  path: string;
  success: boolean;
  message?: string;
};

function verb(method: string, path: string) {
  if (method === "DELETE") return "Deletion";
  if (method === "POST") return path.includes("/calendars") ? "Creation" : "Save";
  if (method === "PATCH" || method === "PUT") return "Update";
  return "Operation";
}

export function OperationNotice() {
  const [operation, setOperation] = useState<Operation | null>(null);

  useEffect(() => {
    const onOperation = (event: Event) => {
      const detail = (event as CustomEvent<Operation>).detail;
      setOperation(detail);
      window.setTimeout(() => setOperation(null), 6000);
    };
    window.addEventListener("passport:operation", onOperation);
    return () => window.removeEventListener("passport:operation", onOperation);
  }, []);

  if (!operation) return null;
  if (!operation.success) {
    return <div className="error-banner operation-notice" role="alert">{operation.message || "The operation could not be completed."}</div>;
  }
  return <div className="success-banner operation-notice" role="status">{verb(operation.method, operation.path)} completed successfully.</div>;
}
