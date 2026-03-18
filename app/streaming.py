import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional


def build_stream_event(
    *,
    event_type: str,
    sequence: int,
    session_id: str,
    text: str,
    start: float,
    end: float,
    is_final: bool,
    language: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "type": event_type,
        "sequence": sequence,
        "session_id": session_id,
        "text": text,
        "start": start,
        "end": end,
        "is_final": is_final,
        "language": language,
        "detail": detail,
    }


@dataclass
class SegmentReconciliationResult:
    final_segments: List[Dict[str, Any]]
    partial_segment: Optional[Dict[str, Any]]


def _build_partial_segment(partial_candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not partial_candidates:
        return None

    candidates_copy = [segment.copy() for segment in partial_candidates]
    text_parts = [segment.get("text") for segment in candidates_copy if segment.get("text") is not None]
    aggregated_text = "".join(text_parts)
    return {
        "text": aggregated_text,
        "start": candidates_copy[0].get("start"),
        "end": candidates_copy[-1].get("end"),
        "segments": candidates_copy,
    }


def reconcile_segments(
    previous_final: List[Dict[str, Any]], latest_segments: List[Dict[str, Any]]
) -> SegmentReconciliationResult:
    final_segments = [segment.copy() for segment in previous_final]
    mismatch_index: Optional[int] = None
    for i, previous in enumerate(previous_final):
        if i >= len(latest_segments):
            mismatch_index = i
            break
        if previous.get("text") != latest_segments[i].get("text"):
            mismatch_index = i
            break
    else:
        mismatch_index = None

    if mismatch_index is not None:
        partial_candidates = latest_segments[mismatch_index:]
        partial_segment = _build_partial_segment(partial_candidates)
        return SegmentReconciliationResult(final_segments=final_segments, partial_segment=partial_segment)

    remainder = latest_segments[len(previous_final) :]
    if not remainder:
        return SegmentReconciliationResult(final_segments=final_segments, partial_segment=None)

    if len(remainder) == 1:
        partial_segment = _build_partial_segment(remainder)
        return SegmentReconciliationResult(final_segments=final_segments, partial_segment=partial_segment)

    promoted_final = remainder[:-1]
    final_segments.extend(segment.copy() for segment in promoted_final)
    partial_segment = _build_partial_segment([remainder[-1]])
    return SegmentReconciliationResult(final_segments=final_segments, partial_segment=partial_segment)


def mime_type_to_extension(mime_type: Optional[str]) -> str:
    normalized = (mime_type or "").lower()
    if "mp4" in normalized or "m4a" in normalized:
        return ".m4a"
    if "mpeg" in normalized or "mp3" in normalized:
        return ".mp3"
    if "wav" in normalized or "wave" in normalized:
        return ".wav"
    return ".webm"


def encode_ndjson_event(event: Dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")


@dataclass
class StreamingTranscriptionSession:
    language: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    final_segments: List[Dict[str, Any]] = field(default_factory=list)
    sequence: int = 0
    latest_language: Optional[str] = None

    def _next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence

    def emit_progress(self, event_type: str, *, detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return build_stream_event(
            event_type=event_type,
            sequence=self._next_sequence(),
            session_id=self.session_id,
            text="",
            start=0.0,
            end=0.0,
            is_final=event_type == "completed",
            language=self.latest_language or self.language,
            detail=detail,
        )

    def apply_transcription_result(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        latest_segments = result.get("segments", [])
        reconciliation = reconcile_segments(self.final_segments, latest_segments)
        events: List[Dict[str, Any]] = []
        detected_language = result.get("detected_language") or self.language
        self.latest_language = detected_language

        new_final_segments = reconciliation.final_segments[len(self.final_segments) :]
        for segment in new_final_segments:
            events.append(
                build_stream_event(
                    event_type="final_segment",
                    sequence=self._next_sequence(),
                    session_id=self.session_id,
                    text=segment.get("text", ""),
                    start=float(segment.get("start", 0.0) or 0.0),
                    end=float(segment.get("end", 0.0) or 0.0),
                    is_final=True,
                    language=detected_language,
                )
            )

        self.final_segments = [segment.copy() for segment in reconciliation.final_segments]

        if reconciliation.partial_segment:
            partial = reconciliation.partial_segment
            events.append(
                build_stream_event(
                    event_type="partial_segment",
                    sequence=self._next_sequence(),
                    session_id=self.session_id,
                    text=partial.get("text", ""),
                    start=float(partial.get("start", 0.0) or 0.0),
                    end=float(partial.get("end", 0.0) or 0.0),
                    is_final=False,
                    language=detected_language,
                )
            )

        return events

    def emit_completed(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return build_stream_event(
            event_type="completed",
            sequence=self._next_sequence(),
            session_id=self.session_id,
            text=result.get("text", ""),
            start=0.0,
            end=float(result.get("segments", [{}])[-1].get("end", 0.0) if result.get("segments") else 0.0),
            is_final=True,
            language=result.get("detected_language") or self.latest_language or self.language,
            detail={
                "requested_language": result.get("requested_language", self.language),
                "segments": result.get("segments", []),
                "language_probability": result.get("language_probability"),
                "timing": result.get("timing"),
            },
        )

    def emit_error(self, detail: str) -> Dict[str, Any]:
        return build_stream_event(
            event_type="error",
            sequence=self._next_sequence(),
            session_id=self.session_id,
            text="",
            start=0.0,
            end=0.0,
            is_final=False,
            language=self.latest_language or self.language,
            detail={"message": detail},
        )


async def iter_file_upload_events(
    *,
    session: StreamingTranscriptionSession,
    transcribe_result: Callable[[], Awaitable[Dict[str, Any]]],
) -> AsyncIterator[bytes]:
    yield encode_ndjson_event(session.emit_progress("queued"))
    yield encode_ndjson_event(session.emit_progress("preprocessing"))
    result = await transcribe_result()
    for event in session.apply_transcription_result(result):
        yield encode_ndjson_event(event)
    yield encode_ndjson_event(session.emit_completed(result))


def write_bytes(path: Path, payload: bytearray) -> None:
    path.write_bytes(bytes(payload))


def append_bytes(path: Path, payload: bytes) -> None:
    with path.open("ab") as handle:
        handle.write(payload)
