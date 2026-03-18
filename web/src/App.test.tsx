import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App, { didCrossCancelThreshold } from "./App";
import type { RecorderSession } from "./lib/recorder";

function createSession(): RecorderSession {
  return {
    stop: vi.fn().mockResolvedValue(new Blob(["audio"], { type: "audio/webm" })),
    cancel: vi.fn().mockResolvedValue(undefined),
  };
}

describe("App", () => {
  it("shows recording state while pressing and idle state after release", async () => {
    render(<App createRecorderSession={vi.fn().mockResolvedValue(createSession())} />);

    const trigger = screen.getByRole("button", { name: /按住说话/i });
    fireEvent.pointerDown(trigger, { clientY: 0 });
    expect(await screen.findByText("松开发送，上滑取消")).toBeInTheDocument();

    fireEvent.pointerUp(trigger);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /按住说话/i })).toBeInTheDocument();
    });
  });

  it("uploads audio on release and renders the transcription result", async () => {
    const mockTranscribe = vi.fn().mockResolvedValue({
      requested_language: "yue",
      detected_language: "yue",
      language_probability: 0.97,
      text: "你好世界",
      segments: [{ start: 0, end: 1.2, text: "你好世界" }],
      timing: { convert_ms: 120, vad_ms: 40, decode_ms: 680 },
    });

    render(
      <App
        transcribeAudio={mockTranscribe}
        createRecorderSession={vi.fn().mockResolvedValue(createSession())}
      />,
    );

    const trigger = screen.getByRole("button", { name: /按住说话/i });
    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("松开发送，上滑取消");
    fireEvent.pointerUp(trigger);

    await waitFor(() => expect(mockTranscribe).toHaveBeenCalledTimes(1));
    expect((await screen.findAllByText("你好世界")).length).toBeGreaterThan(0);
    expect(screen.getByText(/识别语言 yue/i)).toBeInTheDocument();
    expect(screen.getByText("转码 120 ms")).toBeInTheDocument();
    expect(screen.getByText("VAD 40 ms")).toBeInTheDocument();
    expect(screen.getByText("识别 680 ms")).toBeInTheDocument();
  });

  it("renders a floating dock with the record trigger while history content stays above it", async () => {
    const mockTranscribe = vi
      .fn()
      .mockResolvedValueOnce({
        requested_language: "yue",
        detected_language: "yue",
        language_probability: 0.98,
        text: "第一条",
        segments: [{ start: 0, end: 1.2, text: "第一条" }],
      })
      .mockResolvedValueOnce({
        requested_language: "my",
        detected_language: "my",
        language_probability: 0.95,
        text: "第二条",
        segments: [{ start: 0, end: 1.5, text: "第二条" }],
      });

    const createRecorderSession = vi
      .fn()
      .mockImplementation(() => Promise.resolve(createSession()));

    render(
      <App transcribeAudio={mockTranscribe} createRecorderSession={createRecorderSession} />,
    );

    const trigger = screen.getByRole("button", { name: /按住说话/i });

    for (let i = 0; i < 2; i += 1) {
      fireEvent.pointerDown(trigger, { clientY: 0 });
      await screen.findByText("松开发送，上滑取消");
      fireEvent.pointerUp(trigger);
      await waitFor(() => expect(mockTranscribe).toHaveBeenCalledTimes(i + 1));
    }

    await screen.findByText("Latest Result");
    await screen.findByText("History");

    const dock = await screen.findByTestId("record-dock");
    const pageShell = screen.getByTestId("page-shell");
    expect(dock.previousElementSibling).toBe(pageShell);
    const recordButton = within(dock).getByRole("button", { name: /按住说话/i });
    const uploadButton = within(dock).getByRole("button", { name: /上传音频文件/i });
    expect(recordButton).toBeInTheDocument();
    expect(uploadButton).toBeInTheDocument();
    expect(uploadButton).toHaveTextContent("文件");
    expect(within(dock).queryByText("History")).not.toBeInTheDocument();

    const historySection = screen.getByTestId("history-section");
    expect(historySection).toBeInTheDocument();
    expect(within(pageShell).getByText("History")).toBeInTheDocument();
  });

  it("cancels recording without upload when the pointer is cancelled", async () => {
    const mockTranscribe = vi.fn();
    const session = createSession();

    render(
      <App
        transcribeAudio={mockTranscribe}
        createRecorderSession={vi.fn().mockResolvedValue(session)}
      />,
    );

    const trigger = screen.getByRole("button", { name: /按住说话/i });
    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("松开发送，上滑取消");
    fireEvent.pointerCancel(trigger);

    await waitFor(() => expect(mockTranscribe).not.toHaveBeenCalled());
    expect(session.cancel).toHaveBeenCalledTimes(1);
  });

  it("uploads a selected audio file and renders the transcription result", async () => {
    const mockTranscribe = vi.fn().mockResolvedValue({
      requested_language: "auto",
      detected_language: "my",
      language_probability: 0.99,
      text: "မင်္ဂလာပါ",
      segments: [{ start: 0, end: 1.5, text: "မင်္ဂလာပါ" }],
    });

    render(<App transcribeAudio={mockTranscribe} />);

    const input = screen.getAllByLabelText(/上传音频文件/i).find((element) => element.tagName === "INPUT") as HTMLInputElement;
    const file = new File(["audio"], "sample.webm", { type: "audio/webm" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockTranscribe).toHaveBeenCalledWith(file, "auto"));
    expect(await screen.findByText(/识别语言 my/i)).toBeInTheDocument();
    expect((await screen.findAllByText("မင်္ဂလာပါ")).length).toBeGreaterThan(0);
  });

  it("renders streaming transcript updates before upload completion", async () => {
    let resolveStream: (value: {
      requested_language: "auto";
      detected_language: "yue";
      language_probability: number;
      text: string;
      segments: { start: number; end: number; text: string }[];
    }) => void = () => {
      /* placeholder */
    };

    const mockStream = vi.fn().mockImplementation(
      (_file: Blob, _language: string, onEvent?: (event: { type: string; text: string; language: string }) => void) => {
        onEvent?.({ type: "partial_segment", text: "流式中", language: "yue" });
        return new Promise((resolve) => {
          resolveStream = resolve;
        });
      },
    );

    render(<App transcribeAudioStream={mockStream} />);

    const input = screen.getAllByLabelText(/上传音频文件/i).find((element) => element.tagName === "INPUT") as HTMLInputElement;
    const file = new File(["audio"], "sample.webm", { type: "audio/webm" });
    fireEvent.change(input, { target: { files: [file] } });

    expect((await screen.findAllByText("流式中")).length).toBeGreaterThan(0);

    resolveStream({
      requested_language: "auto",
      detected_language: "yue",
      language_probability: 0.97,
      text: "最终结果",
      segments: [{ start: 0, end: 1.2, text: "最终结果" }],
    });

    expect((await screen.findAllByText("最终结果")).length).toBeGreaterThan(0);
  });

  it("renders multiple successful transcriptions as history items", async () => {
    const mockTranscribe = vi
      .fn()
      .mockResolvedValueOnce({
        requested_language: "yue",
        detected_language: "yue",
        language_probability: 0.98,
        text: "第一条",
        segments: [{ start: 0, end: 1.2, text: "第一条" }],
        timing: { convert_ms: 100, vad_ms: 20, decode_ms: 300 },
      })
      .mockResolvedValueOnce({
        requested_language: "my",
        detected_language: "my",
        language_probability: 0.95,
        text: "第二条",
        segments: [{ start: 0, end: 1.5, text: "第二条" }],
        timing: { convert_ms: 110, vad_ms: 0, decode_ms: 420 },
      })
      .mockResolvedValueOnce({
        requested_language: "auto",
        detected_language: "auto",
        language_probability: 0.99,
        text: "第三条",
        segments: [{ start: 0, end: 1.8, text: "第三条" }],
        timing: { convert_ms: 130, vad_ms: 35, decode_ms: 510 },
      });

    const createRecorderSession = vi
      .fn()
      .mockImplementation(() => Promise.resolve(createSession()));

    render(
      <App transcribeAudio={mockTranscribe} createRecorderSession={createRecorderSession} />,
    );

    const trigger = screen.getByRole("button", { name: /按住说话/i });

    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("松开发送，上滑取消");
    fireEvent.pointerUp(trigger);
    await waitFor(() => expect(mockTranscribe).toHaveBeenCalledTimes(1));
    await screen.findAllByText("第一条");

    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("松开发送，上滑取消");
    fireEvent.pointerUp(trigger);
    await waitFor(() => expect(mockTranscribe).toHaveBeenCalledTimes(2));

    await screen.findAllByText("第二条");

    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("松开发送，上滑取消");
    fireEvent.pointerUp(trigger);
    await waitFor(() => expect(mockTranscribe).toHaveBeenCalledTimes(3));
    await screen.findAllByText("第三条");

    const resultSection = screen.getByText("Latest Result").closest("section");
    expect(resultSection).toBeTruthy();
    if (!resultSection) {
      throw new Error("Latest Result section not found");
    }
    expect(within(resultSection).getAllByText("第三条").length).toBeGreaterThan(0);
    expect(within(resultSection).getByText(/识别语言 auto/i)).toBeTruthy();

    const historyHeader = await screen.findByText("History");
    const historySection = historyHeader.closest(".history-section");
    expect(historySection).toBeTruthy();
    const historyItems = historySection?.querySelectorAll(".history-item") ?? [];
    expect(historyItems.length).toBe(2);
    expect(historyItems[0]).toHaveTextContent("第二条");
    expect(historyItems[1]).toHaveTextContent("第一条");
    expect(historyItems[0]).toHaveTextContent("转码 110 ms");
    expect(historyItems[0]).toHaveTextContent("VAD 0 ms");
    expect(historyItems[0]).toHaveTextContent("识别 420 ms");
    expect(historyItems[1]).toHaveTextContent("转码 100 ms");
  });

  it("renders an audio playback control for each history item", async () => {
    const mockTranscribe = vi
      .fn()
      .mockResolvedValueOnce({
        requested_language: "yue",
        detected_language: "yue",
        language_probability: 0.98,
        text: "第一条",
        segments: [{ start: 0, end: 1.2, text: "第一条" }],
      })
      .mockResolvedValueOnce({
        requested_language: "my",
        detected_language: "my",
        language_probability: 0.95,
        text: "第二条",
        segments: [{ start: 0, end: 1.5, text: "第二条" }],
      })
      .mockResolvedValueOnce({
        requested_language: "auto",
        detected_language: "auto",
        language_probability: 0.99,
        text: "第三条",
        segments: [{ start: 0, end: 1.8, text: "第三条" }],
      });

    const createRecorderSession = vi
      .fn()
      .mockImplementation(() => Promise.resolve(createSession()));

    render(
      <App transcribeAudio={mockTranscribe} createRecorderSession={createRecorderSession} />,
    );

    const trigger = screen.getByRole("button", { name: /按住说话/i });
    for (let i = 0; i < 3; i += 1) {
      fireEvent.pointerDown(trigger, { clientY: 0 });
      await screen.findByText("松开发送，上滑取消");
      fireEvent.pointerUp(trigger);
      await waitFor(() => expect(mockTranscribe).toHaveBeenCalledTimes(i + 1));
    }

    await screen.findAllByText("第三条");
    expect(document.querySelectorAll("audio")).toHaveLength(3);
  });

  it("does not start recording when the session resolves after release", async () => {
    let resolveSession: (session: RecorderSession) => void = () => {
      /* placeholder */
    };
    const createRecorderSession = vi.fn().mockImplementation(
      () =>
        new Promise<RecorderSession>((resolve) => {
          resolveSession = resolve;
        }),
    );
    const mockTranscribe = vi.fn();

    render(<App createRecorderSession={createRecorderSession} transcribeAudio={mockTranscribe} />);

    const trigger = screen.getByRole("button", { name: /按住说话/i });
    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("正在请求麦克风权限");
    fireEvent.pointerUp(trigger);

    expect(screen.getByText(/按住下方输入区开始说话/i)).toBeInTheDocument();

    const session = createSession();
    resolveSession(session);
    await waitFor(() => expect(session.cancel).toHaveBeenCalledTimes(1));

    expect(screen.getByText(/按住下方输入区开始说话/i)).toBeInTheDocument();
    expect(mockTranscribe).not.toHaveBeenCalled();
  });

  it("cancels upload when slide-up gesture ends before upload", async () => {
    const session = createSession();
    let resolveSession: (session: RecorderSession) => void = () => {
      /* placeholder */
    };
    const createRecorderSession = vi.fn().mockImplementation(
      () =>
        new Promise<RecorderSession>((resolve) => {
          resolveSession = resolve;
        }),
    );
    const mockTranscribe = vi.fn();

    render(<App createRecorderSession={createRecorderSession} transcribeAudio={mockTranscribe} />);

    const trigger = screen.getByRole("button", { name: /按住说话/i });
    fireEvent.pointerDown(trigger, { clientY: 200 });
    fireEvent.pointerMove(trigger, { clientY: 50 });
    fireEvent.pointerUp(trigger);

    resolveSession(session);
    await waitFor(() => expect(session.cancel).toHaveBeenCalledTimes(1));

    expect(mockTranscribe).not.toHaveBeenCalled();
    expect(screen.getByText(/按住下方输入区开始说话/i)).toBeInTheDocument();
  });

  it("cancels upload when the user slides up and releases quickly", async () => {
    expect(didCrossCancelThreshold(200, { clientY: 50 })).toBe(true);
    expect(didCrossCancelThreshold(200, { pageY: 120 })).toBe(false);
    expect(didCrossCancelThreshold(null, { clientY: 50 })).toBe(false);
  });

  it("revokes generated object urls when the app unmounts", async () => {
    const createdUrl = "blob://generated";
    const createObjectURL = vi.spyOn(URL, "createObjectURL").mockReturnValue(createdUrl);
    const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL");

    const mockTranscribe = vi.fn().mockResolvedValue({
      requested_language: "auto",
      detected_language: "auto",
      language_probability: 0.9,
      text: "clean up",
      segments: [{ start: 0, end: 1, text: "clean up" }],
    });

    const createRecorderSession = vi.fn().mockResolvedValue(createSession());

    const { unmount } = render(
      <App transcribeAudio={mockTranscribe} createRecorderSession={createRecorderSession} />,
    );

    const trigger = screen.getByRole("button", { name: /按住说话/i });
    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("松开发送，上滑取消");
    fireEvent.pointerUp(trigger);

    await waitFor(() => expect(mockTranscribe).toHaveBeenCalledTimes(1));
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith(createdUrl);

    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
  });

  it("ignores a stale session that resolves after a newer press has started", async () => {
    let resolveFirstSession: (session: RecorderSession) => void = () => {
      /* placeholder */
    };
    const secondSession = createSession();
    const createRecorderSession = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<RecorderSession>((resolve) => {
            resolveFirstSession = resolve;
          }),
      )
      .mockResolvedValueOnce(secondSession);
    const mockTranscribe = vi.fn();

    render(<App createRecorderSession={createRecorderSession} transcribeAudio={mockTranscribe} />);

    const trigger = screen.getByRole("button", { name: /按住说话/i });

    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("正在请求麦克风权限");
    fireEvent.pointerUp(trigger);

    fireEvent.pointerDown(trigger, { clientY: 0 });
    await screen.findByText("松开发送，上滑取消");

    const staleSession = createSession();
    resolveFirstSession(staleSession);
    await waitFor(() => expect(staleSession.cancel).toHaveBeenCalledTimes(1));

    fireEvent.pointerUp(trigger);
    await waitFor(() => expect(secondSession.stop).toHaveBeenCalledTimes(1));
    expect(mockTranscribe).toHaveBeenCalledTimes(1);
  });
});
