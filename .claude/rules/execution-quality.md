# Anti-Surface-Level Execution

## 1. Deep Verification Rule
- **Never assume** a task is complete based on code generation alone. Verify actual output (file existence, DB record counts, terminal logs) before reporting success.
- **Verification Requirement:** If you modify a database or file, run a `SELECT` query or `cat/ls` command to prove the change was applied.

## 2. No Hard-coding Policy
- **Real Data Priority:** Do not use static mock data when real data access is available. Always prefer dynamic retrieval.
- **Edge Case Handling:** Explicitly explain and handle edge cases (e.g., PDF with 0 text, empty DB table).

## 3. Self-Critique Step
- **Internal Audit:** Before finalizing any response, ask: "Is this result verifiable, or am I describing what the code *should* do?"
- **Action over Description:** If not yet verified, run the code and confirm actual output first.

## 4. Mandatory Evidence
- **Proof of Execution:** All reports must include:
  - Terminal output snippets
  - SQL result counts or data samples
  - Confirmation of created/modified file paths
