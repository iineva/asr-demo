import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";
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

    const input = screen.getByLabelText(/上传音频文件/i) as HTMLInputElement;
    const file = new File(["audio"], "sample.webm", { type: "audio/webm" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockTranscribe).toHaveBeenCalledWith(file, "auto"));
    expect(await screen.findByText(/识别语言 my/i)).toBeInTheDocument();
    expect((await screen.findAllByText("မင်္ဂလာပါ")).length).toBeGreaterThan(0);
  });
});
