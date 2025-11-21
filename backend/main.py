from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import httpx
import statistics
import asyncio
from time import time

load_dotenv()
app = FastAPI(title="Eng Impact Dashboard API")

# CORS so frontend (file server / 3000) can call backend (8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = "https://api.github.com"

# -------- Performance knobs --------
MAX_PRS_PER_REPO = 30          # hard cap per repo to avoid 100s of calls
CACHE_TTL_SECONDS = 600        # 10 minutes cache (same repos + days)


class InsightsRequest(BaseModel):
    repos: list[str]
    days: int = 30


# -------- Simple in-memory cache --------
CACHE = {}  # key -> {"time": float, "data": dict}


def make_cache_key(repos: list[str], days: int):
    # sort repos so order doesn't matter
    return (tuple(sorted(repos)), days)


# -------------------------------------------------
# Helper: median
# -------------------------------------------------
def median_or_none(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return statistics.median(values)


# -------------------------------------------------
# GitHub fetch helpers
# -------------------------------------------------
async def fetch_github_prs(owner: str, repo: str, session: httpx.AsyncClient, headers: dict):
    """
    Fetch PRs for a repository.
    Always returns a LIST. If GitHub returns an error or non-list, returns [].
    We ask for the most recently created first and only 50 per page.
    """
    url = (
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls"
        f"?state=all&per_page=50&sort=created&direction=desc"
    )
    response = await session.get(url, headers=headers)

    try:
        data = response.json()
    except Exception:
        print(f"Failed to parse PR list JSON for {owner}/{repo}")
        return []

    if not isinstance(data, list):
        # This is typically an error payload like {"message": "..."}
        print(f"GitHub API error for {owner}/{repo}: {data}")
        return []

    return data


async def fetch_pr_reviews(owner, repo, pr_number, session: httpx.AsyncClient, headers: dict):
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    response = await session.get(url, headers=headers)
    if response.status_code != 200:
        return []
    try:
        return response.json()
    except Exception:
        return []


async def fetch_pr_details(owner, repo, pr_number, session: httpx.AsyncClient, headers: dict):
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}"
    response = await session.get(url, headers=headers)
    if response.status_code != 200:
        return {}
    try:
        return response.json()
    except Exception:
        return {}



async def fetch_pr_review_comments(owner, repo, pr_number, session: httpx.AsyncClient, headers: dict):
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    response = await session.get(url, headers=headers)
    if response.status_code != 200:
        return []
    try:
        return response.json()
    except Exception:
        return []


# -------------------------------------------------
# PR metrics helpers
# -------------------------------------------------
def extract_pr_size(pr_details: dict):
    additions = pr_details.get("additions", 0)
    deletions = pr_details.get("deletions", 0)
    changed_files = pr_details.get("changed_files", 0)
    total_changes = additions + deletions
    return {
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
        "total_changes": total_changes,
    }


def calculate_reviewer_metrics(pr: dict, reviews: list[dict]):
    reviewers_requested = len(pr.get("requested_reviewers", []))
    reviewers_who_commented = len(
        {r.get("user", {}).get("login") for r in reviews if r.get("user")}
    )
    approvals = sum(1 for r in reviews if r.get("state") == "APPROVED")
    return {
        "reviewers_requested": reviewers_requested,
        "reviewers_commented": reviewers_who_commented,
        "approvals": approvals,
    }


def filter_prs_by_date(prs: list[dict], days: int):
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    for pr in prs:
        created_at = pr.get("created_at")
        if not created_at:
            continue
        try:
            pr_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if pr_date >= cutoff_date:
            filtered.append(pr)
        else:
            # PRs are sorted newest->oldest, so once we hit older than cutoff we can stop
            break
    return filtered


def calculate_cycle_time(pr: dict):
    created_at = pr.get("created_at")
    merged_at = pr.get("merged_at")
    if not created_at or not merged_at:
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        merged = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    except Exception:
        return None
    diff = merged - created
    return diff.total_seconds() / 3600.0


def calculate_review_time_from_reviews(pr_created_at: str, reviews: list[dict]):
    """
    Use earliest review 'submitted_at' instead of comments.
    """
    if not reviews:
        return None
    try:
        created = datetime.fromisoformat(pr_created_at.replace("Z", "+00:00"))
    except Exception:
        return None
    # find earliest submitted_at
    try:
        first_review = min(
            reviews,
            key=lambda r: datetime.fromisoformat(
                r["submitted_at"].replace("Z", "+00:00")
            ),
        )
    except Exception:
        return None
    try:
        submitted = datetime.fromisoformat(
            first_review["submitted_at"].replace("Z", "+00:00")
        )
    except Exception:
        return None
    diff = submitted - created
    return diff.total_seconds() / 3600.0


def calculate_time_to_merge(pr: dict):
    created_at = pr.get("created_at")
    merged_at = pr.get("merged_at")
    if not created_at or not merged_at:
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        merged = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    except Exception:
        return None
    diff = merged - created
    return diff.total_seconds() / 3600.0


def compute_impact_score(pr: dict):
    changes = pr.get("total_changes", 0)
    reviewers = pr.get("reviewers_commented", 0)
    approvals = pr.get("approvals", 0)
    return changes * (reviewers + approvals + 1)


def detect_burnout(work_by_contributor: dict):
    if not work_by_contributor:
        return []
    sorted_contributors = sorted(
        work_by_contributor.items(), key=lambda x: x[1], reverse=True
    )
    total_work = sum(work_by_contributor.values())
    if total_work == 0:
        return []
    top_10_percent_count = max(1, int(len(sorted_contributors) * 0.10))
    top_contributors = sorted_contributors[:top_10_percent_count]
    burnout_candidates = []
    for user, work in top_contributors:
        share = work / total_work
        if share >= 0.40:
            burnout_candidates.append(user)
    return burnout_candidates


def detect_bottlenecks(pr: dict):
    issues = []
    if pr.get("total_changes", 0) > 500:
        issues.append("Very large PR (>500 changes)")
    if pr.get("changed_files", 0) > 20:
        issues.append("Touches many files")
    review_hours = pr.get("review_time_hours")
    if review_hours is None:
        issues.append("No review started")
    elif review_hours > 24:
        issues.append("First review took >24h")
    cycle_hours = pr.get("cycle_time_hours")
    if cycle_hours is None:
        issues.append("PR still open / not merged")
    elif cycle_hours > 72:
        issues.append("PR took >72h to merge")
    if pr.get("reviewers_commented", 0) == 0:
        issues.append("No reviewers involved")
    if pr.get("approvals", 0) == 0:
        issues.append("No approvals")
    return issues


def identify_high_impact_pr(pr: dict):
    reasons = []
    if pr.get("total_changes", 0) > 500:
        reasons.append("Large PR (>500 LOC changed)")
    if pr.get("changed_files", 0) > 20:
        reasons.append("Touches many files")
    if pr.get("reviewers_commented", 0) == 0:
        reasons.append("No reviewers commented")
    if pr.get("approvals", 0) == 0:
        reasons.append("No approvals")
    cycle = pr.get("cycle_time_hours")
    if cycle and cycle > 72:
        reasons.append("Open >72h")
    if pr.get("review_time_hours") is None:
        reasons.append("No review started")
    return reasons


# -------------------------------------------------
# Aggregation over all PRs
# -------------------------------------------------
def compute_aggregations(all_prs: list[dict]):
    prs_merged_by_contributor: dict[str, int] = {}
    reviews_by_contributor: dict[str, int] = {}

    contributions_per_repo: dict[str, int] = {}
    high_impact_per_repo: dict[str, int] = {}

    review_times: list[float] = []
    merge_times: list[float] = []
    bottleneck_prs: list[dict] = []

    authored_loc: dict[str, int] = {}
    reviewed_loc: dict[str, int] = {}
    opened_prs: dict[str, int] = {}
    reviewed_prs: dict[str, int] = {}

    active_prs: list[dict] = []
    activity_timeline: list[dict] = []

    for pr in all_prs:
        repo_full = pr["base"]["repo"]["full_name"]
        author = pr["user"]["login"]
        state = pr["state"]

        # visibility
        contributions_per_repo[repo_full] = contributions_per_repo.get(repo_full, 0) + 1

        if state != "closed" and pr.get("merged_at") is None:
            active_prs.append(
                {
                    "repo": repo_full,
                    "number": pr["number"],
                    "title": pr["title"],
                    "author": author,
                    "created_at": pr["created_at"],
                }
            )

        activity_timeline.append(
            {
                "timestamp": pr["created_at"],
                "type": "pr_opened",
                "user": author,
                "repo": repo_full,
            }
        )

        # workload: opened PRs
        opened_prs[author] = opened_prs.get(author, 0) + 1

        # LOC authored
        additions = pr.get("additions", 0)
        authored_loc[author] = authored_loc.get(author, 0) + additions

        # times
        if pr.get("cycle_time_hours") is not None:
            merge_times.append(pr["cycle_time_hours"])
        if pr.get("review_time_hours") is not None:
            review_times.append(pr["review_time_hours"])

        # merged PRs
        if pr.get("merged_at"):
            prs_merged_by_contributor[author] = prs_merged_by_contributor.get(
                author, 0
            ) + 1

        # reviews performed per contributor & workload
        reviewer_logins = pr.get("reviewer_logins", [])
        for reviewer in reviewer_logins:
            if not reviewer:
                continue
            reviews_by_contributor[reviewer] = reviews_by_contributor.get(
                reviewer, 0
            ) + 1
            reviewed_prs[reviewer] = reviewed_prs.get(reviewer, 0) + 1
            reviewed_loc[reviewer] = reviewed_loc.get(reviewer, 0) + pr.get(
                "total_changes", 0
            )

        # high-impact PR counts per repo
        if pr.get("high_impact_reasons"):
            high_impact_per_repo[repo_full] = high_impact_per_repo.get(repo_full, 0) + 1

        # bottlenecks table
        if pr.get("bottlenecks"):
            bottleneck_prs.append(
                {
                    "title": pr.get("title", "N/A"),
                    "author": author,
                    "repo": repo_full,
                    "url": pr.get("html_url", ""),
                    "bottlenecks": pr["bottlenecks"],
                }
            )

    burnout_risk = detect_burnout(authored_loc)

    # normalise workload table
    per_contributor = {}
    all_users = set(opened_prs) | set(reviewed_prs) | set(authored_loc) | set(
        reviewed_loc
    )
    for user in all_users:
        per_contributor[user] = {
            "opened_prs": opened_prs.get(user, 0),
            "reviewed_prs": reviewed_prs.get(user, 0),
            "authored_loc": authored_loc.get(user, 0),
            "reviewed_loc": reviewed_loc.get(user, 0),
        }

    return {
        "impact": {
            "prs_merged_by_contributor": prs_merged_by_contributor,
            "reviews_by_contributor": reviews_by_contributor,
            "high_impact_per_repo": high_impact_per_repo,
        },
        "delivery": {
            "median_review_time_hours": median_or_none(review_times),
            "median_merge_time_hours": median_or_none(merge_times),
            "bottleneck_prs": bottleneck_prs,
        },
        "visibility": {
            "contributions_per_repo": contributions_per_repo,
            "active_prs": active_prs,
            "activity_timeline": activity_timeline,
        },
        "workload": {
            "per_contributor": per_contributor,
            "burnout_risk": burnout_risk,
        },
    }


# -------------------------------------------------
# Per-PR processing (done concurrently)
# -------------------------------------------------
async def process_single_pr(pr: dict, owner: str, repo_name: str, session: httpx.AsyncClient, headers: dict):
    pr_number = pr["number"]

    # Run details + reviews in parallel
    details_task = fetch_pr_details(owner, repo_name, pr_number, session, headers)
    reviews_task = fetch_pr_reviews(owner, repo_name, pr_number, session, headers)

    details, reviews = await asyncio.gather(details_task, reviews_task)

    # size
    size = extract_pr_size(details)
    pr.update(size)

    # reviewers & approvals
    reviewer_stats = calculate_reviewer_metrics(pr, reviews)
    pr.update(reviewer_stats)

    # list of reviewers for aggregation
    pr["reviewer_logins"] = list(
        {
            r.get("user", {}).get("login")
            for r in reviews
            if r.get("user") and r.get("user", {}).get("login")
        }
    )

    # times
    pr["cycle_time_hours"] = calculate_cycle_time(pr)
    pr["review_time_hours"] = calculate_review_time_from_reviews(
        pr["created_at"], reviews
    )
    pr["time_to_merge_hours"] = calculate_time_to_merge(pr)

    # bottlenecks & high impact flags
    pr["bottlenecks"] = detect_bottlenecks(pr)
    pr["high_impact_reasons"] = identify_high_impact_pr(pr)

    return pr


# -------------------------------------------------
# Main endpoint
# -------------------------------------------------
@app.post("/insights")
async def get_insights(request: InsightsRequest):
    # ----- cache check -----
    key = make_cache_key(request.repos, request.days)
    now = time()
    if key in CACHE:
        entry = CACHE[key]
        if now - entry["time"] < CACHE_TTL_SECONDS:
            return entry["data"]

    all_prs: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as session:
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

        for repo in request.repos:
            if "/" not in repo:
                continue

            owner, repo_name = repo.split("/")
            prs = await fetch_github_prs(owner, repo_name, session, headers)
            recent_prs = filter_prs_by_date(prs, request.days)

            # hard cap per repo for performance
            recent_prs = recent_prs[:MAX_PRS_PER_REPO]

            # process PRs concurrently
            tasks = [
                process_single_pr(pr, owner, repo_name, session, headers)
                for pr in recent_prs
            ]
            processed = await asyncio.gather(*tasks)
            all_prs.extend(processed)

    summary = compute_aggregations(all_prs)

    result = {
        "contributors": summary["impact"]["prs_merged_by_contributor"],
        "reviews_by_contributor": summary["impact"]["reviews_by_contributor"],
        "delivery": summary["delivery"],
        "high_impact": summary["impact"]["high_impact_per_repo"],
        "bottlenecks": summary["delivery"]["bottleneck_prs"],
        "workload": summary["workload"],
    }

    # store in cache
    CACHE[key] = {"time": now, "data": result}
    return result
