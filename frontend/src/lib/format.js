export function formatEta(sec) {
  if (sec == null) return "-";
  if (sec < 30) return "Any moment";
  const min = Math.round(sec / 60);
  if (min < 60) return `~${min} min`;
  return `~${Math.floor(min / 60)} h ${min % 60} min`;
}

export function pad(seq) {
  return seq == null ? "-" : String(seq).padStart(3, "0");
}
