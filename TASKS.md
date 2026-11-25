# AI University Assistant: Tasks

Legend: `[ ]` to do. Mark `[x]` when done. Tasks marked **(verify)** depend on
an unverified assumption from the README. Do these first.

## Phase 0: Verify assumptions (do first)

- [ ] **(verify)** Can a BTH student create a Canvas access token? Find the BTH Canvas URL.
- [ ] **(verify)** Does TimeEdit offer an iCal export for your schedule? Is the URL stable?
- [ ] **(verify)** Where do grades live? Check what Canvas shows. Check whether Ladok has any usable export.
- [ ] **(verify)** Where do next-semester courses come from? Programme plan on bth.se or another source.
- [x] Choose the core question set for version 1 (see Phase 6).
- [x] Choose the LLM runtime and model (for example Ollama + a quantised open model that supports tool calling).

## Phase 1: Foundation

- [x] Project structure, dependency management, config file for settings.
- [x] Secrets handling: Canvas token and iCal URL stored locally, never committed.
- [x] LLM client wrapper (local model, swappable).
- [x] Simple CLI chat loop to test the assistant end to end.

## Phase 2: Data connectors (read-only)

- [x] Canvas client: courses, assignments (`due_at`), announcements, modules, files, grades.
- [x] Handle pagination, rate limits, and error responses.
- [x] Schedule client: fetch and parse iCal/TimeEdit into events (start, end, course, room, type).
- [x] Time handling: time zones (Europe/Stockholm), "next", "today", "this week".
- [x] Local cache so repeated questions do not hit the APIs each time.
- [x] Course catalogue / programme plan loader for next-semester courses.

## Phase 3: Tool-calling layer (structured questions)

- [x] Tool definitions with clear schemas, for example:
  - [x] `get_upcoming_assignments(course?, days?)`
  - [x] `get_assignment_due_date(course, assignment)`
  - [x] `get_next_lecture(course?)`
  - [x] `get_schedule(date_range)`
  - [x] `get_grades(course?)`
  - [x] `get_next_semester_courses()`
- [x] Agent loop: model picks a tool, runs it, reads the result, answers.
- [x] Fuzzy matching for course and assignment names ("assignment 2 in gen ai").
- [x] Rule: if the tool returns nothing, say so. Never invent dates or grades.

## Phase 4: RAG layer (unstructured questions)

- [ ] Ingest course documents: syllabi, course PM, lecture slides, announcements, regulations.
- [ ] Chunking strategy and metadata (course, document, page, date).
- [ ] Embeddings and a vector store.
- [ ] Retrieval with source citations in the answer.
- [ ] Handles: "What is the lecture about?", "What do I need to prepare?", grading rules, learning outcomes.
- [ ] Re-index when new files or announcements appear.

## Phase 5: Orchestration

- [x] Router: decide tool call, RAG, or both (for example "What do I need to prepare for my next lecture?" = find the lecture with a tool, then retrieve its content with RAG).
- [x] Conversation memory for follow-up questions ("and the one after that?").
- [x] Answers that show their source (API, calendar, or document + page).

## Phase 6: Core questions for version 1

- [ ] When is my next lecture?
- [ ] What do I need to prepare for it?
- [ ] What is the lecture about?
- [ ] When is my next assignment due? / When is Assignment X in course Y due?
- [ ] What grade did I get on exam X? (depends on the grades source)
- [ ] Which courses am I reading next semester? (depends on the source)

## Phase 7: Evaluation

- [x] Build a test set with ground truth from the APIs and documents.
- [x] Metrics: exact-match for dates and grades, correct tool selection rate.
- [ ] Metrics: RAGAS faithfulness and relevance for document questions.
- [ ] Baseline: plain RAG versus RAG + tools on date and schedule questions.
- [x] Mock Canvas dataset so tests do not need real student data.

## Phase 8: Privacy and safety

- [x] Everything runs locally by default. No personal data sent to external APIs.
- [x] Read-only access. The assistant never changes anything.
- [x] Token can be revoked and removed easily. Document how.
- [x] Guard against prompt injection from announcements or documents (treat fetched text as data, not instructions).

## Phase 9: Interface and polish (later)

- [ ] Simple UI (web or chat) after the CLI works.
- [x] Onboarding: link your account once (paste token and schedule URL).
- [x] Proactive features (optional): daily summary, deadline reminders.
- [x] README with setup instructions.

## Suggested build order

Phase 0, then 1, then 2 (Canvas deadlines first), then 3, then 4, then 5, then 6, then 7.
Add 8 as you go and 9 last. A first usable milestone is: "When is my next assignment due?" answered correctly from Canvas through a tool call.

## Status notes (2026-11-25)

- Built everything except RAG (Phase 4, done separately). `src/uniassist/rag.py` is the plug-in
  point: pass a `Retriever` and the `search_course_documents` tool appears automatically.
- Schedule is user-supplied (local `.ics`, iCal URL, or manual `schedule add`), so no TimeEdit dependency.
- Not done: simple web UI (Phase 9); the RAGAS metrics and the plain-RAG vs RAG+tools baseline (need your RAG).
- Still unverified (needs your real account): BTH Canvas token creation, real Canvas URL, Ladok/grades source,
  `uniassist --llm` end to end with a pulled Ollama model (Ollama is not installed here).
