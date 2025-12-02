<div align="center">

🧠 SchedulerAI

Autonomous Distributed System Orchestrator

"Static logic cannot survive dynamic chaos."

<br />

SchedulerAI is a full-stack distributed system simulator that solves the "Thundering Herd" problem using Generative AI. Instead of relying on rigid, hard-coded scheduling rules, it uses an Autonomous AI Agent (Google Gemini) to monitor system health in real-time and dynamically "hot-swap" symmetry-breaking strategies to resolve deadlocks and resource contention.

View Demo • Report Bug • Request Feature

</div>

📖 Table of Contents

The Problem

The Solution

System Architecture

Key Features

OS Concepts

Tech Stack

Installation & Setup

💥 The Problem: Thundering Herds

In modern distributed systems (like Netflix or AWS), the biggest killer isn't hardware failure—it's Resource Contention. When thousands of requests hit a server cluster simultaneously, servers fight for the same locks, causing Deadlocks, Starvation, and Race Conditions.

Static Algorithm

The Failure Mode

Round Robin

Creates "Hot Spots" where one server is overwhelmed while others idle.

Token Rings

Offers fairness but kills throughput due to latency waiting for the token.

Random Backoff

Prevents collisions but drastically increases latency during high traffic.

<div align="center">
<i>Engineers usually tune these manually, but by the time a human notices a bottleneck, the system has already crashed.</i>
</div>

💡 The Solution: Self-Driving Infrastructure

SchedulerAI replaces manual tuning with an OODA Loop (Observe, Orient, Decide, Act) powered by an LLM.

Observe: A discrete-event simulator acts as the "Kernel", streaming real-time telemetry via WebSockets.

Orient: The frontend visualizes queue depth, server load, and fairness variance.

Decide: An AI Agent watches the traffic patterns. If it detects a deadlock or starvation, it semantically reasons about the best fix.

Act: The system autonomously hot-swaps the underlying scheduling algorithm (e.g., switching from Baseline to Random Backoff) without downtime.

🏗 System Architecture

The project follows a decoupled Microservices pattern, connected via REST APIs for control and WebSockets for real-time telemetry.

<div align="center">

graph TD
    subgraph "Frontend (React + Vite)"
        UI[Dashboard UI]
        Agent[AI Service]
        Chart[Live Charts]
    end

    subgraph "Backend (FastAPI + Python)"
        API[REST API]
        WS[WebSocket Server]
        Sim[Simulation Engine (Kernel)]
    end

    subgraph "External"
        Gemini[Google Gemini API]
    end

    UI -->|Start/Stop| API
    API -->|Control| Sim
    Sim -->|Telemetry Stream (500ms)| WS
    WS -->|Live Updates| Chart
    Chart -->|Metrics| Agent
    Agent -->|Prompt| Gemini
    Gemini -->|Strategy Decision| Agent


</div>

🚀 Key Features

<table>
<tr>
<td width="50%">
<h3>1. Multi-Strategy Kernel</h3>
<p>A custom-built Python engine that simulates 5 distinct OS scheduling algorithms:</p>
<ul>
<li><b>Baseline (FCFS)</b>: Deterministic, prone to starvation.</li>
<li><b>Random Backoff</b>: Ethernet-style collision avoidance (CSMA/CD).</li>
<li><b>Consistent Hashing</b>: Database sharding/partitioning simulation.</li>
<li><b>Token Ring</b>: Industrial Network fairness protocols.</li>
<li><b>Leader Election</b>: Orchestrator node simulation (like Kubernetes).</li>
</ul>
</td>
<td width="50%">
<h3>2. Autonomous AI SRE</h3>
<p>Integrated <b>Google Gemini 2.5</b> to act as a Site Reliability Engineer. It parses complex JSON metrics and enforces decisions using <b>Structured Outputs</b> to ensure valid system commands.</p>
</td>
</tr>
<tr>
<td>
<h3>3. Real-Time Dashboard</h3>
<p>A high-performance React frontend using <b>Recharts</b> and <b>WebSockets</b> to render server states and queue dynamics at 60fps.</p>
</td>
<td>
<h3>4. Deadlock Detection</h3>
<p>Heuristic algorithms running inside the kernel to detect stalled queues and circular wait conditions.</p>
</td>
</tr>
</table>

🎓 Operating System Concepts Implemented

This project is a functional simulation of an OS Kernel managing resources:

OS Concept

Implementation in SchedulerAI

Process Scheduling

Modeled via the Job Queue and Server assignment logic.

Concurrency

Implemented using Python's asyncio for non-blocking event loops.

Deadlocks

Detected via heuristic monitoring of Queue Length vs. Throughput.

Race Conditions

Simulated via "Collisions" in the Random Backoff strategy.

Mutual Exclusion

Enforced via the Token Ring strategy (Global Lock).

IPC

Realized via WebSockets between Backend (Kernel) and Frontend (User Space).

🛠 Tech Stack

<div align="center">

Frontend

Backend

AI & DevOps

React 19

Python 3.11

Google Gemini API

TypeScript

FastAPI

Docker

Tailwind CSS

Uvicorn

Virtual Environments

Recharts

AsyncIO

Git

Vite

SQLModel (SQLite)



</div>

⚙️ Installation & Setup

<details>
<summary><b>Click to expand: Prerequisites</b></summary>

Node.js (v18+)

Python (v3.10+)

Google Gemini API Key

</details>

<details open>
<summary><b>1. Backend Setup (The Brain)</b></summary>

cd backend
python -m venv venv

# Activate Venv:
# Windows: .\venv\Scripts\Activate
# Mac/Linux: source venv/bin/activate

pip install -r requirements.txt

# Start the Kernel
uvicorn app.main:app --reload --port 8000


</details>

<details open>
<summary><b>2. Frontend Setup (The Body)</b></summary>

Open a new terminal:

npm install

# Configure API Key
# Create a .env.local file in the root directory and add:
# GEMINI_API_KEY=your_key_here

npm run dev


</details>

🎮 How to Run

Ensure both Backend (port 8000) and Frontend (port 3000) terminals are running.

Open your browser to http://localhost:3000.

Click "Baseline" under "Start Simulation".

Watch the magic:

Observe the Queue Length chart rising.

See the Server Grid flashing as jobs are processed.

Look at the Agent Decisions panel to see the AI analyzing the traffic and suggesting strategy swaps!

<div align="center">
