import { NextResponse, type NextRequest } from "next/server";

/**
 * Locks the app behind a password and passes the API token to the backend.
 *
 * - RAHBEH_PASSWORD (optional): browser login prompt (HTTP Basic auth, user "rahbeh" or RAHBEH_USER).
 * - API_TOKEN (optional): added server-side to every /api request, so the browser never sees it.
 */
export function proxy(request: NextRequest) {
  const password = process.env.RAHBEH_PASSWORD;
  if (password) {
    const user = process.env.RAHBEH_USER || "rahbeh";
    const header = request.headers.get("authorization") || "";
    const [scheme, encoded] = header.split(" ");
    let ok = false;
    if (scheme === "Basic" && encoded) {
      const decoded = atob(encoded);
      const i = decoded.indexOf(":");
      ok = timingSafeEqual(decoded.slice(0, i), user) && timingSafeEqual(decoded.slice(i + 1), password);
    }
    if (!ok) {
      return new NextResponse("Authentication required", {
        status: 401,
        headers: { "WWW-Authenticate": 'Basic realm="Rahbeh", charset="UTF-8"' },
      });
    }
  }
  const token = process.env.API_TOKEN;
  if (token && request.nextUrl.pathname.startsWith("/api")) {
    const headers = new Headers(request.headers);
    headers.set("x-rahbeh-token", token);
    headers.delete("authorization");
    return NextResponse.next({ request: { headers } });
  }
  return NextResponse.next();
}

function timingSafeEqual(a: string, b: string) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
