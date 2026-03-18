# ASR History Playback UI Design

**Goal:** Update the existing ASR web frontend so the press-to-talk control becomes a smaller WeChat-like floating input anchored at the bottom of the page, and successful transcription results are shown as a front-end-only history list where each item can replay its original audio.

**Architecture**

This change is entirely frontend-scoped. The backend contract stays the same. The React app stops treating transcription output as a single `result` object and instead maintains an in-memory `historyItems` list. Each successful recording or file upload appends a new item at the top of that list. Each history item stores the transcription payload plus a browser-local audio reference for playback during the current page session.

The page layout changes from a centered “current result” screen to a two-zone composition:

- a scrollable result history area in the main content
- a fixed floating action area pinned near the bottom safe area

The floating action area holds the smaller press-to-talk control and the file-upload trigger. The gesture model remains the same: press and hold to record, slide up to cancel, release to submit.

**UI Structure**

The main viewport becomes a message-like history stream. The latest successful transcription appears first. Each history card includes:

- a timestamp
- a source label such as recorded or uploaded
- detected/requested language metadata
- the transcribed text
- optional segment details
- an inline control to replay the original audio

The bottom action area is always visible and visually separate from the history stream. It should feel like a mobile chat input dock rather than a central hero button. The primary talk button is materially smaller than the current version and visually anchored to the bottom of the screen. The history list must reserve bottom padding so the floating dock never obscures the latest cards.

**State Model**

Replace the current single-result state with a history collection:

- `historyItems`: newest-first list of transcription records
- `status`: existing interaction state for recording/upload lifecycle
- `error`: transient UI error state
- `language`: current requested language

Each history item should contain:

- `id`
- `createdAt`
- `sourceType`
- `audioName`
- `audioBlob`
- `audioUrl`
- `result`

`audioBlob` and `audioUrl` are frontend-only runtime data. No persistence is required beyond the current page session. Refreshing the page clears the history.

**Audio Playback**

Each history card should render a native browser audio control instead of a custom playback state machine. This keeps the implementation small and robust while still giving the user direct replay of the original recording or uploaded file.

Audio URLs should be created with `URL.createObjectURL(...)` when a new history item is created. The app must release those URLs during cleanup to avoid leaking memory. This includes component unmount and any future history item removal behavior.

**Interaction Rules**

- A successful recording creates a new history item using the recorded blob and the returned transcription result.
- A successful file upload creates a new history item using the selected file blob and the returned transcription result.
- Errors do not create history items.
- Existing history items remain visible when later requests fail.
- The upload button remains available from the floating action area as a secondary action.
- The current press/hold, release-to-send, and slide-up-to-cancel behavior is preserved.

**Testing Strategy**

Frontend tests should cover:

- successful recording appends a new history item instead of replacing previous output
- successful file upload appends another history item
- each history item renders an audio playback control using the original audio source
- the floating bottom action area still supports record, release, and cancel behavior
- cleanup revokes generated object URLs when appropriate

No backend changes are required for this feature.
