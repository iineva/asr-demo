import { useEffect, useRef, useState } from "react";
import { transcribeAudio as defaultTranscribeAudio, transcribeAudioStream as defaultTranscribeAudioStream } from "./lib/api";
import {
  createRecorderSession as defaultCreateRecorderSession,
  type RecorderSession,
} from "./lib/recorder";
import type { TranscriptHistoryItem, TranscriptResult, TranscriptSegment, TranscriptStreamEvent } from "./types";

type Props = {
  transcribeAudio?: (blob: Blob, language: string) => Promise<TranscriptResult>;
  transcribeAudioStream?: (
    blob: Blob,
    language: string,
    onEvent?: (event: TranscriptStreamEvent) => void,
  ) => Promise<TranscriptResult>;
  createRecorderSession?: () => Promise<RecorderSession>;
  createRealtimeSocket?: () => WebSocket;
};

type InteractionState =
  | "idle"
  | "requesting"
  | "recording"
  | "cancel"
  | "uploading"
  | "success"
  | "error";

const CANCEL_THRESHOLD = 120;
const REALTIME_COMPLETION_TIMEOUT_MS = 45000;

function formatProbability(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function createDefaultRealtimeSocket(): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${protocol}://${window.location.host}/api/ws/transcribe`);
}

function createHistoryItem(
  result: TranscriptResult,
  sourceType: TranscriptHistoryItem["sourceType"],
  source: Blob | File,
  registerObjectUrl?: (url: string) => void,
): TranscriptHistoryItem {
  const isFileAvailable = typeof File !== "undefined" && source instanceof File;
  const audioName = isFileAvailable ? source.name : sourceType === "uploaded" ? "上传音频" : "录音";
  const audioUrl = URL.createObjectURL(source);

  registerObjectUrl?.(audioUrl);

  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    sourceType,
    audioName,
    audioBlob: source,
    audioUrl,
    result,
  };
}

export default function App({
  transcribeAudio = defaultTranscribeAudio,
  transcribeAudioStream = defaultTranscribeAudioStream,
  createRecorderSession = defaultCreateRecorderSession,
  createRealtimeSocket = createDefaultRealtimeSocket,
}: Props) {
  const [language, setLanguage] = useState<"auto" | "my" | "yue">("auto");
  const [status, setStatus] = useState<InteractionState>("idle");
  const [error, setError] = useState("");
  const [historyItems, setHistoryItems] = useState<TranscriptHistoryItem[]>([]);
  const [liveResult, setLiveResult] = useState<TranscriptResult | null>(null);
  const [durationMs, setDurationMs] = useState(0);

  const startYRef = useRef<number | null>(null);
  const sessionRef = useRef<RecorderSession | null>(null);
  const timerRef = useRef<number | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const isPointerDownRef = useRef(false);
  const sessionRequestIdRef = useRef<number | null>(null);
  const cancelSlashRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const objectUrlRegistryRef = useRef<Set<string>>(new Set());
  const realtimeSocketRef = useRef<WebSocket | null>(null);
  const realtimeUnsubscribeRef = useRef<(() => void) | null>(null);
  const realtimeCompletionRef = useRef<{
    promise: Promise<TranscriptResult>;
    resolve: (result: TranscriptResult) => void;
    reject: (error: Error) => void;
  } | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
      }
      objectUrlRegistryRef.current.forEach((url) => {
        URL.revokeObjectURL(url);
      });
      objectUrlRegistryRef.current.clear();
      realtimeUnsubscribeRef.current?.();
      realtimeSocketRef.current?.close();
    };
  }, []);

  const stopTimer = () => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const resetGesture = () => {
    startYRef.current = null;
    stopTimer();
    startedAtRef.current = null;
    setDurationMs(0);
  };

  const registerObjectUrl = (url: string) => {
    objectUrlRegistryRef.current.add(url);
  };

  const buildLiveResultFromEvent = (event: TranscriptStreamEvent) => {
    setLiveResult((previous) => {
      const previousSegments = previous?.segments ?? [];
      const nextSegments: TranscriptSegment[] = [...previousSegments];

      if (event.type === "final_segment") {
        nextSegments.push({
          start: 0,
          end: 0,
          text: event.text,
        });
      }

      if (event.type === "partial_segment") {
        const finalizedSegments = nextSegments.filter((segment) => !segment.text.startsWith("__partial__:"));
        finalizedSegments.push({
          start: 0,
          end: 0,
          text: `__partial__:${event.text}`,
        });
        return {
          requested_language: previous?.requested_language ?? language,
          detected_language: event.language,
          language_probability: previous?.language_probability ?? 0,
          text: [...finalizedSegments.map((segment) => segment.text.replace(/^__partial__:/, ""))].join(" ").trim(),
          segments: finalizedSegments,
        };
      }

      if (event.type === "completed") {
        return {
          requested_language: (event.detail?.requested_language ?? language) as TranscriptResult["requested_language"],
          detected_language: event.language,
          language_probability: event.detail?.language_probability ?? 0,
          text: event.text,
          segments: event.detail?.segments ?? nextSegments,
        };
      }

      return previous;
    });
  };

  const buildCompletedResult = (event: TranscriptStreamEvent): TranscriptResult => ({
    requested_language: (event.detail?.requested_language ?? language) as TranscriptResult["requested_language"],
    detected_language: event.language,
    language_probability: event.detail?.language_probability ?? 0,
    text: event.text,
    segments: event.detail?.segments ?? [],
  });

  const resetRealtimeSession = () => {
    realtimeUnsubscribeRef.current?.();
    realtimeUnsubscribeRef.current = null;
    realtimeSocketRef.current?.close();
    realtimeSocketRef.current = null;
    realtimeCompletionRef.current = null;
  };

  const runTranscription = async (
    source: Blob | File,
    uploadErrorMessage: string,
    sourceType: TranscriptHistoryItem["sourceType"],
  ) => {
    try {
      setError("");
      setStatus("uploading");
      setLiveResult(null);
      const shouldUseLegacyTranscribe =
        transcribeAudio !== defaultTranscribeAudio && transcribeAudioStream === defaultTranscribeAudioStream;
      const nextResult = shouldUseLegacyTranscribe
        ? await transcribeAudio(source, language)
        : await transcribeAudioStream(source, language, buildLiveResultFromEvent);
      setHistoryItems((previous) => [
        createHistoryItem(nextResult, sourceType, source, registerObjectUrl),
        ...previous,
      ]);
      setLiveResult(null);
      setStatus("success");
    } catch (uploadError) {
      setLiveResult(null);
      setStatus("error");
      setError(uploadError instanceof Error ? uploadError.message : uploadErrorMessage);
    }
  };

  const handlePointerDown = async (event: React.PointerEvent<HTMLButtonElement>) => {
    if (status === "requesting" || status === "uploading") {
      return;
    }

    event.preventDefault();
    if ("setPointerCapture" in event.currentTarget) {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    setError("");
    setStatus("requesting");
    startYRef.current = event.clientY;
    cancelSlashRef.current = false;
    isPointerDownRef.current = true;
    const requestId = (sessionRequestIdRef.current ?? 0) + 1;
    sessionRequestIdRef.current = requestId;

    try {
      const session = await createRecorderSession();
      if (!isPointerDownRef.current || sessionRequestIdRef.current !== requestId) {
        await session.cancel();
        return;
      }
      sessionRef.current = session;
      setLiveResult(null);

      if (session.onChunk) {
        const socket = createRealtimeSocket();
        realtimeSocketRef.current = socket;
        let isSettled = false;
        const pendingChunks: Blob[] = [];
        let resolveCompletion: (result: TranscriptResult) => void = () => {
          /* placeholder */
        };
        let rejectCompletion: (error: Error) => void = () => {
          /* placeholder */
        };
        const completionPromise = new Promise<TranscriptResult>((resolve, reject) => {
          resolveCompletion = resolve;
          rejectCompletion = reject;
        });
        const completionTimeoutId = window.setTimeout(() => {
          if (!isSettled) {
            realtimeCompletionRef.current?.reject(new Error("录音流式识别超时，请重试"));
          }
        }, REALTIME_COMPLETION_TIMEOUT_MS);
        realtimeCompletionRef.current = {
          promise: completionPromise,
          resolve: (result) => {
            isSettled = true;
            window.clearTimeout(completionTimeoutId);
            realtimeCompletionRef.current = null;
            realtimeSocketRef.current = null;
            resolveCompletion(result);
          },
          reject: (error) => {
            isSettled = true;
            window.clearTimeout(completionTimeoutId);
            realtimeCompletionRef.current = null;
            realtimeSocketRef.current = null;
            rejectCompletion(error);
          },
        };

        const sendChunk = async (chunk: Blob) => {
          const targetSocket = realtimeSocketRef.current;
          if (!targetSocket || targetSocket.readyState !== WebSocket.OPEN) {
            pendingChunks.push(chunk);
            return;
          }
          targetSocket.send(await chunk.arrayBuffer());
        };

        realtimeUnsubscribeRef.current = session.onChunk((chunk) => {
          void sendChunk(chunk);
        });

        socket.addEventListener("open", () => {
          socket.send(JSON.stringify({ type: "start", language, mime_type: session.mimeType ?? "audio/webm" }));
          pendingChunks.splice(0).forEach((chunk) => {
            void sendChunk(chunk);
          });
        });

        socket.addEventListener("message", (messageEvent) => {
          if (typeof messageEvent.data !== "string") {
            return;
          }
          let payload: TranscriptStreamEvent;
          try {
            payload = JSON.parse(messageEvent.data) as TranscriptStreamEvent;
          } catch {
            realtimeCompletionRef.current?.reject(new Error("录音流式识别响应格式错误"));
            return;
          }
          if (payload.type === "error") {
            realtimeCompletionRef.current?.reject(new Error(payload.detail?.message ?? "录音流式识别失败"));
            return;
          }
          buildLiveResultFromEvent(payload);
          if (payload.type === "completed") {
            realtimeCompletionRef.current?.resolve(buildCompletedResult(payload));
          }
        });

        socket.addEventListener("error", () => {
          if (!isSettled) {
            realtimeCompletionRef.current?.reject(new Error("录音流式识别失败"));
          }
        });

        socket.addEventListener("close", () => {
          if (!isSettled) {
            realtimeCompletionRef.current?.reject(new Error("录音流式连接已断开，请重试"));
          }
        });
      }

      startedAtRef.current = Date.now();
      setStatus("recording");
      timerRef.current = window.setInterval(() => {
        if (startedAtRef.current) {
          setDurationMs(Date.now() - startedAtRef.current);
        }
      }, 100);
    } catch (sessionError) {
      if (sessionRequestIdRef.current !== requestId) {
        return;
      }
      resetGesture();
      setStatus("error");
      setError(sessionError instanceof Error ? sessionError.message : "无法启动录音");
    }
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (startYRef.current === null) {
      return;
    }

    const currentY =
      [event.clientY, event.pageY, event.screenY].find((value) => typeof value === "number" && !Number.isNaN(value)) ??
      startYRef.current;
    const offset = startYRef.current - currentY;
    const willCancel = offset > CANCEL_THRESHOLD;
    cancelSlashRef.current = willCancel;
    setStatus(willCancel ? "cancel" : "recording");
  };

  const finishRecording = async (shouldCancel = false) => {
    const session = sessionRef.current;
    const cancelled = shouldCancel || cancelSlashRef.current || status === "cancel";
    sessionRef.current = null;
    isPointerDownRef.current = false;
    cancelSlashRef.current = false;
    resetGesture();
    if (!session) {
      setStatus("idle");
      return;
    }

    if (cancelled) {
      await session.cancel();
      resetRealtimeSession();
      setLiveResult(null);
      setStatus("idle");
      return;
    }

    try {
      const blob = await session.stop();
      if (realtimeSocketRef.current && realtimeCompletionRef.current) {
        if (realtimeSocketRef.current.readyState === WebSocket.OPEN) {
          realtimeSocketRef.current.send(JSON.stringify({ type: "finish" }));
          const nextResult = await realtimeCompletionRef.current.promise;
          setHistoryItems((previous) => [
            createHistoryItem(nextResult, "recorded", blob, registerObjectUrl),
            ...previous,
          ]);
          setLiveResult(null);
          resetRealtimeSession();
          setStatus("success");
          return;
        }
        resetRealtimeSession();
      }
      await runTranscription(blob, "录音上传失败", "recorded");
    } catch (uploadError) {
      resetRealtimeSession();
      setStatus("error");
      setError(uploadError instanceof Error ? uploadError.message : "录音上传失败");
    }
  };

  const handlePointerUp = async (event: React.PointerEvent<HTMLButtonElement>) => {
    if ("hasPointerCapture" in event.currentTarget && event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    await finishRecording(status === "cancel");
  };

  const handlePointerCancel = async () => {
    cancelSlashRef.current = true;
    setStatus("cancel");
    await finishRecording(true);
  };

  const handleUploadButtonClick = () => {
    if (status === "requesting" || status === "recording" || status === "cancel" || status === "uploading") {
      return;
    }
    fileInputRef.current?.click();
  };

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    await runTranscription(file, "文件上传失败", "uploaded");
    event.target.value = "";
  };

  const latestHistoryItem = historyItems[0];
  const latestResult = liveResult ?? latestHistoryItem?.result ?? null;
  const previousHistoryItems = historyItems.slice(1);

  return (
    <>
      <main className="page-shell" data-testid="page-shell">
        <section className="hero-card">
          <p className="eyebrow">Voice Bridge</p>
          <h1>按住说话，松开发送</h1>
          <p className="hero-copy">
            面向手机测试的实时语音输入页，支持缅甸语、粤语和自动识别。
          </p>

          <label className="language-field">
            <span>识别语言</span>
            <select value={language} onChange={(event) => setLanguage(event.target.value as "auto" | "my" | "yue")}>
              <option value="auto">自动识别</option>
              <option value="my">缅甸语</option>
              <option value="yue">粤语</option>
            </select>
          </label>
        </section>

        <section className="result-card">
          <div className="section-header">
            <div>
              <p className="eyebrow">Latest Result</p>
              <h2>识别结果</h2>
            </div>
            {latestResult ? (
              <span className="badge">识别语言 {latestResult.detected_language ?? "unknown"}</span>
            ) : null}
          </div>

          {latestResult ? (
            <>
              <div className="result-metrics">
                <div className="metric">
                  <span>请求语言</span>
                  <strong>{latestResult.requested_language}</strong>
                </div>
                <div className="metric">
                  <span>概率</span>
                  <strong>{formatProbability(latestResult.language_probability)}</strong>
                </div>
              </div>

              <article className="transcript-card">
                <p>{latestResult.text}</p>
              </article>

              {!liveResult && latestHistoryItem ? <audio controls src={latestHistoryItem.audioUrl} /> : null}

              <div className="segment-list">
                {latestResult.segments.map((segment, index) => (
                  <article key={`${segment.start}-${segment.end}-${index}`} className="segment-item">
                    <span className="segment-time">
                      {segment.start.toFixed(1)}s - {segment.end.toFixed(1)}s
                    </span>
                    <p>{segment.text.replace(/^__partial__:/, "")}</p>
                  </article>
                ))}
              </div>
              {previousHistoryItems.length > 0 && (
                <div className="history-section" data-testid="history-section">
                  <div className="history-section-header">
                    <p className="eyebrow">History</p>
                    <p className="history-description">过往识别记录</p>
                  </div>
                  <div className="history-list">
                    {previousHistoryItems.map((item) => (
                      <article key={item.id} className="history-item">
                        <span className="history-stamp">
                          {new Date(item.createdAt).toLocaleTimeString()}
                        </span>
                        <p>{item.result.text}</p>
                        <audio controls src={item.audioUrl} />
                      </article>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <p>还没有识别结果。</p>
              <p>按住说话后松开，结果会自动显示在这里。</p>
            </div>
          )}
        </section>
      </main>

      <div className="record-dock" data-testid="record-dock" aria-label="录音操作">
        <section className={`record-panel state-${status}`}>
          <div className="record-panel-top">
            <div className="record-status">
              <div className="status-orb" />
              <div className="record-status-text">
                <p className="status-label">
                  {status === "recording" && "松开发送，上滑取消"}
                  {status === "cancel" && "松手取消发送"}
                  {status === "uploading" && "正在上传并识别"}
                  {status === "requesting" && "正在请求麦克风权限"}
                  {(status === "idle" || status === "success" || status === "error") && "按住下方输入区开始说话"}
                </p>
                <p className="duration-label">
                  {status === "recording" || status === "cancel" ? formatDuration(durationMs) : "准备就绪"}
                </p>
              </div>
            </div>

            <button
              type="button"
              className="upload-button"
              onClick={handleUploadButtonClick}
              aria-label="上传音频文件"
              title="上传音频文件"
              disabled={
                status === "requesting" || status === "recording" || status === "cancel" || status === "uploading"
              }
            >
              文件
            </button>
          </div>

          <button
            type="button"
            className="record-button"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerCancel}
            disabled={status === "requesting" || status === "uploading"}
          >
            <span className="record-button-inner">
              <span className="record-button-title">按住说话</span>
              <span className="record-button-subtitle">按住录音</span>
            </span>
          </button>

          <input
            ref={fileInputRef}
            id="audio-upload"
            className="file-input"
            type="file"
            aria-label="上传音频文件"
            accept=".m4a,.mp3,.wav,.webm,audio/*"
            onChange={handleFileChange}
          />

          {error ? <p className="inline-error">{error}</p> : null}
        </section>
      </div>
    </>
  );
}
