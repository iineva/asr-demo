import type { TranscriptResult, TranscriptSegment } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

type StreamEvent = {
  type: string;
  text: string;
  language: string | null;
  detail?: {
    requested_language?: TranscriptResult["requested_language"];
    segments?: TranscriptSegment[];
    language_probability?: number;
    message?: string;
  } | null;
};

function inferUploadFilename(file: Blob): string {
  const normalizedType = file.type.toLowerCase();

  if (normalizedType.includes("mp4")) {
    return "recording.m4a";
  }

  if (normalizedType.includes("mpeg") || normalizedType.includes("mp3")) {
    return "recording.mp3";
  }

  if (normalizedType.includes("wav")) {
    return "recording.wav";
  }

  return "recording.webm";
}

function parseStreamEvents(payload: string): StreamEvent[] {
  return payload
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as StreamEvent);
}

function buildTranscriptResultFromEvent(event: StreamEvent, fallbackLanguage: string): TranscriptResult {
  const segments = event.detail?.segments ?? [];
  return {
    requested_language: (event.detail?.requested_language ?? fallbackLanguage) as TranscriptResult["requested_language"],
    detected_language: event.language,
    language_probability: event.detail?.language_probability ?? 0,
    text: event.text,
    segments,
  };
}

async function readResponseText(response: Response): Promise<string> {
  if (response.body) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let combined = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      combined += decoder.decode(value, { stream: true });
    }

    combined += decoder.decode();
    return combined;
  }

  return await response.text();
}

export async function transcribeAudio(file: Blob, language: string): Promise<TranscriptResult> {
  const formData = new FormData();
  const uploadFile =
    file instanceof File ? file : new File([file], inferUploadFilename(file), { type: file.type || "audio/webm" });
  formData.append("file", uploadFile);
  formData.append("language", language);

  const response = await fetch(`${API_BASE_URL}/transcribe/stream`, {
    method: "POST",
    body: formData,
  });

  const payloadText = await readResponseText(response);
  const streamEvents = parseStreamEvents(payloadText);

  if (!response.ok) {
    const errorEvent = streamEvents.find((event) => event.type === "error");
    throw new Error(errorEvent?.detail?.message ?? "转写失败");
  }

  const completedEvent = [...streamEvents].reverse().find((event) => event.type === "completed");
  if (!completedEvent) {
    const errorEvent = streamEvents.find((event) => event.type === "error");
    throw new Error(errorEvent?.detail?.message ?? "转写失败");
  }

  return buildTranscriptResultFromEvent(completedEvent, language);
}
