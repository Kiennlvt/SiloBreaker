import { Link } from "react-router-dom";

export function ForbiddenPage() {
  return (
    <section className="panel status-page" aria-labelledby="forbidden-title">
      <p className="eyebrow">403</p>
      <h2 id="forbidden-title">You do not have access to this page</h2>
      <p className="muted">Your account's role does not allow this. Ask an administrator if you need access.</p>
      <Link to="/">Go to your home page</Link>
    </section>
  );
}

export function NotFoundPage() {
  return (
    <section className="panel status-page" aria-labelledby="notfound-title">
      <p className="eyebrow">404</p>
      <h2 id="notfound-title">Page not found</h2>
      <p className="muted">The address does not match any page.</p>
      <Link to="/">Go to your home page</Link>
    </section>
  );
}
