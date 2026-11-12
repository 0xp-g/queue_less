import { useEffect, useRef, useState } from "react";
import { api, wsUrl } from "./api";

// Live queue state over WebSocket, with the fallbacks from ADR-0005:
//  * every (re)connect starts with a server snapshot, so a reconnecting client is never stale
//  * messages older than what we already have (lower version) are ignored
//  * while the socket is down, poll the REST endpoint every 3 s
//  * reconnect with exponential backoff
export function useQueueSocket({ queueId, ticketToken, pollPath, onMessage }) {
  const [state, setState] = useState(null);
  const [mode, setMode] = useState("connecting"); // live | polling | connecting | closed
  const [error, setError] = useState(null);
  const versionRef = useRef(-1);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!queueId) return undefined;
    let ws;
    let stopped = false;
    let retry = 0;
    let pollTimer;
    let retryTimer;

    const apply = (msg) => {
      if (msg.version != null && msg.version < versionRef.current) return; // out of order
      if (msg.version != null) versionRef.current = msg.version;
      setState(msg);
      onMessageRef.current?.(msg);
    };

    const startPolling = () => {
      if (!pollPath || pollTimer) return;
      const tick = async () => {
        try {
          apply(await api(pollPath));
        } catch (e) {
          if (e.status === 404) setError(e);
        }
      };
      tick();
      pollTimer = setInterval(tick, 3000);
    };
    const stopPolling = () => {
      clearInterval(pollTimer);
      pollTimer = undefined;
    };

    const connect = () => {
      const qs = ticketToken ? `?ticket=${encodeURIComponent(ticketToken)}` : "";
      ws = new WebSocket(wsUrl(`/ws/queues/${queueId}${qs}`));
      ws.onopen = () => {
        retry = 0;
        setMode("live");
        stopPolling();
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "ping") return;
        apply(msg);
      };
      ws.onclose = (ev) => {
        if (stopped) return;
        if (ev.code === 4404) {
          setMode("closed");
          setError({ status: 404, message: "Not found." });
          return;
        }
        setMode("polling");
        startPolling();
        retryTimer = setTimeout(connect, Math.min(15000, 500 * 2 ** retry++));
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      stopPolling();
      ws?.close();
    };
  }, [queueId, ticketToken, pollPath]);

  return { state, mode, error };
}
