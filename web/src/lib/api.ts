import type { TranscriptResult } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function transcribeAudio(file: Blob, language: string): Promise<TranscriptResult> {
  const formData = new FormData();
  const uploadFile =
    file instanceof File ? file : new File([file], "recording.webm", { type: file.type || "audio/webm" });
  formData.append("file", uploadFile);
  formData.append("language", language);

  const response = await fetch(`${API_BASE_URL}/transcribe`, {
    method: "POST",
    body: formData,
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? "转写失败");
  }

  return payload.result as TranscriptResult;
}
