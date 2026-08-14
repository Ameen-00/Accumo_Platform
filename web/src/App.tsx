import { useEffect, useState } from "react";
import { ApiError, api, type Me } from "./api";
import { Findings } from "./Findings";
import { ImportDesk } from "./ImportDesk";

type Tab = "import" | "findings";

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState<Tab>("import");
  const [runId, setRunId] = useState<string | null>(null);
  const [apiDown, setApiDown] = useState(false);

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch((err) => {
        if (err instanceof ApiError && err.status !== 401) setApiDown(true);
      })
      .finally(() => setReady(true));
  }, []);

  if (!ready) return null;
  if (!me) {
    return <Login onIn={setMe} apiDown={apiDown} />;
  }

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          Accumo<span>Pulse</span>
        </div>
        <nav className="tabs">
          <button className={tab === "import" ? "on" : ""} onClick={() => setTab("import")}>
            Import
          </button>
          <button className={tab === "findings" ? "on" : ""} onClick={() => setTab("findings")}>
            Findings
          </button>
        </nav>
        <div className="btn-row">
          <span className="hint" style={{ margin: 0 }}>
            {me.name} · {me.role}
          </span>
          <button
            className="btn btn-ghost"
            onClick={() => {
              api.logout().finally(() => setMe(null));
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      {tab === "import" ? (
        <ImportDesk
          onRan={(id) => {
            setRunId(id);
            setTab("findings");
          }}
        />
      ) : (
        <Findings runId={runId} />
      )}
    </div>
  );
}

function Login({ onIn, apiDown }: { onIn: (m: Me) => void; apiDown: boolean }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  return (
    <div className="login">
      <form
        className="login-card"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setErr(null);
          try {
            onIn(await api.login(email.trim(), password));
          } catch (ex) {
            setErr(ex instanceof Error ? ex.message : "Could not sign in");
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="mark">Pulse</div>
        <p className="lead">Review payments. The number on this screen is money.</p>
        {apiDown && (
          <p className="err">
            The API is not reachable. Start Postgres + the API, then refresh. This screen is not
            the marketing demo.
          </p>
        )}
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {err && <p className="err">{err}</p>}
        <div style={{ marginTop: "1.1rem" }}>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
        <p className="hint">An Accumo operator creates your login. There is no self-serve signup.</p>
      </form>
    </div>
  );
}
