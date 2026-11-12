import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { tickets } from "../lib/storage";

// Opened by scanning the counter's rotating QR. The nonce proves the visitor is at the counter.
export default function CheckInPage() {
  const [params] = useSearchParams();
  const [result, setResult] = useState({ state: "working" });

  useEffect(() => {
    const counterId = Number(params.get("counter"));
    const nonce = params.get("nonce");
    (async () => {
      for (const token of Object.values(tickets.all())) {
        try {
          const t = await api(`/api/tickets/${token}`);
          if (t.status !== "called") continue;
          await api(`/api/tickets/${t.ticket_id}/check-in`, { method: "POST", body: { token, counter_id: counterId, nonce } });
          return setResult({ state: "ok", token });
        } catch (e) {
          return setResult({ state: "error", message: e.message });
        }
      }
      setResult({ state: "error", message: "No called ticket on this phone. Wait until your number is called." });
    })();
  }, [params]);

  return (
    <main className="page narrow">
      <h1 className="brand">Check in</h1>
      {result.state === "working" && <p className="muted">Checking you in...</p>}
      {result.state === "ok" && (
        <section className="card">
          <h2>You're checked in ✓</h2>
          <Link className="btn" to={`/t/${result.token}`}>Back to my ticket</Link>
        </section>
      )}
      {result.state === "error" && <p className="error">{result.message}</p>}
    </main>
  );
}
