import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";
import { adminAuth, adminDb } from "@/lib/firebase-admin";
import { z } from "zod";

const inputSchema = z.object({
    text: z.string().min(1).max(5000),
    targetLanguage: z.string().optional().default("English"),
});

export async function POST(req: NextRequest) {
    try {
        // 1. Verify Authentication
        const authHeader = req.headers.get("Authorization");
        if (!authHeader?.startsWith("Bearer ")) {
            return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
        }
        const token = authHeader.split("Bearer ")[1];
        const decodedToken = await adminAuth.verifyIdToken(token);
        const uid = decodedToken.uid;

        // 2. Rate Limiting (Simple implementation using Firestore)
        // Limit: 20 requests per hour
        const now = new Date();
        const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
        const usageRef = adminDb.collection("ai_usage");
        const usageQuery = await usageRef
            .where("uid", "==", uid)
            .where("timestamp", ">", oneHourAgo)
            .count()
            .get();

        if (usageQuery.data().count >= 20) {
            return NextResponse.json({ error: "Rate limit exceeded" }, { status: 429 });
        }

        // 3. Input Validation
        const body = await req.json();
        const validation = inputSchema.safeParse(body);

        if (!validation.success) {
            return NextResponse.json({ error: "Invalid input", details: validation.error.issues }, { status: 400 });
        }

        const { text, targetLanguage } = validation.data;

        const prompt = `
      You are an expert Khmer-English translator.
      Translate the following text to ${targetLanguage}.
      If the input is in Khmer, translate to English.
      If the input is in English, translate to Khmer.
      Provide ONLY the translation, no explanations.
      
      Input: ${text}
    `;

        const result = await generateAIResponse(prompt);

        // 4. Log Usage
        await usageRef.add({
            uid,
            tool: "translator",
            timestamp: adminDb.FieldValue.serverTimestamp(),
            inputLength: text.length,
        });

        return NextResponse.json({ result });
    } catch (error) {
        console.error("Translator API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
