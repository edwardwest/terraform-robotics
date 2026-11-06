// Forwards a request to the backend API. API_URL is read at request time, so one built image works in every
// environment (local Docker, Cloud Run) — unlike next.config rewrites, which are fixed at build time.
import { auth } from "@clerk/nextjs/server";

const HOP_BY_HOP = new Set(["host", "connection", "content-length", "transfer-encoding", "keep-alive", "upgrade", "cookie"]);

export async function proxy(request: Request, prefix: "/api" | "/files", path: string[]): Promise<Response> {
  const base = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");
  const url = new URL(request.url);
  const target = `${base}${prefix}/${path.map(encodeURIComponent).join("/")}${url.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });

  // The browser never sees the API: the session token is attached here, server-side.
  const { getToken } = await auth();
  const token = await getToken();
  if (token) headers.set("authorization", `Bearer ${token}`);
  else headers.delete("authorization");

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    // required by Node's fetch to stream a request body (uploads)
    ...(hasBody ? { duplex: "half" } : {}),
    redirect: "manual",
    cache: "no-store",
  } as RequestInit);

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}
