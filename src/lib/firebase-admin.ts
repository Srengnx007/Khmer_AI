import "server-only";
import { initializeApp, getApps, cert, getApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getFirestore } from "firebase-admin/firestore";

// In a real production environment, you should use a service account JSON file.
// For this setup, we'll try to use the default credentials or environment variables if provided.
// However, Vercel + Firebase often requires the private key.
// We will assume standard env vars are set for the service account if available,
// or fallback to a basic init which might limit some admin features if not properly authenticated.

const firebaseAdminConfig = {
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
    privateKey: process.env.FIREBASE_PRIVATE_KEY?.replace(/\\n/g, "\n"),
};

export function initAdmin() {
    if (getApps().length <= 0) {
        if (firebaseAdminConfig.clientEmail && firebaseAdminConfig.privateKey) {
            initializeApp({
                credential: cert(firebaseAdminConfig),
            });
        } else {
            // Fallback for local dev without service account (might fail for some admin ops)
            initializeApp({
                projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
            });
        }
    }
    return getApp();
}



export function getAdminAuth() {
    return getAuth(initAdmin());
}

export function getAdminDb() {
    return getFirestore(initAdmin());
}
