import { useEffect, useRef, useState } from "react";
import { transcribeAudio as defaultTranscribeAudio } from "./lib/api";
import {
  createRecorderSession as defaultCreateRecorderSession,
  type RecorderSession,
} from "./lib/recorder";
import type { TranscriptResult } from "./types";

type Props = {
  transcribeAudio?: (blob: Blob, language: string) => Promise<TranscriptResult>;
  createRecorderSession?: () => Promise<RecorderSession>;
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

function formatProbability(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export default function App({
  transcribeAudio = defaultTranscribeAudio,
  createRecorderSession = defaultCreateRecorderSession,
}: Props) {
  const [language, setLanguage] = useState<"auto" | "my" | "yue">("auto");
  const [status, setStatus] = useState<InteractionState>("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState<TranscriptResult | null>(null);
  const [durationMs, setDurationMs] = useState(0);

  const startYRef = useRef<number | null>(null);
  const sessionRef = useRef<RecorderSession | null>(null);
  const timerRef = useRef<number | null>(null);
  const startedAtRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
      }
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

  const handlePointerDown = async (event: React.PointerEvent<HTMLButtonElement>) => {
    if (status === "requesting" || status === "uploading") {
      return;
    }

    if ("setPointerCapture" in event.currentTarget) {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    setError("");
    setStatus("requesting");
    startYRef.current = event.clientY;

    try {
      const session = await createRecorderSession();
      sessionRef.current = session;
      startedAtRef.current = Date.now();
      setStatus("recording");
      timerRef.current = window.setInterval(() => {
        if (startedAtRef.current) {
          setDurationMs(Date.now() - startedAtRef.current);
        }
      }, 100);
    } catch (sessionError) {
      resetGesture();
      setStatus("error");
      setError(sessionError instanceof Error ? sessionError.message : "无法启动录音");
    }
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!sessionRef.current || startYRef.current === null) {
      return;
    }

    const currentY =
      [event.clientY, event.pageY, event.screenY].find((value) => typeof value === "number" && !Number.isNaN(value)) ??
      startYRef.current;
    const offset = startYRef.current - currentY;
    setStatus(offset > CANCEL_THRESHOLD ? "cancel" : "recording");
  };

  const finishRecording = async (shouldCancel = false) => {
    const session = sessionRef.current;
    sessionRef.current = null;
    resetGesture();
    if (!session) {
      setStatus("idle");
      return;
    }

    if (shouldCancel || status === "cancel") {
      await session.cancel();
      setStatus("idle");
      return;
    }

    try {
      setStatus("uploading");
      const blob = await session.stop();
      const nextResult = await transcribeAudio(blob, language);
      setResult(nextResult);
      setStatus("success");
    } catch (uploadError) {
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
    setStatus("cancel");
    await finishRecording(true);
  };

  return (
    <main className="page-shell">
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

      <section className={`record-panel state-${status}`}>
        <div className="status-orb" />
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
            <span className="record-button-subtitle">Hold to record</span>
          </span>
        </button>

        {error ? <p className="inline-error">{error}</p> : null}
      </section>

      <section className="result-card">
        <div className="section-header">
          <div>
            <p className="eyebrow">Latest Result</p>
            <h2>识别结果</h2>
          </div>
          {result ? <span className="badge">识别语言 {result.detected_language ?? "unknown"}</span> : null}
        </div>

        {result ? (
          <>
            <div className="result-metrics">
              <div className="metric">
                <span>请求语言</span>
                <strong>{result.requested_language}</strong>
              </div>
              <div className="metric">
                <span>概率</span>
                <strong>{formatProbability(result.language_probability)}</strong>
              </div>
            </div>

            <article className="transcript-card">
              <p>{result.text}</p>
            </article>

            <div className="segment-list">
              {result.segments.map((segment, index) => (
                <article key={`${segment.start}-${segment.end}-${index}`} className="segment-item">
                  <span className="segment-time">
                    {segment.start.toFixed(1)}s - {segment.end.toFixed(1)}s
                  </span>
                  <p>{segment.text}</p>
                </article>
              ))}
            </div>
          </>
        ) : (
          <div className="empty-state">
            <p>还没有识别结果。</p>
            <p>按住说话后松开，结果会自动显示在这里。</p>
          </div>
        )}
      </section>
    </main>
  );
}
