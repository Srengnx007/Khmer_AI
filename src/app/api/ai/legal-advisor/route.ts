import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { question } = await req.json();

        if (!question) {
            return NextResponse.json({ error: "Question is required" }, { status: 400 });
        }

        const prompt = `
      You are an AI Legal Advisor for Cambodia.
      Question: ${question}
      
      Provide general legal information based on Cambodian law.
      IMPORTANT: Start with a disclaimer that you are an AI and this is not professional legal advice.
      Explain relevant laws and potential steps to take.
      Response must be in Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Legal Advisor API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
