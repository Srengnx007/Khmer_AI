import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { location } = await req.json();

        if (!location) {
            return NextResponse.json({ error: "Location is required" }, { status: 400 });
        }

        const prompt = `
      You are an AI Environmental Advisor for Cambodia.
      Location: ${location}
      
      Provide an environmental risk report for this location.
      Include flood risks, pollution levels (estimated), and weather patterns.
      Suggest precautions and eco-friendly practices.
      Response must be in Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Environmental Advisor API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
