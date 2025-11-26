import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
    // This is a simplified middleware. 
    // In a real app with Firebase, we'd verify the session cookie here.
    // Since we are using client-side auth primarily, we'll rely on client-side checks for now
    // or use a library like next-firebase-auth-edge for edge compatibility.

    // For this implementation, we will allow the client-side AuthContext to handle redirects
    // to keep it simple and compatible with standard Firebase SDK.
    // However, we can still protect specific API routes if needed.

    return NextResponse.next();
}

export const config = {
    matcher: [
        /*
         * Match all request paths except for the ones starting with:
         * - api (API routes)
         * - _next/static (static files)
         * - _next/image (image optimization files)
         * - favicon.ico (favicon file)
         */
        "/((?!api|_next/static|_next/image|favicon.ico).*)",
    ],
};
