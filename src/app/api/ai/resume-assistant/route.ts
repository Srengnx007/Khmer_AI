import { NextRequest, NextResponse } from "next/server";
import { generateAIResponse } from "@/lib/gemini";

export async function POST(req: NextRequest) {
    try {
        const { resumeText, jobDescription } = await req.json();

        if (!resumeText) {
            return NextResponse.json({ error: "Resume text is required" }, { status: 400 });
        }

        const prompt = `
      You are an expert Career Coach and Resume Reviewer.
      
      Resume Content:
      ${resumeText}
      
      Target Job Description (Optional):
      ${jobDescription || "General Application"}
      
      Analyze the resume.
      Provide feedback on strengths and weaknesses.
      Suggest improvements for formatting, content, and keywords.
      If a job description is provided, tailor the advice to that role.
      Provide the response in both Khmer and English.
    `;

        const result = await generateAIResponse(prompt);
        return NextResponse.json({ result });
    } catch (error) {
        console.error("Resume Assistant API Error:", error);
        return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
    }
}
