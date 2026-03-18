import type { TranscriptResult, TranscriptStreamEvent } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";
const TRANSCRIBE_REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_TRANSCRIBE_REQUEST_TIMEOUT_MS ?? "180000");

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = TRANSCRIBE_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("识别请求超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

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

function buildUploadFile(file: Blob): File {
  return file instanceof File ? file : new File([file], inferUploadFilename(file), { type: file.type || "audio/webm" });
}

function buildTranscriptResultFromEvent(
  event: TranscriptStreamEvent,
  fallbackLanguage: string,
): TranscriptResult {
  const segments = event.detail?.segments ?? [];
  return {
    requested_language: (event.detail?.requested_language ?? fallbackLanguage) as TranscriptResult["requested_language"],
    detected_language: event.language,
    language_probability: event.detail?.language_probability ?? 0,
    text: event.text,
    segments,
  };
}

function parseEventLine(line: string): TranscriptStreamEvent {
  return JSON.parse(line) as TranscriptStreamEvent;
}

async function consumeTextResponse(
  response: Response,
  onEvent?: (event: TranscriptStreamEvent) => void,
): Promise<TranscriptStreamEvent[]> {
  const payload = await response.text();
  return payload
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const event = parseEventLine(line);
      onEvent?.(event);
      return event;
    });
}

async function consumeNdjsonResponse(
  response: Response,
  onEvent?: (event: TranscriptStreamEvent) => void,
): Promise<TranscriptStreamEvent[]> {
  if (!response.body) {
    return await consumeTextResponse(response, onEvent);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const events: TranscriptStreamEvent[] = [];
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      const event = parseEventLine(trimmed);
      events.push(event);
      onEvent?.(event);
    }
  }

  buffer += decoder.decode();
  const tail = buffer.trim();
  if (tail) {
    const event = parseEventLine(tail);
    events.push(event);
    onEvent?.(event);
  }

  return events;
}

async function postLegacyTranscription(uploadFile: File, language: string): Promise<TranscriptResult> {
  const formData = new FormData();
  formData.append("file", uploadFile);
  formData.append("language", language);

  const response = await fetchWithTimeout(`${API_BASE_URL}/transcribe`, {
    method: "POST",
    body: formData,
  });

  const payload = (await response.json()) as {
    detail?: string;
    result?: TranscriptResult;
  };

  if (!response.ok || !payload.result) {
    throw new Error(payload.detail ?? "转写失败");
  }

  return payload.result;
}

export async function transcribeAudioStream(
  file: Blob,
  language: string,
  onEvent?: (event: TranscriptStreamEvent) => void,
): Promise<TranscriptResult> {
  const uploadFile = buildUploadFile(file);
  const formData = new FormData();
  formData.append("file", uploadFile);
  formData.append("language", language);

  const response = await fetchWithTimeout(`${API_BASE_URL}/transcribe/stream`, {
    method: "POST",
    body: formData,
  });

  const streamEvents = await consumeNdjsonResponse(response, onEvent);

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

export async function transcribeAudio(file: Blob, language: string): Promise<TranscriptResult> {
  const uploadFile = buildUploadFile(file);

  try {
    return await transcribeAudioStream(uploadFile, language);
  } catch {
    return await postLegacyTranscription(uploadFile, language);
  }
}
