import type { components, paths } from "./openapi";

const TOKEN_KEY = "steelmind_api_token";

export function getApiToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setApiToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    const old = window.localStorage.getItem(TOKEN_KEY);
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
    // Same-tab dispatch — the native `storage` event only fires for *other*
    // tabs, so subscribers in this tab (e.g. useRobotSocket) won't see the
    // change otherwise.
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: TOKEN_KEY,
        oldValue: old,
        newValue: token,
        storageArea: window.localStorage,
      }),
    );
  } catch {
    // ignore
  }
}

export function authHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// --- Command signing (replay protection) -----------------------------------
// Must match backend/signing.py canonical(): compact, recursively key-sorted
// JSON so client and server sign byte-identical strings.
export function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const obj = value as Record<string, unknown>;
  const body = Object.keys(obj)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`)
    .join(",");
  return `{${body}}`;
}

function _toHex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// HMAC-SHA256(key, "ts:nonce:command:canonical(params)") as lowercase hex.
export async function signCommand(
  key: string,
  command: string,
  params: Record<string, unknown>,
  ts: number,
  nonce: string,
): Promise<string> {
  const enc = new TextEncoder();
  const msg = `${ts}:${nonce}:${command}:${stableStringify(params ?? {})}`;
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    enc.encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return _toHex(await crypto.subtle.sign("HMAC", cryptoKey, enc.encode(msg)));
}

export type ApiAICommandRequest =
  paths["/ai-command"]["post"]["requestBody"]["content"]["application/json"];
export type ApiAICommandResponse = components["schemas"]["AICommandResponse"];
export type ApiCommandRequest =
  paths["/command"]["post"]["requestBody"]["content"]["application/json"];
export type ApiCommandResponse = components["schemas"]["CommandResponse"];

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
