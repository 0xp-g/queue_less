// Per-visitor conveniences kept in the browser. The server is still the source of truth.

function safe(fn, fallback) {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

export function deviceId() {
  return safe(() => {
    let id = localStorage.getItem("ql.device");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("ql.device", id);
    }
    return id;
  }, undefined);
}

// One idempotency key per join attempt: a retry after a network error reuses it,
// so the server returns the same ticket instead of creating a second one.
export function joinRequestId(queueId) {
  return safe(() => {
    const key = `ql.joinReq.${queueId}`;
    let id = sessionStorage.getItem(key);
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem(key, id);
    }
    return id;
  }, crypto.randomUUID());
}

export function clearJoinRequestId(queueId) {
  safe(() => sessionStorage.removeItem(`ql.joinReq.${queueId}`));
}

export const tickets = {
  all: () => safe(() => JSON.parse(localStorage.getItem("ql.tickets") || "{}"), {}),
  get(queueId) {
    return this.all()[queueId];
  },
  save(queueId, token) {
    safe(() => localStorage.setItem("ql.tickets", JSON.stringify({ ...this.all(), [queueId]: token })));
  },
  remove(queueId) {
    const all = this.all();
    delete all[queueId];
    safe(() => localStorage.setItem("ql.tickets", JSON.stringify(all)));
  },
};
