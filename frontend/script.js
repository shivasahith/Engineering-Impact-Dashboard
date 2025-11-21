let chartMerged, chartReviews, chartVelocity, chartImpact;

async function loadInsights() {
    const repoInput = document.getElementById("repoInput").value.trim();
    const days = parseInt(document.getElementById("daysInput").value || "30", 10);

    if (!repoInput) {
        alert("Enter at least one GitHub repo (e.g. facebook/react).");
        return;
    }

    const repos = repoInput
        .split(",")
        .map(r => r.trim())
        .filter(r => r.includes("/"));

    const payload = { repos, days };

    try {
        const response = await fetch("http://127.0.0.1:8000/insights", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            alert("Backend error: " + response.status);
            return;
        }

        const data = await response.json();
        console.log("INSIGHTS:", data);

        drawCharts(data);
        fillBottlenecks(data.bottlenecks || []);
        renderWorkloadTable(data);
    } catch (err) {
        console.error(err);
        alert("Failed to load insights. Check that the FastAPI server is running.");
    }
}

function destroyIfExists(chart) {
    if (chart) chart.destroy();
}

function drawCharts(data) {
    destroyIfExists(chartMerged);
    destroyIfExists(chartReviews);
    destroyIfExists(chartVelocity);
    destroyIfExists(chartImpact);

    // 1) PRs merged by contributor
    const mergedLabels = Object.keys(data.contributors || {});
    const mergedValues = Object.values(data.contributors || {});

    chartMerged = new Chart(document.getElementById("chartMerged"), {
        type: "bar",
        data: {
            labels: mergedLabels,
            datasets: [{
                label: "PRs Merged",
                data: mergedValues
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            }
        }
    });

    // 2) Reviews performed by contributor
    const reviewLabels = Object.keys(data.reviews_by_contributor || {});
    const reviewValues = Object.values(data.reviews_by_contributor || {});

    chartReviews = new Chart(document.getElementById("chartReviews"), {
        type: "bar",
        data: {
            labels: reviewLabels,
            datasets: [{
                label: "Reviews Performed",
                data: reviewValues
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            }
        }
    });

    // 3) Median review & merge times
    const reviewTime = (data.delivery && data.delivery.median_review_time_hours) || 0;
    const mergeTime = (data.delivery && data.delivery.median_merge_time_hours) || 0;

    chartVelocity = new Chart(document.getElementById("chartVelocity"), {
        type: "bar",
        data: {
            labels: ["Median Review Time", "Median Merge Time"],
            datasets: [{
                label: "Hours",
                data: [reviewTime, mergeTime]
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            }
        }
    });

    // 4) High impact PR count per repo
    const impactLabels = Object.keys(data.high_impact || {});
    const impactValues = Object.values(data.high_impact || {});

    chartImpact = new Chart(document.getElementById("chartImpact"), {
        type: "bar",
        data: {
            labels: impactLabels,
            datasets: [{
                label: "High Impact PRs",
                data: impactValues
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            }
        }
    });
}

function fillBottlenecks(list) {
    const tbody = document.getElementById("bottleneckTable");
    tbody.innerHTML = "";

    if (!list || list.length === 0) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="5">No bottlenecked PRs in this period.</td>`;
        tbody.appendChild(tr);
        return;
    }

    list.forEach(pr => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>${pr.title || "N/A"}</td>
            <td>${pr.author || "N/A"}</td>
            <td>${pr.repo || "N/A"}</td>
            <td>${(pr.bottlenecks || []).join(", ")}</td>
            <td>${pr.url ? `<a href="${pr.url}" target="_blank">Open</a>` : "N/A"}</td>
        `;
        tbody.appendChild(row);
    });
}

function renderWorkloadTable(data) {
    const tableBody = document.querySelector("#workloadTable tbody");
    tableBody.innerHTML = "";

    if (!data.workload || !data.workload.per_contributor) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="6">No workload data available.</td>`;
        tableBody.appendChild(tr);
        return;
    }

    const workload = data.workload.per_contributor;
    const burnoutRisk = data.workload.burnout_risk || [];

    for (const user in workload) {
        const w = workload[user];
        const tr = document.createElement("tr");

        const atRisk = burnoutRisk.includes(user);

        tr.innerHTML = `
            <td>${user}</td>
            <td>${w.opened_prs}</td>
            <td>${w.reviewed_prs}</td>
            <td>${w.authored_loc}</td>
            <td>${w.reviewed_loc}</td>
            <td style="color:${atRisk ? "red" : "green"};">
                ${atRisk ? "!! At Risk" : "OK"}
            </td>
        `;

        tableBody.appendChild(tr);
    }
}
