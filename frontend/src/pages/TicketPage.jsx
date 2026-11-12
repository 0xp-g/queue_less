import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { formatEta, pad } from "../lib/format";
import { tickets } from "../lib/storage";
import { useQueueSocket } from "../lib/useQueueSocket";

const LABELS = {
  waiting: "You're in the queue",
  called: "It's your turn!",
  serving: "You're being served",
  served: "All done. Thank you!",
  cancelled: "Ticket cancelled",
  no_show: "You missed your turn",
};

export default function TicketPage() {
  const { token } = useParams();
  const [queueId, setQueueId] = useState(null);
  const [initial, setInitial] = useState(null);
  const [error, setError] = useState(null);

  // Resolve the queue id once over REST, then stay live over the socket.
  useEffect(() => {
    api(`/api/tickets/${token}`)
      .then((t) => {
        setInitial(t);
        setQueueId(t.queue_id);
      })
      .catch(setError);
  }, [token]);
  const live = useQueueSocket({ queueId, ticketToken: token, pollPath: queueId ? `/api/tickets/${token}` : null });
  const t = (queueId && live.state) || initial;

  async function cancel() {
    if (!confirm("Leave the queue?")) return;
    try {
      await api(`/api/tickets/${token}`, { method: "DELETE" });
      tickets.remove(t.queue_id);
    } catch (e) {
      setError(e);
    }
  }

  if (error) return <main className="page narrow"><p className="error">{error.message}</p></main>;
  if (!t) return <main className="page narrow"><p className="muted">Loading your ticket...</p></main>;

  return (
    <main className={`page narrow status-${t.status}`}>
      <p className="muted">{t.queue_name}</p>
      <section className="card ticket">
        <p className="label">Your number</p>
        <p className="number">{pad(t.seq)}</p>
        <h2>{LABELS[t.status]}</h2>
        {t.status === "waiting" && (
          <div className="grid2">
            <div><p className="label">Position</p><p className="stat">{t.position}</p></div>
            <div><p className="label">Estimated wait</p><p className="stat">{formatEta(t.eta_seconds)}</p></div>
          </div>
        )}
        {t.status === "called" && (
          <p className="notice">
            Go to <b>{t.counter ?? "the counter"}</b> and scan the QR code on its screen to check in.
          </p>
        )}
        <p className="muted">Now serving <b>{pad(t.now_serving)}</b> · queue is {t.queue_status}</p>
      </section>
      {["waiting", "called"].includes(t.status) && (
        <button className="btn ghost" onClick={cancel}>Leave the queue</button>
      )}
      <p className={`conn conn-${live.mode}`}>{live.mode === "live" ? "Live" : live.mode === "polling" ? "Reconnecting (updating every 3 s)" : "Connecting..."}</p>
    </main>
  );
}
