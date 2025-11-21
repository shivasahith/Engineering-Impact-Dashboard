🚀 ENIGINEERING IMPACT DASHBOARD

A lightweight web dashboard that transforms GitHub activity into meaningful engineering insights-focusing on outcomes, impact, productivity patterns, bottlenecks, and workload balance, not vanity metrics.

📂PROJECT STRUCTURE

Codity/
│── backend/
│    ├── main.py              # FastAPI backend
│    ├── requirements.txt     # Backend dependencies
│    ├── .env                 # Your GitHub token (NOT included)
│    └── .gitignore
│
└── frontend/
     ├── index.html           # Dashboard UI
     ├── script.js            # API calls + chart rendering
     └── styles.css           # UI styling

🔧TECH STACK

Backend
    Python 3.10+
    FastAPI
    httpx (async GitHub API calls)
    Pydantic
    Statistics/time parsing modules

Frontend
    HTML5 / CSS3
    Vanilla JavaScript
    Chart.js (visualizations)

⭐FEATURES AND INSIGHTS COMPUTED

A. Engineering Impact Insights

    PRs merged per contributor
    Reviews performed
    Impact Score (custom formula):
    impact_score = total_changes × (reviewers + approvals + 1)
    Cycle Time per PR
    High Impact PRs (large size, long open time, no reviewers, etc.)

Delivered as bar charts + summary blocks.

B. Delivery Velocity

    Median Review Time
    Median Merge Time
    Bottlenecked PRs (open too long, no review activity)

Delivered as:

    Velocity Chart
    Bottleneck Table

C. Visibility Across Repositories

    Contributions per repository
    Active PRs
    Activity timeline entries (PR opened)
    Note: Timeline is included in backend output and can be visualized if extended.

D. Workload Balance

Fully implemented:

    LOC authored per person
    LOC reviewed per person
    PRs opened vs reviewed
    Burnout detection:
    Top 10% contributors doing ≥40% of total work

Delivered as a Workload Balance table.

⚙️SETUP INSTRUCTIONS

1. Clone the Repository
2. Navigate to Backend
3. Create & Activate Virtual Environment
    python -m venv .venv
    .venv\Scripts\activate   # Windows
4. Install Dependencies
    pip install -r requirements.txt
5. Create .env file Manually
    -Place your Github Token in it
6. Run Backend
    uvicorn main:app --reload

1. Frontend Setup
    - Navigate to frontend:
    cd frontend

Open UI:
    Double-click index.html, or
    Open in VS Code & use Live Server
The dashboard will open in your browser.

🧪 HOW TO USE

1. Enter one or multiple GitHub repositories:
    Example:
    microsoft/vscode, facebook/react
2. Select timeframe (ex: 7 days or 30 days)
3. Click Load Insights
4. Dashboard displays:
    Merged PRs (chart)
    Reviews performed (chart)
    Velocity metrics (chart)
    High impact PRs (chart)
    Bottleneck PRs (table)
    Workload Balance (table)

🛡 ERROR HANDLING INCLUDES:

    Skips invalid repos
    Handles GitHub API errors (rate limit, missing fields)
    Defaults empty lists instead of crashing
    Proper type checking for GitHub responses

📦 BONUS FEATURES INCLUDED

✔ Burnout Risk Detection
✔ PR Size Analysis
✔ Reviewer Metrics
✔ Review Delay Detection

🚀 OPTIONAL FUTURE ENHANCEMENTS

    Activity timeline UI
    Live websocket updates
    Backend caching (Redis)
    Advanced metrics (review depth, rework rate, bus factor)

SCREENSHOTS