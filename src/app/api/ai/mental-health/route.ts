import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { message, history } = await req.json();

        if (!message) {
            return NextResponse.json({ error: "Message is required" }, { status: 400 });
        }

        const prompt = `
      You are a supportive and empathetic AI Mental Health Companion.
      User Message: ${message}
      Conversation History: ${JSON.stringify(history || [])}
      
      Provide a comforting and helpful response in Khmer.
      IMPORTANT: You are NOT a doctor. Do not diagnose. If the user seems suicidal or in danger, urge them to seek professional help immediately.
      Keep the tone warm and understanding.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Mental Health API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
