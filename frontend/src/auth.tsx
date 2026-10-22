import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, ApiError, setUnauthorizedHandler } from "./api";
import type { Role, User } from "./types";

export type AuthState = {
  user: User | null;
  loading: boolean;
  // True after the user pressed Log out, so the next sign-in starts at home, not at the
  // page the previous person was on.
  signedOut?: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Asks the backend who is signed in. The browser never decides that from local state. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .me()
      .then((r) => live && setUser(r.user))
      .catch((e) => {
        if (live && !(e instanceof ApiError && e.status === 401)) console.error(e);
        if (live) setUser(null);
      })
      .finally(() => live && setLoading(false));
    setUnauthorizedHandler(() => setUser(null));
    return () => {
      live = false;
      setUnauthorizedHandler(null);
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.login(username, password);
    setSignedOut(false);
    setUser(r.user);
    return r.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setSignedOut(true);
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, signedOut, login, logout }),
    [user, loading, signedOut, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function displayName(u: User): string {
  return u.display_name || u.username;
}

/** Signed out goes to /login (remembering where it was headed); wrong role goes to /403. */
export function ProtectedRoute({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading, signedOut } = useAuth();
  const location = useLocation();
  if (loading)
    return (
      <p className="busy" role="status">
        Checking your session…
      </p>
    );
  if (!user) return <Navigate to="/login" replace state={signedOut ? null : { from: location.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/403" replace />;
  return <>{children}</>;
}
