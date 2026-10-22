import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

/** Admins start at the overview; members start where they have work to do. */
export default function HomeRedirect() {
  const { user } = useAuth();
  const [target, setTarget] = useState<string | null>(user?.role === "admin" ? "/admin" : null);

  useEffect(() => {
    if (!user || user.role === "admin") return;
    api
      .handoffs()
      .then((hs) => setTarget(hs.some((h) => h.viewer_role === "expert") ? "/expert" : "/learn"))
      .catch(() => setTarget("/learn"));
  }, [user]);

  if (!user) return <Navigate to="/login" replace />;
  if (!target)
    return (
      <p className="busy" role="status">
        Loading…
      </p>
    );
  return <Navigate to={target} replace />;
}
