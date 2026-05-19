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
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

export function authHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
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
