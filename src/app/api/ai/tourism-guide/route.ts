import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { city, duration, interests } = await req.json();

        if (!city) {
            return NextResponse.json({ error: "City is required" }, { status: 400 });
        }

        const prompt = `
      You are an expert Tour Guide for Cambodia.
      Destination: ${city}
      Duration: ${duration || "1 day"}
      Interests: ${interests || "General sightseeing"}
      
      Create a detailed travel itinerary.
      Include popular spots, hidden gems, and food recommendations.
      Response must be in Khmer.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Tourism Guide API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
