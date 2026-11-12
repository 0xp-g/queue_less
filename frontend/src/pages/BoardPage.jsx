import { useParams } from "react-router-dom";
import { pad } from "../lib/format";
import { useQueueSocket } from "../lib/useQueueSocket";

// Big-screen display: what each counter is serving right now.
export default function BoardPage() {
  const { queueId } = useParams();
  const { state, mode } = useQueueSocket({ queueId, pollPath: `/api/queues/${queueId}/public` });
  if (!state) return <main className="board"><p>Connecting...</p></main>;
  return (
    <main className="board">
      <header>
        <h1>{state.queue_name}</h1>
        <p>{state.waiting_count} waiting · {state.queue_status}</p>
      </header>
      <div className="board-grid">
        {state.counters.map((c) => (
          <div key={c.counter_id} className={`board-cell ${c.status ?? "idle"}`}>
            <p className="board-label">{c.label}</p>
            <p className="board-number">{pad(c.seq)}</p>
          </div>
        ))}
      </div>
      <footer className={`conn conn-${mode}`}>{mode}</footer>
    </main>
  );
}
