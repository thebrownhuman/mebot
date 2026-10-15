import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { getSetupStatus } from "../lib/api";
import { CenteredCard } from "./AuthForm";

const SetupCtx = createContext<{ markSetupDone: () => void }>({ markSetupDone: () => {} });

export const useSetup = () => useContext(SetupCtx);

// Asks the backend once on boot whether first-run setup is pending. While it is, every
// route goes to /setup; afterwards /setup itself is closed.
export default function SetupGate({ children }: { children: React.ReactNode }) {
  const [required, setRequired] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { pathname } = useLocation();

  useEffect(() => {
    getSetupStatus()
      .then((s) => setRequired(s?.setup_required ?? false))
      .catch((e: Error) => setError(e.message || "backend not reachable"));
  }, []);

  if (error) {
    return (
      <CenteredCard title="// can't reach the server">
        <p role="alert" className="text-term-err text-sm">
          {error}
        </p>
      </CenteredCard>
    );
  }
  if (required === null) {
    return (
      <div role="status" className="fixed inset-0 flex items-center justify-center text-term-dim text-sm">
        loading…
      </div>
    );
  }
  if (required && pathname !== "/setup") return <Navigate to="/setup" replace />;
  if (!required && pathname === "/setup") return <Navigate to="/admin/login" replace />;

  return (
    <SetupCtx.Provider value={{ markSetupDone: () => setRequired(false) }}>
      {children}
    </SetupCtx.Provider>
  );
}
