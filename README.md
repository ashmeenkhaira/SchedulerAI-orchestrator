🧠 SchedulerAI: Autonomous Distributed System Orchestrator

"Static logic cannot survive dynamic chaos."

SchedulerAI is a full-stack distributed system simulator that solves the "Thundering Herd" problem using Generative AI. Instead of relying on rigid, hard-coded scheduling rules, it uses an Autonomous AI Agent (Google Gemini) to monitor system health in real-time and dynamically "hot-swap" symmetry-breaking strategies to resolve deadlocks and resource contention.

📖 Table of Contents

The Problem: Thundering Herds

The Solution: Self-Driving Infrastructure

System Architecture

Key Features

Operating System Concepts Implemented

Tech Stack

Installation & Setup

How to Run

💥 The Problem: Thundering Herds

In modern distributed systems (like Netflix or AWS), the biggest killer isn't hardware failure—it's Resource Contention.

When thousands of requests hit a server cluster simultaneously, servers fight for the same locks, causing Deadlocks, Starvation, and Race Conditions.

Static Algorithms Fail:

Round Robin creates "Hot Spots".

Token Rings allow fairness but kill throughput.

Random Backoff increases latency during high traffic.

Engineers usually tune these manually, but by the time a human notices a bottleneck, the system has already crashed.

💡 The Solution: Self-Driving Infrastructure

SchedulerAI replaces manual tuning with an OODA Loop (Observe, Orient, Decide, Act) powered by an LLM.

Observe: A discrete-event simulator acts as the "Kernel", streaming real-time telemetry via WebSockets.

Orient: The frontend visualizes queue depth, server load, and fairness variance.

Decide: An AI Agent watches the traffic patterns. If it detects a deadlock or starvation, it semantically reasons about the best fix.

Act: The system autonomously hot-swaps the underlying scheduling algorithm (e.g., switching from Baseline to Random Backoff) without downtime.

🏗 System Architecture

The project follows a decoupled Microservices pattern, connected via REST APIs for control and WebSockets for real-time telemetry.

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


🚀 Key Features

1. Multi-Strategy Simulation Kernel

A custom-built Python engine that simulates 5 distinct OS scheduling algorithms:

Baseline (FCFS): Deterministic, prone to starvation.

Random Backoff: Simulates Ethernet-style collision avoidance (CSMA/CD).

Consistent Hashing: Simulates Database sharding/partitioning.

Token Ring: Simulates Industrial Network fairness protocols.

Leader Election: Simulates Orchestrator nodes (like Kubernetes).

2. Autonomous AI SRE

Integrated Google Gemini 2.5 to act as a Site Reliability Engineer. It parses complex JSON metrics and enforces decisions using Structured Outputs to ensure valid system commands.

3. Real-Time Telemetry Dashboard

A high-performance React frontend using Recharts and WebSockets to render server states and queue dynamics at 60fps.

4. Deadlock Detection

Heuristic algorithms running inside the kernel to detect stalled queues and circular wait conditions.

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

IPC (Inter-Process Comm)

Realized via WebSockets between Backend (Kernel) and Frontend (User Space).

🛠 Tech Stack

Frontend: React 19, TypeScript, Tailwind CSS, Recharts, Vite.

Backend: Python 3.11, FastAPI, Uvicorn, AsyncIO, SQLModel (SQLite).

AI: Google Gemini API (Generative Language Client).

DevOps: Docker, Virtual Environments.

⚙️ Installation & Setup

Prerequisites

Node.js (v18+)

Python (v3.10+)

Google Gemini API Key

1. Backend Setup (The Brain)

cd backend
python -m venv venv
# Activate Venv:
# Windows: .\venv\Scripts\Activate
# Mac/Linux: source venv/bin/activate

pip install -r requirements.txt
# Start the Kernel
uvicorn app.main:app --reload --port 8000


2. Frontend Setup (The Body)

Open a new terminal:

npm install
# Configure API Key
# Create a .env.local file in the root directory and add:
# GEMINI_API_KEY=your_key_here

npm run dev


🎮 How to Run

Ensure both Backend (port 8000) and Frontend (port 3000) terminals are running.

Open your browser to http://localhost:3000.

Click "Baseline" under "Start Simulation".

Watch the magic:

Observe the Queue Length chart rising.

See the Server Grid flashing as jobs are processed.

Look at the Agent Decisions panel to see the AI analyzing the traffic and suggesting strategy swaps!
