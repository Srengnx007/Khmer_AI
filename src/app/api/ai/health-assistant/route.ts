import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { symptoms } = await req.json();

        if (!symptoms) {
            return NextResponse.json({ error: "Symptoms are required" }, { status: 400 });
        }

        const prompt = `
      You are an AI Health Assistant.
      Symptoms: ${symptoms}
      
      Provide general health advice and potential causes.
      IMPORTANT: Start with a disclaimer that you are an AI and this is not a medical diagnosis. Advise seeing a doctor for serious issues.
      Suggest home remedies or lifestyle changes if applicable.
      Response must be in Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Health Assistant API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
