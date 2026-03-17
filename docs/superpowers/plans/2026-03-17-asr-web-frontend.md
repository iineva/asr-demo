# ASR Web Frontend Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mobile-first Vite React TypeScript frontend with press-to-record, slide-up cancel, auto-upload on release, and result rendering for the ASR backend.

**Architecture:** Create a standalone `web/` app with a single page and small utility layer. Keep recording state in the top-level app component, isolate API calls and browser media helpers into focused modules, and style the page with intentional mobile-first CSS instead of a UI library.

**Tech Stack:** Vite, React, TypeScript, Vitest, Testing Library, Docker, docker compose

---

### File Map

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/styles.css`
- Create: `web/src/lib/api.ts`
- Create: `web/src/lib/recorder.ts`
- Create: `web/src/types.ts`
- Create: `web/src/App.test.tsx`
- Create: `web/Dockerfile`
- Create: `web/nginx.conf`

### Task 1: Recording Interaction Contract

**Files:**
- Create: `web/src/App.test.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/lib/recorder.ts`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run `npm test` and verify failure**
- [ ] **Step 3: Implement minimal press-and-hold recording state**
- [ ] **Step 4: Run `npm test` and verify pass**

### Task 2: Upload and Result Rendering

**Files:**
- Modify: `web/src/App.test.tsx`
- Create: `web/src/lib/api.ts`
- Create: `web/src/types.ts`

- [ ] **Step 1: Write failing tests for upload-on-release and result rendering**
- [ ] **Step 2: Run the targeted tests and verify failure**
- [ ] **Step 3: Implement minimal upload/result flow**
- [ ] **Step 4: Run the targeted tests and verify pass**

### Task 3: Visual Design and Mobile Layout

**Files:**
- Create: `web/src/styles.css`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Implement idle, recording, cancel, uploading, success, and error states**
- [ ] **Step 2: Verify the build succeeds**

### Task 4: Runtime and Container Integration

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/Dockerfile`
- Create: `web/nginx.conf`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add frontend project configuration and container files**
- [ ] **Step 2: Wire frontend service into compose**
- [ ] **Step 3: Verify `npm run build` passes**
