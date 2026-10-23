// One module instance shares revisions across API imports with different cache versions.
let token;
try {
  token = sessionStorage.getItem("lblstdio:annotation-session");
  if (!token) { token = crypto.randomUUID(); sessionStorage.setItem("lblstdio:annotation-session", token); }
} catch { token = crypto.randomUUID(); }
export const annotationSession = token;
const revisions = new Map();
export function annotationRevision(id) { return revisions.get(id); }
export function setAnnotationRevision(id, value) { revisions.set(id, Number(value)); }
