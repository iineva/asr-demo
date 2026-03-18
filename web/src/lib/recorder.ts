export type RecorderSession = {
  stop: () => Promise<Blob>;
  cancel: () => Promise<void>;
  mimeType?: string;
  onChunk?: (listener: (chunk: Blob) => void) => () => void;
};

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const candidate of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }
  return "";
}

export async function createRecorderSession(): Promise<RecorderSession> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    throw new Error("当前浏览器不支持录音");
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const chunks: BlobPart[] = [];
  const chunkListeners = new Set<(chunk: Blob) => void>();
  const mimeType = pickMimeType();
  const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

  recorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      chunks.push(event.data);
      chunkListeners.forEach((listener) => listener(event.data));
    }
  });

  recorder.start(300);

  const stopTracks = () => {
    stream.getTracks().forEach((track) => track.stop());
  };

  return {
    mimeType: mimeType || "audio/webm",
    onChunk: (listener) => {
      chunkListeners.add(listener);
      return () => {
        chunkListeners.delete(listener);
      };
    },
    stop: () =>
      new Promise<Blob>((resolve, reject) => {
        recorder.addEventListener(
          "stop",
          () => {
            stopTracks();
            resolve(new Blob(chunks, { type: mimeType || "audio/webm" }));
          },
          { once: true },
        );
        recorder.addEventListener(
          "error",
          () => {
            stopTracks();
            reject(new Error("录音失败"));
          },
          { once: true },
        );
        recorder.stop();
      }),
    cancel: async () => {
      if (recorder.state !== "inactive") {
        recorder.stop();
      }
      stopTracks();
    },
  };
}
