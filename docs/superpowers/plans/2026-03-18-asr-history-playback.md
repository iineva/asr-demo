# ASR History Playback UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the frontend so the record control becomes a smaller floating bottom dock, and successful transcriptions are appended to an in-memory history list where each item can replay its original audio.

**Architecture:** Keep the change frontend-only. Refactor the current single-result screen into a history-driven page model inside `web/src/App.tsx`, with a small typed history record in `web/src/types.ts` and browser-generated object URLs for audio replay. Preserve the existing record, release, cancel, and upload flow while moving the controls into a bottom floating action area and rendering successful results as cards in a newest-first list.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, browser `Blob` and `URL.createObjectURL`

---

## Chunk 1: History Data Model and Playback Contracts

### File Map

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/App.tsx`

### Task 1: Add typed history item support

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
it("renders multiple successful transcriptions as history items", async () => {
  ...
  expect(await screen.findByText("第一条")).toBeInTheDocument()
  expect(await screen.findByText("第二条")).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL because the app only stores and renders one `result`

- [ ] **Step 3: Write minimal implementation scaffolding**

```ts
export type TranscriptHistoryItem = {
  id: string
  createdAt: string
  sourceType: "recorded" | "uploaded"
  audioName: string
  audioBlob: Blob
  audioUrl: string
  result: TranscriptResult
}
```

- [ ] **Step 4: Run test to verify it still fails for the right reason**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL in `App.tsx` rendering or state usage, not type-definition errors

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/App.test.tsx
git commit -m "test: add history item contracts for playback UI"
```

### Task 2: Append successful results to history instead of replacing output

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/types.ts`

- [ ] **Step 1: Write the failing test**

```ts
it("keeps earlier successful results when a later transcription succeeds", async () => {
  ...
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL because later success overwrites prior `result`

- [ ] **Step 3: Write minimal implementation**

```ts
const [historyItems, setHistoryItems] = useState<TranscriptHistoryItem[]>([])
```

Update success handling so each finished upload or recording inserts a new history item at the top of the list instead of replacing a single `result`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx web/src/types.ts
git commit -m "feat: append transcription results to in-memory history"
```

## Chunk 2: Original Audio Playback and Resource Cleanup

### Task 3: Attach replayable audio to each history item

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
it("renders an audio playback control for each history item", async () => {
  ...
  expect(screen.getAllByRole("audio")).toHaveLength(2)
})
```

If role-based selection is awkward in jsdom, assert on `document.querySelectorAll("audio")`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL because no audio element is rendered for successful results

- [ ] **Step 3: Write minimal implementation**

```ts
const audioUrl = URL.createObjectURL(sourceBlob)
```

Store the generated object URL on each history item and render a native `<audio controls>` inside each history card.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx
git commit -m "feat: add original audio playback to history items"
```

### Task 4: Revoke generated object URLs on cleanup

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
it("revokes generated object urls when the app unmounts", async () => {
  ...
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(createdUrl)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL because object URLs are created but never revoked

- [ ] **Step 3: Write minimal implementation**

```ts
useEffect(() => {
  return () => {
    historyItems.forEach((item) => URL.revokeObjectURL(item.audioUrl))
  }
}, [historyItems])
```

Use a ref or cleanup-safe pattern if needed to avoid double-revoking stale values.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx
git commit -m "fix: clean up audio object urls for history playback"
```

## Chunk 3: Floating Dock Layout and Interaction Preservation

### Task 5: Move the recorder and upload actions into a floating bottom dock

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/App.test.tsx`

- [ ] **Step 1: Write the failing test**

```ts
it("keeps the record trigger available while rendering history above a bottom dock", async () => {
  ...
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL because the current layout still centers the large record panel in the page body

- [ ] **Step 3: Write minimal implementation**

Update the JSX structure so:
- the history list occupies the main content area
- the record button and upload button are rendered inside a bottom floating dock
- the record button is visually smaller than the current hero-style button
- the content area has bottom padding so cards are not hidden behind the dock

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/styles.css web/src/App.test.tsx
git commit -m "feat: move recording controls into floating bottom dock"
```

### Task 6: Preserve existing record, release, cancel, and upload behavior

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`

- [ ] **Step 1: Add or update failing tests**

Cover:
- press and hold still enters recording state
- release still uploads and creates a history item
- pointer cancel still avoids upload
- file upload still creates a history item

- [ ] **Step 2: Run test to verify failures**

Run: `npm test -- web/src/App.test.tsx`
Expected: FAIL if the dock refactor broke existing behavior

- [ ] **Step 3: Write minimal implementation fixes**

Adjust event handlers and render structure so the floating dock does not change the recording contract.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- web/src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx
git commit -m "test: preserve recording and upload behavior in floating dock"
```

## Chunk 4: Final Verification

### Task 7: Run frontend verification

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/types.ts`

- [ ] **Step 1: Run frontend tests**

Run: `npm test`
Expected: PASS

- [ ] **Step 2: Run frontend build verification**

Run: `npm run build`
Expected: PASS

- [ ] **Step 3: Manual UI check**

Verify in the browser that:
- the dock is fixed at the bottom
- the talk button is visibly smaller
- multiple successful results stack as history
- each history item can replay the original audio
- refreshing the page clears the in-memory history

- [ ] **Step 4: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx web/src/styles.css web/src/types.ts
git commit -m "test: verify history playback ui"
```
