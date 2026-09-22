You are writing a technical deep-dive document for this repository. Its purpose is to explain, in depth, how the project actually works, based ONLY on what is implemented in the code. Accuracy is more important than completeness. A shorter document that is 100% true is better than a longer one with guesses.

OUTPUT: Create docs/PROJECT_DEEP_DIVE.md. Do not modify, delete, or reformat any other file. Do not install packages, build, or run the project. Read-only commands (ls, find, cat, grep, git log) are fine.

═══ GROUNDING RULES (non-negotiable) ═══
1. Never describe a file, function, class, topic, or parameter you have not opened and read in this session.
2. Every technical claim must end with a citation in the form `path/to/file.ext:L<start>-L<end>` or `path/to/file.ext::ClassName.method`. If you cannot cite it, do not write it.
3. Copy identifiers verbatim: function names, class names, ROS topic/service/action names, message types, parameter names, frame IDs, file paths.
4. Numbers (rates, thresholds, resolutions, gains, timeouts, model input sizes, etc.) must come from code or config files, with the source cited. Never estimate or round.
5. README files, comments, docstrings, and commit messages are CLAIMS, not proof. If they describe something the code does not implement, say so explicitly in a "Discrepancies" section.
6. Distinguish implementation status. Before calling something a feature, verify that it is actually called, imported, or launched. Use these labels:
   - [IMPLEMENTED] – code exists and is reachable from an entry point
   - [DEFINED, NOT WIRED] – code exists but nothing calls/launches it
   - [STUB/TODO] – placeholder, pass, NotImplementedError, TODO/FIXME
   - [COMMENTED OUT] – present only in comments
7. For third-party libraries/frameworks (e.g., Nav2, SLAM Toolbox, OpenCV, PyTorch, Ultralytics, MuJoCo), describe HOW THIS PROJECT USES them (which components, which config selects them, which parameters are set). Only explain library internals briefly, and label those sentences "Library behavior:".
8. If the purpose of a piece of code is unclear, write "Purpose not determinable from code" rather than guessing.
9. Never state runtime results, performance, accuracy, FPS, latency, hardware tested on, or success rates unless they appear in a file in the repo (logs, result files, benchmarks). Cite that file. Otherwise, put the question in the "Needs Author Input" section.
10. If you are ever unsure whether something is true, leave it out and add it to "Needs Author Input".

═══ PROCESS ═══
PHASE 1 – RECON (then pause)
- Map the repo tree, excluding: .git, build/, install/, log/, venv/.venv, node_modules, __pycache__, model weights, datasets, rosbags, and other large binaries.
- Read: README(s), package manifests (package.xml, setup.py, setup.cfg, pyproject.toml, requirements*.txt, CMakeLists.txt, package.json), all launch files, all config/param files (YAML, JSON, URDF/Xacro, world/scene XML).
- Identify every entry point (launch files, main scripts, console_scripts, CLI commands, node executables).
- Show me: (a) the filtered repo tree, (b) the list of entry points, (c) the subsystems you identified, (d) the files you plan to read for each. Then STOP and wait for my confirmation before writing.

PHASE 2 – TRACE
- Starting from each entry point, follow the execution path: what gets launched, which nodes/classes are instantiated, what each subscribes to/publishes, which functions are called, how data moves between components.
- Read every file on these paths fully. Note anything defined but never reached.

PHASE 3 – WRITE (incrementally, section by section, saving to the file as you go)
Use this structure. Skip any section that does not apply, and write "Not present in this codebase" instead of inventing content.

1. Overview – what the code does, in one paragraph, fully cited.
2. Repository Map – annotated tree of key directories/files and their role.
3. Tech Stack & Dependencies – languages, frameworks, libraries, with versions only if pinned in the repo.
4. System Architecture – Mermaid flowchart of the major components and how they connect, followed by an explanation.
5. Entry Points & How It Runs – launch files/scripts, arguments, what each starts. Include run commands only if they appear in the repo.
6. Component Deep Dives – for each module/node/class:
   - Responsibility
   - Inputs and outputs (with types)
   - Key functions/classes and what they do, step by step
   - The core algorithm or logic, explained in plain language, then precisely
   - Parameters with default values and source file
   - Error handling and edge cases actually handled
7. Runtime Data Flow – Mermaid sequenceDiagram(s) showing the order of operations for the main loop(s)/pipeline(s).
8. ROS 2 Interface (if applicable) – tables for nodes, topics (name, msg type, publisher, subscriber, QoS if set), services, actions, parameters, TF frames and the transform tree (Mermaid diagram), timer/loop rates.
9. ML / Computer Vision Pipeline (if applicable) – model source and architecture as defined in code, how weights are loaded, preprocessing, inference loop, postprocessing, thresholds, output format.
10. Control Logic & State Machines (if present) – Mermaid stateDiagram-v2 with states and transitions exactly as coded.
11. Configuration Reference – every config file, what it controls, key values.
12. Implementation Status – table of every feature/component with its status label from rule 6 and a citation.
13. Discrepancies – where README/comments/docs disagree with the code.
14. Limitations Visible in Code – TODOs, FIXMEs, hardcoded values, missing error handling, assumptions baked into the code. Cite each.
15. Needs Author Input – a list of questions only I can answer (e.g., hardware used, measured performance, results, design decisions and why, problems faced during development).

DIAGRAM RULES
- Use Mermaid only (it renders on GitHub).
- Every node/participant/state in a diagram must correspond to a real component in the code, labeled with its actual name. No conceptual boxes that don't exist in code.
- Wrap all labels in double quotes (topic names like "/cmd_vel" break Mermaid otherwise).
- Keep each diagram readable; split into multiple diagrams rather than creating one huge one.

PHASE 4 – SELF-AUDIT (mandatory before finishing)
- Re-open the cited lines for every claim in the document and confirm the claim matches the code. Fix or delete anything that doesn't.
- Delete any sentence that has no citation (except headers, transitions, and "Library behavior:" notes).
- Check every Mermaid block for syntax errors.
- At the end, report to me: number of claims verified, what you corrected or removed during the audit, and any sections you skipped because they don't apply.
