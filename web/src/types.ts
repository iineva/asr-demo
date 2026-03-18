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

export type TranscriptStreamEvent = {
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

export type TranscriptHistoryItem = {
  id: string;
  createdAt: string;
  sourceType: "recorded" | "uploaded";
  audioName: string;
  audioBlob: Blob;
  audioUrl: string;
  result: TranscriptResult;
};
