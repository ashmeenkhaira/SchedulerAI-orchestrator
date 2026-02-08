import { GoogleGenAI, Type, Schema } from "@google/genai";
import { MetricsPayload, AgentDecision } from '../types';
import { SYSTEM_PROMPT, GEMINI_MODEL } from '../constants';

// We use process.env because your vite.config.ts defines it
const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

// FIXED SCHEMA: 'params' MUST have explicit properties to be valid
const responseSchema: Schema = {
  type: Type.OBJECT,
  properties: {
    action: { type: Type.STRING },
    strategy: { type: Type.STRING, nullable: true },
    params: { 
      type: Type.OBJECT,
      nullable: true,
      properties: {
        // defining these properties fixes the "should be non-empty" error
        priority: { type: Type.STRING, nullable: true },
        target_server: { type: Type.INTEGER, nullable: true },
        reason: { type: Type.STRING, nullable: true }
      } 
    },
    message: { type: Type.STRING },
  },
  required: ['action', 'message'],
};

export const askGemini = async (metrics: MetricsPayload): Promise<AgentDecision> => {
  try {
    const response = await ai.models.generateContent({
      model: GEMINI_MODEL,
      contents: JSON.stringify(metrics),
      config: {
        systemInstruction: SYSTEM_PROMPT,
        responseMimeType: "application/json",
        responseSchema: responseSchema,
      },
    });

    const text = response.text;
    if (!text) {
      throw new Error("Empty response from Gemini");
    }
    
    return JSON.parse(text) as AgentDecision;
  } catch (error) {
    console.error("Gemini Agent Error:", error);
    return {
      action: "explain",
      strategy: null,
      params: {},
      message: "Agent connection interrupted. Decision making offline."
    };
  }
};