🧠 SchedulerAI — Autonomous Distributed System Orchestrator
<p align="center"> <em>"Static logic cannot survive dynamic chaos."</em> </p> <p align="center"> <img src="https://img.shields.io/badge/LLM-Powered-blue?style=for-the-badge" /> <img src="https://img.shields.io/badge/FastAPI-Backend-green?style=for-the-badge" /> <img src="https://img.shields.io/badge/React-Frontend-skyblue?style=for-the-badge" /> <img src="https://img.shields.io/badge/Distributed%20Systems-Simulator-purple?style=for-the-badge" /> </p> <p align="center"> SchedulerAI is a **self-driving infrastructure simulator** that uses Generative AI (Google Gemini) to dynamically detect deadlocks, resolve contention, and hot-swap scheduling strategies in real time. <br/> Think of it as **Kubernetes + OS scheduling algorithms + an autonomous SRE agent**, all inside one interactive system. </p>
📌 Table of Contents

🔥 The Problem

💡 The Solution

🏗 Architecture

🚀 Key Features

🎓 OS Concepts

🛠 Tech Stack

⚙️ Installation

🎮 How to Run

💥 The Problem: Thundering Herds

Modern distributed systems (Netflix, AWS, Databases, Edge Networks) frequently collapse not from hardware failures but from:

Resource Contention

Live-locks / Deadlocks

Hot Spots

Queue Overload

Race Conditions

Static scheduling algorithms fail exactly when traffic becomes unpredictable.

Algorithm	Failure Mode
Round Robin	Creates hot spots — one server overloaded while others idle
Token Ring	Fair but extremely slow under high load
Random Backoff	Reduces collisions but drastically increases latency
Consistent Hashing	Good for sharding but terrible for bursty traffic

⚠️ By the time humans detect a bottleneck, the system has already collapsed.

💡 The Solution: Self-Driving Infrastructure

SchedulerAI uses a continuous OODA Loop driven by an LLM:

🔍 Observe

A discrete-event simulation engine (“Kernel”) emits live telemetry every 500ms.

🧭 Orient

A React dashboard visualizes server load, queue depth, throughput, and contention.

🤖 Decide

A Gemini-powered agent analyzes patterns to detect:

Deadlocks

Starvation

Excessive queueing

Load imbalance

⚡ Act

Based on semantic reasoning, the AI switches the scheduling algorithm on the fly.

No restarts.
No downtime.
Fully autonomous.

🏗 System Architecture
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


Design Philosophy: OS Kernel + Distributed System Simulator + AI SRE
All loosely coupled using REST + WebSockets.

🚀 Key Features
🧩 1. Multi-Strategy Kernel

Simulates 5 real OS & distributed scheduling algorithms:

FCFS (Baseline) – Fast but unfair

Random Backoff (CSMA/CD) – Ethernet-style collision handling

Consistent Hashing – Used in Cassandra, DynamoDB

Token Ring – Ensures strict mutual exclusion

Leader Election – Kubernetes-style orchestrator simulation

🤖 2. Autonomous AI SRE

Google Gemini 2.5 is integrated as a real-time reasoning engine.

Consumes JSON metrics

Uses Structured Outputs

Issues valid control commands

Detects deadlocks before they happen

📊 3. Real-Time Dashboard

Built with Recharts + WebSockets, delivering live updates at 60fps.

Features:

Server Grid (Processing State)

Queue Depth Chart

Throughput Timeline

AI Decisions Log

🔐 4. Deadlock Detection Engine

Built-in heuristics monitor:

Queue stagnation

Circular wait patterns

Token starvation

Low throughput-to-arrival ratio

When detected → AI picks a new strategy.

🎓 Operating System Concepts Implemented
OS Concept	Implemented As
Process Scheduling	Job Queue + Kernel strategies
Concurrency	Python asyncio
Deadlocks	Queue vs Throughput heuristics
Race Conditions	Random Backoff collisions
Mutual Exclusion	Token Ring
IPC	WebSockets between backend ↔ frontend

This project is essentially a teaching OS kernel, visualized in real time.

🛠 Tech Stack
🎨 Frontend

React 19

TypeScript

Tailwind CSS

Recharts

Vite

⚙️ Backend

FastAPI

Python 3.11

AsyncIO

SQLModel

Uvicorn

🤖 AI & DevOps

Google Gemini API

Docker

Git

⚙️ Installation & Setup
Prerequisites

Node.js (18+)

Python 3.10+

Gemini API Key

1️⃣ Backend Setup (Kernel)
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000

2️⃣ Frontend Setup (Dashboard)
npm install


Create ./.env.local:

GEMINI_API_KEY=your_key_here


Run the app:

npm run dev

🎮 How to Run

1️⃣ Start Backend on port 8000
2️⃣ Start Frontend on port 3000
3️⃣ Open: http://localhost:3000

✔ Click "Start Simulation → Baseline"

Then watch:

📈 Queue length rise & fall

⚙️ Servers handling jobs

🤖 AI agent reasoning logs

🔁 Algorithm hot-swaps in real time
