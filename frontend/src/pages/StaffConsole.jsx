import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, staffToken } from "../lib/api";
import { pad } from "../lib/format";
import { useQueueSocket } from "../lib/useQueueSocket";

const auth = { auth: true };

export default function StaffConsole() {
  const navigate = useNavigate();
  const [me, setMe] = useState(null);
  const [queues, setQueues] = useState([]);
  const [queueId, setQueueId] = useState(null);

  useEffect(() => {
    if (!staffToken.get()) return navigate("/staff/login");
    Promise.all([api("/api/me", auth), api("/api/queues", auth)])
      .then(([m, qs]) => {
        setMe(m);
        setQueues(qs);
        setQueueId((id) => id ?? qs[0]?.id ?? null);
      })
      .catch(() => navigate("/staff/login"));
  }, [navigate]);

  if (!me) return <main className="page"><p className="muted">Loading...</p></main>;
  const isAdmin = me.role === "admin";
  return (
    <main className="page wide">
      <header className="topbar">
        <h1 className="brand">QueueLess staff</h1>
        <select value={queueId ?? ""} onChange={(e) => setQueueId(Number(e.target.value))}>
          {queues.map((q) => <option key={q.id} value={q.id}>{q.name}</option>)}
        </select>
        <span className="muted">{me.email} ({me.role})</span>
        <button className="btn ghost small" onClick={() => { staffToken.clear(); navigate("/staff/login"); }}>Sign out</button>
      </header>
      {isAdmin && <CreateQueue onCreated={(q) => { setQueues((qs) => [...qs, q]); setQueueId(q.id); }} />}
      {queueId && <QueuePanel key={queueId} queueId={queueId} isAdmin={isAdmin} />}
    </main>
  );
}

function QueuePanel({ queueId, isAdmin }) {
  const [queue, setQueue] = useState(null);
  const [active, setActive] = useState([]);
  const [noShows, setNoShows] = useState([]);
  const [counterId, setCounterId] = useState("");
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [q, act, ns] = await Promise.all([
        api(`/api/queues/${queueId}`, auth),
        api(`/api/queues/${queueId}/tickets`, auth),
        api(`/api/queues/${queueId}/tickets?status=no_show`, auth),
      ]);
      setQueue(q);
      setActive(act);
      setNoShows(ns.slice(-10));
      if (isAdmin) setStats(await api(`/api/queues/${queueId}/stats`, auth));
    } catch (e) {
      setError(e.message);
    }
  }, [queueId, isAdmin]);

  useEffect(() => { refresh(); }, [refresh]);
  // The console listens like a display board and refetches its lists on every event.
  const { state: live } = useQueueSocket({ queueId, onMessage: refresh });

  async function act(path, body) {
    setError(null);
    try {
      await api(path, { method: "POST", body, ...auth });
    } catch (e) {
      setError(e.message);
    }
    refresh();
  }
  async function setStatus(status) {
    await api(`/api/queues/${queueId}`, { method: "PATCH", body: { status }, ...auth }).catch((e) => setError(e.message));
    refresh();
  }

  if (!queue) return null;
  const waiting = active.filter((t) => t.status === "waiting");
  const atCounter = active.filter((t) => t.status !== "waiting");
  const counterLabel = (id) => queue.counters.find((c) => c.id === id)?.label ?? "-";

  return (
    <div className="columns">
      <section className="card">
        <h2>{queue.name} <span className={`pill ${queue.status}`}>{queue.status}</span></h2>
        <p className="muted">Now serving <b>{pad(live?.now_serving)}</b> · {waiting.length} waiting · est. {Math.round(queue.est_service_sec ?? queue.default_service_sec)} s per person</p>
        <div className="row">
          <select value={counterId} onChange={(e) => setCounterId(e.target.value)}>
            <option value="">Any counter</option>
            {queue.counters.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <button className="btn big" disabled={!waiting.length || queue.status === "closed"}
            onClick={() => act(`/api/queues/${queueId}/call-next`, { counter_id: counterId ? Number(counterId) : null })}>
            Call next
          </button>
        </div>
        {isAdmin && (
          <div className="row">
            {["open", "paused", "closed"].map((s) => (
              <button key={s} className="btn ghost small" disabled={queue.status === s} onClick={() => setStatus(s)}>{s}</button>
            ))}
            <Link className="btn ghost small" to={`/board/${queueId}`} target="_blank">Display board</Link>
          </div>
        )}
        {error && <p className="error">{error}</p>}

        <h3>At the counter</h3>
        <ul className="list">
          {atCounter.map((t) => (
            <li key={t.id}>
              <b>{pad(t.seq)}</b> <span className={`pill ${t.status}`}>{t.status}</span> {counterLabel(t.counter_id)}
              <span className="actions">
                {t.status === "called" && <button className="btn small ghost" onClick={() => act(`/api/tickets/${t.id}/check-in`)}>Check in</button>}
                <button className="btn small" onClick={() => act(`/api/tickets/${t.id}/complete`)}>Complete</button>
                {t.status === "called" && <button className="btn small ghost" onClick={() => act(`/api/tickets/${t.id}/no-show`)}>No-show</button>}
              </span>
            </li>
          ))}
          {!atCounter.length && <li className="muted">Nobody called yet.</li>}
        </ul>

        <h3>Waiting</h3>
        <ul className="list">
          {waiting.slice(0, 15).map((t, i) => (
            <li key={t.id}>
              <span className="muted">#{i + 1}</span> <b>{pad(t.seq)}</b>
              <span className="actions"><button className="btn small ghost" onClick={() => act(`/api/tickets/${t.id}/cancel`)}>Cancel</button></span>
            </li>
          ))}
          {waiting.length > 15 && <li className="muted">+{waiting.length - 15} more</li>}
        </ul>

        {!!noShows.length && (<>
          <h3>Recent no-shows</h3>
          <ul className="list">
            {noShows.map((t) => (
              <li key={t.id}><b>{pad(t.seq)}</b>
                <span className="actions">{t.requeue_count < queue.max_requeues && <button className="btn small ghost" onClick={() => act(`/api/tickets/${t.id}/requeue`)}>Requeue</button>}</span>
              </li>
            ))}
          </ul>
        </>)}
      </section>

      <aside>
        <CounterQr counters={queue.counters} />
        {isAdmin && <JoinQr queueId={queueId} />}
        {stats && (
          <section className="card">
            <h3>Stats</h3>
            <p>Served: <b>{stats.served}</b> · Avg wait: <b>{stats.avg_wait_sec ?? "-"} s</b></p>
            <p>ETA error (median): <b>{stats.eta_median_ape == null ? "-" : `${(stats.eta_median_ape * 100).toFixed(1)}%`}</b> over {stats.eta_error_samples} tickets</p>
          </section>
        )}
      </aside>
    </div>
  );
}

function JoinQr({ queueId }) {
  const [qr, setQr] = useState(null);
  useEffect(() => { api(`/api/queues/${queueId}/qr`, auth).then(setQr).catch(() => {}); }, [queueId]);
  if (!qr) return null;
  return (
    <section className="card center">
      <h3>Join QR (rotates daily)</h3>
      <img className="qr" alt="Join QR code" src={`data:image/png;base64,${qr.png_base64}`} />
      <a href={qr.join_url} target="_blank" rel="noreferrer" className="small-link">{qr.join_url}</a>
    </section>
  );
}

// Shown on the counter's screen. The nonce rotates every 30 s, so a photo of it stops working.
function CounterQr({ counters }) {
  const [counterId, setCounterId] = useState(counters[0]?.id);
  const [qr, setQr] = useState(null);
  useEffect(() => {
    if (!counterId) return undefined;
    let timer;
    const load = async () => {
      try {
        const n = await api(`/api/counters/${counterId}/nonce`, auth);
        setQr(n);
        timer = setTimeout(load, Math.max(1, n.expires_in) * 1000);
      } catch {
        timer = setTimeout(load, 5000);
      }
    };
    load();
    return () => clearTimeout(timer);
  }, [counterId]);
  return (
    <section className="card center">
      <h3>Counter check-in QR</h3>
      <select value={counterId} onChange={(e) => setCounterId(Number(e.target.value))}>
        {counters.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>
      {qr && <img className="qr" alt="Counter check-in QR" src={`data:image/png;base64,${qr.png_base64}`} />}
      {qr && <p className="muted small">Refreshes in {Math.round(qr.expires_in)} s</p>}
    </section>
  );
}

function CreateQueue({ onCreated }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", counters: 2, default_service_sec: 80 });
  const [error, setError] = useState(null);
  if (!open) return <button className="btn ghost small" onClick={() => setOpen(true)}>+ New queue</button>;
  async function submit(e) {
    e.preventDefault();
    try {
      onCreated(await api("/api/queues", { method: "POST", body: { ...form, counters: Number(form.counters), default_service_sec: Number(form.default_service_sec) }, ...auth }));
      setOpen(false);
    } catch (err) {
      setError(err.message);
    }
  }
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return (
    <form className="card form row" onSubmit={submit}>
      <label>Name<input value={form.name} onChange={set("name")} required /></label>
      <label>Counters<input type="number" min="1" max="50" value={form.counters} onChange={set("counters")} /></label>
      <label>Default service (s)<input type="number" min="1" value={form.default_service_sec} onChange={set("default_service_sec")} /></label>
      <button className="btn">Create</button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
