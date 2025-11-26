import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { articleText } = await req.json();

        if (!articleText) {
            return NextResponse.json({ error: "Article text is required" }, { status: 400 });
        }

        const prompt = `
      You are an AI News Summarizer.
      Article:
      ${articleText}
      
      Summarize the key points of this article in Khmer.
      Keep it concise and easy to understand.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("News Summarizer API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
