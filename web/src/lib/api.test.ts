import { transcribeAudio } from "./api";

describe("transcribeAudio", () => {
  it("posts to same-origin /api/transcribe/stream by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: null,
      text: vi.fn().mockResolvedValue(
        [
          JSON.stringify({ type: "queued", text: "", language: "auto", detail: null }),
          JSON.stringify({
            type: "completed",
            text: "hello",
            language: "yue",
            detail: {
              requested_language: "auto",
              language_probability: 0.9,
              segments: [],
              timing: { convert_ms: 120, vad_ms: 30, decode_ms: 450 },
            },
          }),
        ].join("\n"),
      ),
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      const result = await transcribeAudio(new Blob(["audio"], { type: "audio/webm" }), "auto");
      expect(result.timing).toEqual({ convert_ms: 120, vad_ms: 30, decode_ms: 450 });
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/transcribe/stream",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    );
  });

  it("wraps audio/mp4 recordings as an m4a upload", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: null,
      text: vi.fn().mockResolvedValue(
        JSON.stringify({
          type: "completed",
          text: "hello",
          language: "yue",
          detail: {
            requested_language: "auto",
            language_probability: 0.9,
            segments: [],
            timing: { convert_ms: 50, vad_ms: 10, decode_ms: 120 },
          },
        }),
      ),
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      await transcribeAudio(new Blob(["audio"], { type: "audio/mp4" }), "auto");
    } finally {
      vi.unstubAllGlobals();
    }

    const request = fetchMock.mock.calls[0]?.[1] as { body: FormData } | undefined;
    const uploadFile = request?.body.get("file");

    expect(uploadFile).toBeInstanceOf(File);
    expect((uploadFile as File).name).toBe("recording.m4a");
    expect((uploadFile as File).type).toBe("audio/mp4");
  });

  it("falls back to the legacy upload endpoint when streamed transcription fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        body: null,
        text: vi.fn().mockResolvedValue(JSON.stringify({ type: "queued", text: "", language: "auto", detail: null })),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          result: {
            requested_language: "auto",
            detected_language: "yue",
            language_probability: 0.9,
            text: "fallback result",
            segments: [],
            timing: { convert_ms: 80, vad_ms: 20, decode_ms: 300 },
          },
        }),
      });

    vi.stubGlobal("fetch", fetchMock);

    try {
      const result = await transcribeAudio(new Blob(["audio"], { type: "audio/webm" }), "auto");
      expect(result.text).toBe("fallback result");
      expect(result.timing).toEqual({ convert_ms: 80, vad_ms: 20, decode_ms: 300 });
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/transcribe/stream");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/transcribe");
  });
});
