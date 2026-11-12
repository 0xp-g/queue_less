import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { clearJoinRequestId, deviceId, joinRequestId, tickets } from "../lib/storage";

export default function JoinPage() {
  const { queueId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [queue, setQueue] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const existing = tickets.get(queueId);
    if (existing) {
      // Already holding a ticket here? Go back to it unless it has finished.
      api(`/api/tickets/${existing}`)
        .then((t) => (["waiting", "called", "serving"].includes(t.status) ? navigate(`/t/${existing}`) : tickets.remove(queueId)))
        .catch(() => tickets.remove(queueId));
    }
    api(`/api/queues/${queueId}/public`).then(setQueue).catch(setError);
  }, [queueId, navigate]);

  async function join() {
    setBusy(true);
    setError(null);
    try {
      const t = await api(`/api/queues/${queueId}/tickets`, {
        method: "POST",
        body: { join_token: params.get("t") ?? "", client_request_id: joinRequestId(queueId), device_id: deviceId() },
      });
      tickets.save(queueId, t.token);
      clearJoinRequestId(queueId);
      navigate(`/t/${t.token}`);
    } catch (e) {
      setError(e); // the request id is kept, so pressing again is a safe retry
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page narrow">
      <h1 className="brand">QueueLess</h1>
      {queue && (
        <section className="card">
          <h2>{queue.queue_name}</h2>
          <p className="muted">
            {queue.waiting_count} waiting · now serving <b>{queue.now_serving ?? "-"}</b>
          </p>
          {queue.queue_status === "open" ? (
            <button className="btn big" disabled={busy} onClick={join}>
              {busy ? "Joining..." : "Join the queue"}
            </button>
          ) : (
            <p className="notice">This queue is {queue.queue_status}. Please check with staff.</p>
          )}
        </section>
      )}
      {error && <p className="error">{error.message}</p>}
    </main>
  );
}
