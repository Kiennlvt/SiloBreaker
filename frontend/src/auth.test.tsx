import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthContext, ProtectedRoute, type AuthState } from "./auth";
import Layout from "./components/Layout";
import type { User } from "./types";

const admin: User = { id: "1", username: "admin", display_name: "Admin", role: "admin", person_id: null };
const FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };
const bob: User = { id: "2", username: "bob", display_name: "Bob", role: "member", person_id: "bob" };

function auth(user: User | null, loading = false): AuthState {
  return { user, loading, login: async () => user!, logout: async () => undefined };
}

function renderAt(path: string, state: AuthState) {
  return render(
    <AuthContext.Provider value={state}>
      <MemoryRouter initialEntries={[path]} future={FUTURE}>
        <Routes>
          <Route path="/login" element={<p>Login page</p>} />
          <Route path="/403" element={<p>Forbidden page</p>} />
          <Route
            path="/admin/users"
            element={
              <ProtectedRoute roles={["admin"]}>
                <p>Users admin</p>
              </ProtectedRoute>
            }
          />
          <Route
            path="/library"
            element={
              <ProtectedRoute>
                <p>Library</p>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("ProtectedRoute", () => {
  it("sends a signed-out visitor to /login", () => {
    renderAt("/admin/users", auth(null));
    expect(screen.getByText("Login page")).toBeInTheDocument();
  });

  it("sends a member to /403 on an admin page", () => {
    renderAt("/admin/users", auth(bob));
    expect(screen.getByText("Forbidden page")).toBeInTheDocument();
  });

  it("lets the right role in", () => {
    renderAt("/admin/users", auth(admin));
    expect(screen.getByText("Users admin")).toBeInTheDocument();
  });

  it("lets any signed-in user into a page without a role list", () => {
    renderAt("/library", auth(bob));
    expect(screen.getByText("Library")).toBeInTheDocument();
  });

  it("waits for the session check instead of redirecting", () => {
    renderAt("/admin/users", auth(null, true));
    expect(screen.getByRole("status")).toHaveTextContent(/Checking your session/);
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });
});

function renderLayout(user: User) {
  return render(
    <AuthContext.Provider value={auth(user)}>
      <MemoryRouter initialEntries={["/"]} future={FUTURE}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<p>Home</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

const menu = () =>
  Array.from(screen.getByRole("navigation", { name: "Main" }).querySelectorAll("a")).map((a) => a.textContent);

describe("Layout menu", () => {
  it("shows the administration menu to an admin", () => {
    renderLayout(admin);
    expect(menu()).toEqual(["Overview", "Users", "Handoffs", "Audit log", "Library"]);
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("Administrator")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log out" })).toBeInTheDocument();
  });

  it("shows the member menu to a member, without admin links", () => {
    renderLayout(bob);
    expect(menu()).toEqual(["My handoffs", "Learning", "Library"]);
    expect(screen.getByText("Member")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });
});
