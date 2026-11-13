# ChatGPT Prompt Library for a Beginner Maintaining This Project

These prompts are designed for someone who is not comfortable coding yet. Replace anything inside `[BRACKETS]` with your own information.

---

## 1. Understand a file before editing it

```text
I am working on the FRIB decision-support project and I am not an experienced programmer.

File path:
[FILE PATH]

Current contents:
[PASTE FILE]

Explain this file in plain English.
Tell me:
1. What job this file performs.
2. What other files depend on it.
3. What parts are safe to modify.
4. What changes could break other parts of the project.
5. Give me a simple map of the important functions/classes.

Do not change the code yet.
```

---

## 2. Find the correct file before making a feature

```text
I want to change this behavior in the FRIB decision-support project:

[DESCRIBE GOAL]

Assume I do not know how to code.
Do not write code yet.
First tell me:
- which exact existing files are likely involved;
- which file should be changed first;
- whether this is a config change, prompt change, UI change, processor change, API change, or data-model change;
- what could be affected by the change;
- the safest step-by-step plan.
```

---

## 3. Ask for a complete replacement file

```text
I am modifying the FRIB decision-support project.

Goal:
[GOAL]

File path:
[FILE PATH]

Current contents:
[PASTE FULL FILE]

Requirements:
[REQUIREMENTS]

Please:
1. Explain the proposed change in plain English.
2. Preserve all unrelated behavior.
3. Give me the COMPLETE replacement contents of this file, not fragments.
4. Tell me whether any other files must also change.
5. Give me exact commands/tests to verify the change.
```

---

## 4. Debug a terminal error

```text
I am working on the FRIB decision-support project.
I do not know how to debug Python yet.

Command I ran:
[EXACT COMMAND]

Complete terminal output/error:
[PASTE EVERYTHING]

Most recent file I changed:
[FILE PATH]

Current contents of that file:
[PASTE FILE]

Please:
1. Identify the root cause.
2. Explain it in plain English.
3. Tell me the smallest safe fix.
4. If a file must change, give me the COMPLETE replacement file.
5. Give me the exact command to test the fix.
6. Do not change unrelated parts of the project.
```

---

## 5. Debug a failed pytest test

```text
I ran `pytest -q` in the FRIB decision-support project and a test failed.

Test output:
[PASTE OUTPUT]

Files I changed before this failure:
[LIST FILES]

Please explain which failure is the first/root failure, not just later consequences.
Tell me which file to inspect first and why.
Do not propose a broad rewrite unless it is genuinely necessary.
```

---

## 6. Change a synthetic engineering scenario

```text
I want to modify the [RF / MECHANICAL / PLC] synthetic scenario in the FRIB project.

Goal:
[DESCRIBE WHAT THE SYNTHETIC EVENT SHOULD DO]

Current scenario YAML:
[PASTE config/scenarios/...yaml]

Current generator file:
[PASTE RELATED GENERATOR .py FILE]

First tell me whether this can be done only by changing YAML values or whether Python logic must change.
Prefer a YAML-only change if it can correctly represent the requested behavior.
Then give me the exact replacement YAML or code and a test plan.
```

---

## 7. Modify a Level-2 engineering calculation

```text
I want to modify Level-2 analysis for the [DOMAIN] domain.

Goal:
[GOAL]

Current processor:
[PASTE src/frib_ds/processing/...py]

Related generator:
[PASTE generator if useful]

Please:
1. Explain the current calculation.
2. Explain the engineering assumption it makes.
3. Propose the smallest change.
4. Keep output compatible with the existing AnalysisResult model unless there is a strong reason not to.
5. Give me the complete replacement processor file.
6. Add or update a pytest test for this behavior.
```

---

## 8. Modify the dashboard

```text
I want to modify the Streamlit dashboard in the FRIB project.

Goal:
[DESCRIBE SCREEN/CONTROL/WORDING]

Current dashboard file:
[PASTE src/frib_ds/dashboard/app.py]

Requirements:
- Preserve all existing pages unless I explicitly ask to remove one.
- Keep the existing backend API endpoints unchanged unless necessary.
- Do not move engineering logic into the dashboard.
- Give me the complete replacement dashboard file.
- Tell me exactly what to click in the UI to test the change.
```

---

## 9. Change RAG behavior

```text
I want to modify Level-3 RAG behavior.

Goal:
[GOAL]

Current RAG config:
[PASTE config/rag.yaml]

Current system prompt:
[PASTE prompts/rag_system.txt]

If needed, current RAG service:
[PASTE src/frib_ds/rag/service.py]

Please first classify the change as:
- config-only;
- prompt-only;
- retrieval-code change;
- embedding/vector-store change;
- API/UI change.

Prefer the least invasive solution.
Explain how to test that answers remain source-grounded and do not hallucinate unsupported procedures.
```

---

## 10. Switch Ollama models

```text
I want to switch the FRIB project's Ollama model.

Current `config/models.yaml`:
[PASTE FILE]

Models installed according to `ollama list`:
[PASTE OUTPUT]

My computer specs if known:
[RAM / GPU / VRAM]

Recommend which installed model to try and tell me the exact YAML change.
Do not rewrite application code unless the model requires a genuinely different API behavior.
Give me a small evaluation checklist for RAG grounding, structured output, speed, and memory use.
```

---

## 11. Switch from Ollama to LM Studio

```text
I want to switch this FRIB project from Ollama to LM Studio.

Current `config/models.yaml`:
[PASTE FILE]

LM Studio local-server information:
[PASTE SERVER URL AND MODEL ID]

Tell me the smallest configuration change needed.
Then explain how to verify the backend can talk to LM Studio before changing any other code.
```

---

## 12. Add a new engineering domain

```text
I want to add a new engineering domain called `[DOMAIN]` to this FRIB project.

Do not generate code yet.

I will provide these existing files as examples:
- generator registry
- processor registry
- one existing generator
- one existing processor
- data models

First produce a FILE-BY-FILE implementation plan showing:
1. files to create;
2. files to modify;
3. required configuration;
4. expected synthetic data;
5. Level-2 analysis output;
6. tests;
7. any dashboard changes.

After I approve the plan, guide me one file at a time and tell me to run tests after each stage.
```

---

## 13. Replace a technology without rewriting the project

```text
I want to replace `[CURRENT TECHNOLOGY]` with `[NEW TECHNOLOGY]` in the FRIB project.

Before writing code, inspect the project's adapter/interface design and identify the smallest boundary that should change.

I want to preserve:
- event schemas;
- processors;
- API endpoints;
- dashboard behavior;
- human review workflow.

Give me a migration plan and identify which files should NOT need to change.
```

---

## 14. Review generated code before I paste it

```text
Another AI generated this code for my FRIB project.
I have NOT pasted it into the project yet.

Target file:
[FILE PATH]

Current working file:
[PASTE CURRENT FILE]

Proposed replacement:
[PASTE GENERATED FILE]

Review the proposed replacement for:
- removed existing functionality;
- wrong imports;
- incorrect file paths;
- changed API/data contracts;
- unsafe assumptions;
- bugs;
- lack of tests.

Tell me whether it is safe to paste as-is. If not, produce a corrected complete replacement file.
```

---

## 15. Ask ChatGPT to create tests for a new feature

```text
I just changed this feature in the FRIB project:
[DESCRIBE FEATURE]

Changed files:
[PASTE OR LIST FILES]

Please design pytest tests that protect the intended behavior and catch likely regressions.
Use the existing test style in this repository.
Tell me exactly which test file to create or modify and give the complete contents.
```

---

## 16. Ask for a checkpoint summary after a work session

```text
We made several changes to my FRIB decision-support project today.

Here is what changed:
[PASTE NOTES / FILES / DIFFS]

Create a concise project checkpoint containing:
- files changed;
- purpose of each change;
- current working features;
- known problems;
- tests run and results;
- exact next step;
- anything I should back up before continuing.

Write it so I can paste it into a new ChatGPT conversation tomorrow and continue without losing context.
```

---

# Best practice

When possible, give ChatGPT the **actual current file** rather than asking it to guess what is in your project.

For changes affecting several files, ask for a plan first, then edit **one file at a time** and run tests between steps.
