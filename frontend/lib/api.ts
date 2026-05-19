export function deriveApiBase(): string {
  const ws = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";
  try {
    const url = new URL(ws);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return "http://localhost:8000";
  }
}
