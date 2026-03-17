import { transcribeAudio } from "./api";

describe("transcribeAudio", () => {
  it("posts to same-origin /api/transcribe by default", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        result: {
          requested_language: "auto",
          detected_language: "yue",
          language_probability: 0.9,
          text: "hello",
          segments: [],
        },
      }),
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      await transcribeAudio(new Blob(["audio"], { type: "audio/webm" }), "auto");
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/transcribe",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    );
  });
});
