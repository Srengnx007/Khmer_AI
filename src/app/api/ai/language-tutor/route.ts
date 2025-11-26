import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { text, targetLanguage = "English" } = await req.json();

        if (!text) {
            return NextResponse.json({ error: "Text is required" }, { status: 400 });
        }

        const prompt = `
      You are an AI Language Tutor.
      Student Input: ${text}
      Target Language: ${targetLanguage}
      
      1. Correct any grammar mistakes in the input.
      2. Explain the corrections in Khmer.
      3. Provide 3 similar sentences for practice.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Language Tutor API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
