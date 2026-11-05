// One module instance shares revisions across API imports with different cache versions.
export function createUuid() {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();

  // randomUUID is restricted to secure contexts, while the app may be opened
  // over plain HTTP on a trusted LAN. getRandomValues remains available there.
  const bytes = new Uint8Array(16);
  if (typeof globalThis.crypto?.getRandomValues === "function") globalThis.crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.random() * 256;
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

let token;
try {
  token = sessionStorage.getItem("lblstdio:annotation-session");
  if (!token) { token = createUuid(); sessionStorage.setItem("lblstdio:annotation-session", token); }
} catch { token = createUuid(); }
export const annotationSession = token;
const revisions = new Map();
export function annotationRevision(id) { return revisions.get(id); }
export function setAnnotationRevision(id, value) { revisions.set(id, Number(value)); }
