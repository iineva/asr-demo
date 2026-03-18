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
            },
          }),
        ].join("\n"),
      ),
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      await transcribeAudio(new Blob(["audio"], { type: "audio/webm" }), "auto");
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
});
