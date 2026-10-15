import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { getMe, UNAUTHORIZED_EVENT, type Me } from "../lib/api";

// Renders children only for a logged-in admin; otherwise sends them to /admin/login.
// Also reacts to any later 401 from an admin API call (e.g. session expired).
export default function RequireAdmin({ children }: { children: (me: Me) => React.ReactNode }) {
  const navigate = useNavigate();
  const [me, setMe] = useState<Me | null | "anon">(null);

  useEffect(() => {
    let live = true;
    getMe()
      .then((m) => live && setMe(m))
      .catch(() => live && setMe("anon"));
    const onUnauthorized = () => navigate("/admin/login", { replace: true });
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => {
      live = false;
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, [navigate]);

  if (me === "anon") return <Navigate to="/admin/login" replace />;
  if (me === null) {
    return (
      <div role="status" className="fixed inset-0 flex items-center justify-center text-term-dim text-sm">
        checking session…
      </div>
    );
  }
  return <>{children(me)}</>;
}
