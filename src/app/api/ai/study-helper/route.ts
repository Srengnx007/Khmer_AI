import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { question, subject } = await req.json();

        if (!question) {
            return NextResponse.json({ error: "Question is required" }, { status: 400 });
        }

        const prompt = `
      You are a helpful AI Study Assistant for Cambodian students.
      Subject: ${subject || "General"}
      Question: ${question}
      
      Please explain the answer clearly in Khmer.
      If appropriate, provide a short quiz (3 questions) at the end to test understanding.
      Format the output with Markdown.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Study Helper API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
