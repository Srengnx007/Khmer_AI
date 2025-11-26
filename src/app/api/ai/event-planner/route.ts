import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { eventType, guestCount, location, budget } = await req.json();

        if (!eventType) {
            return NextResponse.json({ error: "Event type is required" }, { status: 400 });
        }

        const prompt = `
      You are an expert Event Planner.
      Event Type: ${eventType}
      Guests: ${guestCount || "Unknown"}
      Location: ${location || "Cambodia"}
      Budget: ${budget || "Flexible"}
      
      Create a detailed event plan.
      Include a schedule, budget breakdown, and venue suggestions.
      Response must be in Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Event Planner API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
