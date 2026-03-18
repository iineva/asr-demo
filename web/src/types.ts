export type TranscriptSegment = {
  start: number;
  end: number;
  text: string;
};

export type TranscriptResult = {
  requested_language: "auto" | "my" | "yue";
  detected_language: string | null;
  language_probability: number;
  text: string;
  segments: TranscriptSegment[];
};

export type TranscriptHistoryItem = {
  id: string;
  createdAt: string;
  sourceType: "recorded" | "uploaded";
  audioName: string;
  audioBlob: Blob;
  audioUrl: string;
  result: TranscriptResult;
};
