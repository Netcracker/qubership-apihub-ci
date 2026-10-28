import requests
import datetime
import os
import json
import argparse
from jinja2 import Template

# --- Configuration ---
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
ORG_NAME = "Netcracker"
TOPIC_FILTER = "apihub"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}
GRAPHQL_URL = "https://api.github.com/graphql"
VERBOSE = False

# Repositories that stayed after the polyrepo migration into qubership-apihub.
MONOREPO_REPOS = frozenset({
    "qubership-apihub",
    "qubership-apihub-ci",
    "qubership-apihub-vscode",
    "qubership-apihub-aux-tools",
})

USER_GROUP_CLPLCI = "clplci"
USER_GROUP_DEPENDABOT = "dependabot"
USER_GROUP_OTHER_BOTS = "other-bots"
USER_GROUP_HUMANS = "humans"

REPO_GROUP_ARCHIVED = "archived"
REPO_GROUP_OLD_POLYREPOS = "old-polyrepos"
REPO_GROUP_MONOREPO = "monorepo"

STATUS_DRAFT = "Draft"
STATUS_NOT_DRAFT = "Not Draft"

CI_RED = "red"
CI_GREEN = "green"
CI_PROGRESS = "in progress"
CI_NONE = "no checks"
APPROVAL_YES = "approved"
APPROVAL_NO = "not approved yet"
COMMENT_LIMIT = 160
COMMENT_TITLE_LIMIT = 400

# Rollup state is the aggregate GitHub already shows on the PR.
# Individual CANCELLED runs are often superseded jobs and must not paint a green PR red.
RED_ROLLUP_STATES = frozenset({"FAILURE", "ERROR"})
GREEN_ROLLUP_STATES = frozenset({"SUCCESS"})
PROGRESS_ROLLUP_STATES = frozenset({"PENDING"})

CLPLCI_LOGIN = "NetcrackerCLPLCI"
DEPENDABOT_LOGIN = "dependabot[bot]"

# Checkbox filters rendered into the report. Checked options are the default view.
REPORT_FILTERS = [
    {
        "prefix": "User",
        "attr": "data-user-group",
        "options": [
            {"value": USER_GROUP_CLPLCI, "label": CLPLCI_LOGIN, "checked": False},
            {"value": USER_GROUP_DEPENDABOT, "label": DEPENDABOT_LOGIN, "checked": False},
            {"value": USER_GROUP_OTHER_BOTS, "label": "other bots", "checked": False},
            {"value": USER_GROUP_HUMANS, "label": "Humans", "checked": True},
        ],
    },
    {
        "prefix": "Repositories",
        "attr": "data-repo-group",
        "options": [
            {"value": REPO_GROUP_ARCHIVED, "label": "Archived", "checked": False},
            {"value": REPO_GROUP_OLD_POLYREPOS, "label": "Old polyrepos", "checked": False},
            {"value": REPO_GROUP_MONOREPO, "label": "Monorepo & Co", "checked": True},
        ],
    },
    {
        "prefix": "Status",
        "attr": "data-status",
        "options": [
            {"value": STATUS_DRAFT, "label": STATUS_DRAFT, "checked": False},
            {"value": STATUS_NOT_DRAFT, "label": STATUS_NOT_DRAFT, "checked": True},
        ],
    },
]

# --- Rule definitions for "Attention Required" ---
def rule_open_more_than_10_days(pr):
    """
    Rule: PR has been open for more than 10 days.
    """
    created = datetime.datetime.strptime(pr["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    age_days = (datetime.datetime.utcnow() - created).days
    result = age_days > 10
    if VERBOSE:
        print(f"[Rule] 'open > 10 days' on PR #{pr['number']}: age_days={age_days} -> {result}")
    return result

def rule_no_issues_and_not_exempt(pr):
    """
    Rule: PR has no linked issues and its title does not start with 'chore', 'doc', or 'tech'.
    """
    no_issues = len(pr.get("issues", [])) == 0
    title_lower = pr.get("title", "").lower()
    exempt_prefix = (
        title_lower.startswith("chore") or
        title_lower.startswith("doc") or
        title_lower.startswith("tech")
    )
    result = no_issues and not exempt_prefix
    if VERBOSE:
        print(f"[Rule] 'no issues & not exempt' on PR #{pr['number']}: no_issues={no_issues}, exempt_prefix={exempt_prefix} -> {result}")
    return result

def rule_not_in_any_project(pr):
    """
    Rule: PR has no linked issues and is not assigned to any GitHub Project.
    """
    no_projects = len(pr.get("projects", [])) == 0
    no_issues = len(pr.get("issues", [])) == 0
    result = no_projects and no_issues
    if VERBOSE:
        print(f"[Rule] 'no issues & no projects' on PR #{pr['number']}: no_issues={no_issues}, no_projects={no_projects} -> {result}")
    return result

# List of rules: each rule has a function and a human-readable description
ATTENTION_RULES = [
    {"func": rule_open_more_than_10_days, "description": "PR open for more than 10 days"},
    {"func": rule_no_issues_and_not_exempt, "description": "No linked issues and title does not start with 'chore', 'doc', or 'tech'"},
    {"func": rule_not_in_any_project, "description": "No linked issues and not assigned to any GitHub Project"},
]

def get_attention_reasons(pr):
    """
    Collect descriptions of all rules that triggered for this PR.
    Returns a list of human-readable reasons (may be empty).
    """
    reasons = []
    for rule in ATTENTION_RULES:
        try:
            if rule["func"](pr):
                reasons.append(rule["description"])
        except Exception as e:
            if VERBOSE:
                print(f"[Error] evaluating rule '{rule['description']}' on PR #{pr['number']}: {e}")
            continue
    return reasons

def classify_user(login, user_type):
    """Map a PR author to one User-filter bucket."""
    if login == CLPLCI_LOGIN:
        return USER_GROUP_CLPLCI
    if login == DEPENDABOT_LOGIN:
        return USER_GROUP_DEPENDABOT
    if user_type == "Bot" or login.endswith("[bot]"):
        return USER_GROUP_OTHER_BOTS
    return USER_GROUP_HUMANS

def classify_repo(repo_name, archived):
    """Map a repository to one Repositories-filter bucket."""
    if archived:
        return REPO_GROUP_ARCHIVED
    if repo_name in MONOREPO_REPOS:
        return REPO_GROUP_MONOREPO
    return REPO_GROUP_OLD_POLYREPOS

def classify_ci(rollup):
    """Red when any check failed, yellow while checks are still running, green when they passed."""
    if not rollup:
        return CI_NONE
    state = rollup.get("state") or ""
    if state in RED_ROLLUP_STATES:
        return CI_RED
    if state in PROGRESS_ROLLUP_STATES:
        return CI_PROGRESS
    if state in GREEN_ROLLUP_STATES:
        return CI_GREEN
    return CI_NONE

def classify_approval(reviews):
    """Approved when at least one reviewer's latest review is an approval."""
    latest_by_author = {}
    for index, review in enumerate(reviews or []):
        if not review:
            continue
        author = ((review.get("author") or {}).get("login")) or f"unknown-{index}"
        submitted_at = review.get("submittedAt") or ""
        previous = latest_by_author.get(author)
        if previous is None or submitted_at >= previous[0]:
            latest_by_author[author] = (submitted_at, review.get("state") or "")
    for _, state in latest_by_author.values():
        if state == "APPROVED":
            return APPROVAL_YES
    return APPROVAL_NO

def truncate_comment(text, limit):
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    if limit <= 1:
        return "…"
    return collapsed[: limit - 1].rstrip() + "…"

def latest_comment_text(timeline_nodes):
    """Return a short preview and a longer hover text for the newest PR comment."""
    best_at = ""
    best_body = ""
    for node in timeline_nodes or []:
        if not node:
            continue
        candidates = []
        if node.get("__typename") == "PullRequestReviewThread":
            comments = (node.get("comments") or {}).get("nodes") or []
            for comment in comments:
                if comment:
                    candidates.append((comment.get("createdAt") or "", comment.get("body") or ""))
        elif node.get("__typename") == "PullRequestReview":
            candidates.append((node.get("submittedAt") or "", node.get("body") or ""))
        else:
            candidates.append((node.get("createdAt") or "", node.get("body") or ""))
        for created_at, body in candidates:
            if body.strip() and created_at >= best_at:
                best_at = created_at
                best_body = body
    return truncate_comment(best_body, COMMENT_LIMIT), truncate_comment(best_body, COMMENT_TITLE_LIMIT)

def empty_pr_graphql_details():
    return {
        "issues": [],
        "projects": [],
        "ci": CI_NONE,
        "approval": APPROVAL_NO,
        "comment": "",
        "comment_title": "",
    }

def parse_pr_graphql_payload(pr_node):
    if not pr_node:
        return empty_pr_graphql_details()
    issues = []
    for node in (pr_node.get("closingIssuesReferences") or {}).get("nodes") or []:
        if not node:
            continue
        url = node.get("url")
        title = node.get("title")
        if url and title:
            issues.append((url, title))
    projects = []
    for node in (pr_node.get("projectsV2") or {}).get("nodes") or []:
        if not node:
            continue
        title = node.get("title")
        if title:
            projects.append(title)
    commits = (pr_node.get("commits") or {}).get("nodes") or []
    rollup = None
    if commits and commits[0] and commits[0].get("commit"):
        rollup = commits[0]["commit"].get("statusCheckRollup")
    comment, comment_title = latest_comment_text((pr_node.get("timelineItems") or {}).get("nodes"))
    return {
        "issues": issues,
        "projects": projects,
        "ci": classify_ci(rollup),
        "approval": classify_approval((pr_node.get("reviews") or {}).get("nodes")),
        "comment": comment,
        "comment_title": comment_title,
    }

PR_DETAILS_QUERY = """
query($owner: String!, $repo: String!, $prNumber: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $prNumber) {
      closingIssuesReferences(first: 10) {
        nodes { title url }
      }
      projectsV2(first: 10) {
        nodes { title }
      }
      reviews(last: 100) {
        nodes {
          state
          submittedAt
          author { login }
        }
      }
      timelineItems(last: 20, itemTypes: [ISSUE_COMMENT, PULL_REQUEST_REVIEW, PULL_REQUEST_REVIEW_THREAD]) {
        nodes {
          __typename
          ... on IssueComment { body createdAt }
          ... on PullRequestReview { body submittedAt }
          ... on PullRequestReviewThread {
            comments(last: 1) { nodes { body createdAt } }
          }
        }
      }
      commits(last: 1) {
        nodes {
          commit {
            statusCheckRollup { state }
          }
        }
      }
    }
  }
}
"""

def get_pr_details_via_graphql(owner, repo, pr_number):
    """Fetch linked issues, projects, check rollup, reviews, and the latest comment."""
    variables = {"owner": owner, "repo": repo, "prNumber": pr_number}
    if VERBOSE:
        print(f"[GraphQL] Requesting PR details for {owner}/{repo}#{pr_number}")
    response = requests.post(
        GRAPHQL_URL,
        json={"query": PR_DETAILS_QUERY, "variables": variables},
        headers=HEADERS,
    )
    data = response.json()
    if data.get("errors"):
        message = data["errors"][0].get("message", data["errors"][0])
        print(f"[GraphQL] Partial error for {owner}/{repo}#{pr_number}: {message}")
    if VERBOSE:
        print(f"[GraphQL] Response for PR #{pr_number}: {json.dumps(data, indent=2)[:500]}...")
    repository = (data.get("data") or {}).get("repository") or {}
    return parse_pr_graphql_payload(repository.get("pullRequest"))

# --- Search for repositories with the specified topic using GitHub search API ---
def get_repositories_with_topic(org, topic):
    # Search omits archived repositories unless archived:true is set explicitly.
    repos = {}
    for archived in ("false", "true"):
        page = 1
        while True:
            url = (
                "https://api.github.com/search/repositories"
                f"?q=topic:{topic}+org:{org}+archived:{archived}&per_page=100&page={page}"
            )
            if VERBOSE:
                print(f"[REST] Searching repositories from: {url}")
            resp = requests.get(url, headers=HEADERS).json()
            if VERBOSE:
                print(f"[REST] Response repos page {page}: {json.dumps(resp, indent=2)[:500]}...")
            items = resp.get("items")
            if not items:
                if resp.get("message"):
                    print(f"[REST] GitHub search error: {resp.get('message')}")
                break
            for repo in items:
                repos[repo["full_name"]] = {
                    "full_name": repo["full_name"],
                    "name": repo["name"],
                    "archived": bool(repo.get("archived")),
                }
            if len(items) < 100:
                break
            page += 1
    if VERBOSE:
        print(f"[REST] Total repositories found: {len(repos)}")
    return list(repos.values())

# --- Fetch open pull requests along with issues and projects ---
def get_pull_requests(repo_info):
    prs = []
    repo_full_name = repo_info["full_name"]
    repo_group = classify_repo(repo_info["name"], repo_info["archived"])
    url = f"https://api.github.com/repos/{repo_full_name}/pulls?state=open"
    if VERBOSE:
        print(f"[REST] Fetching PRs from: {url}")
    resp = requests.get(url, headers=HEADERS).json()
    if VERBOSE:
        print(f"[REST] Response PRs for {repo_full_name}: {json.dumps(resp, indent=2)[:500]}...")
    for pr in resp:
        owner, repo = repo_full_name.split("/")
        pr_number = pr["number"]

        # One GraphQL call covers issues, projects, checks, reviews, and the latest comment.
        details = get_pr_details_via_graphql(owner, repo, pr_number)

        user = pr.get("user") or {}
        login = user.get("login", "")
        is_draft = pr.get("draft", False)
        pr_details = {
            "number": pr_number,
            "html_url": pr.get("html_url", ""),
            "title": pr.get("title", ""),
            "user": login,
            "user_group": classify_user(login, user.get("type", "")),
            "created_at": pr.get("created_at", ""),
            "assignee": pr.get("assignee", {}).get("login", "Empty") if pr.get("assignee") else "Empty",
            "repo": repo_full_name,
            "repo_name": repo,
            "repo_group": repo_group,
            "issues": details["issues"],
            "projects": details["projects"],
            "ci": details["ci"],
            "approval": details["approval"],
            "comment": details["comment"],
            "comment_title": details["comment_title"],
            "status": STATUS_DRAFT if is_draft else STATUS_NOT_DRAFT
        }
        if VERBOSE:
            print(
                f"[PR] Collected details for PR #{pr_number}: "
                f"issues={details['issues']}, projects={details['projects']}, "
                f"ci={details['ci']}, approval={details['approval']}"
            )
        # Collect reasons why this PR requires attention
        pr_details["attention_reasons"] = get_attention_reasons(pr_details)
        if VERBOSE and pr_details["attention_reasons"]:
            print(f"[Attention] PR #{pr_number} reasons: {pr_details['attention_reasons']}")
        prs.append(pr_details)
    return prs

# --- HTML template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <title>GitHub PR Report</title>
    <script src='https://unpkg.com/list.js@1.5.0/dist/list.min.js'></script>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; background: #fff; color: #222; }
        .rules-panel {
            border: 1px solid #ccc;
            padding: 10px;
            margin-bottom: 20px;
            background-color: #f2f2f2;
        }
        .rules-panel strong {
            display: block;
            margin-bottom: 8px;
        }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; color: #222; }
        th { cursor: pointer; background: #f3f3f3; }
        .color-0 { background-color: #f9f9f9; }
        .color-1 { background-color: #e7f4ff; }
        .color-2 { background-color: #fef9e7; }
        .color-3 { background-color: #eaf7ea; }
        .color-4 { background-color: #fceeee; }
        .filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 12px; }
        .filter-dropdown { position: relative; }
        .filter-toggle {
            background: #fff;
            border: 1px solid #bbb;
            border-radius: 4px;
            padding: 6px 28px 6px 10px;
            cursor: pointer;
            font: inherit;
            text-align: left;
            position: relative;
        }
        .filter-toggle::after {
            content: "";
            position: absolute;
            right: 10px;
            top: 50%;
            margin-top: -2px;
            border: 5px solid transparent;
            border-top-color: #333;
        }
        .filter-dropdown.open .filter-toggle::after {
            margin-top: -7px;
            border-top-color: transparent;
            border-bottom-color: #333;
        }
        .filter-menu {
            display: none;
            position: absolute;
            z-index: 20;
            top: calc(100% + 4px);
            left: 0;
            min-width: 100%;
            background: #fff;
            border: 1px solid #ccc;
            border-radius: 4px;
            padding: 8px 12px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
        }
        .filter-dropdown.open .filter-menu { display: block; }
        .filter-menu label {
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 4px 0;
            cursor: pointer;
            white-space: nowrap;
        }
        .pr-search {
            padding: 6px 8px;
            border: 1px solid #bbb;
            border-radius: 4px;
            font: inherit;
            min-width: 220px;
        }
        #visible-count { color: #555; }
        .ci-mark {
            display: inline-block;
            padding: 2px 8px;
            white-space: nowrap;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 700;
            text-align: center;
        }
        .ci-red { background: #f8d0d0; color: #9b1c1c; }
        .ci-progress { background: #fff3cd; color: #8a6d00; }
        .ci-green { background: #d8f3dc; color: #1b7a32; }
        .ci-none { background: #eee; color: #666; font-weight: 600; }
        .comment-clip {
            max-width: 280px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .attention-icon { color: red; font-weight: bold; display: block; }
        .attention-text { margin-left: 4px; font-style: italic; }
        #snake-hatch {
            position: fixed;
            right: 4px;
            bottom: 4px;
            width: 16px;
            height: 16px;
            border: 0;
            padding: 0;
            background: transparent;
            cursor: pointer;
            z-index: 5;
        }
        #snake-hatch::after {
            content: "";
            display: block;
            width: 5px;
            height: 5px;
            margin: 5px;
            border-radius: 50%;
            background: #ddd;
        }
        #snake-hatch:hover::after { background: #888; }
        body.snake-on #snake-hatch { display: none; }
        body.snake-on #report-chrome,
        body.snake-on #pr-report .filters { display: none; }
        body.snake-on #pr-report a,
        body.snake-on #pr-report th { pointer-events: none; }
        #snake-hud {
            display: flex;
            align-items: center;
            gap: 16px;
            margin: 0 0 8px;
            font-weight: 700;
        }
        #snake-hud[hidden] { display: none; }
        #snake-score { color: #1b5e20; }
        body.snake-on td.snake-body { background: #c8e6c9; }
        body.snake-on td.snake-head { background: #1b5e20; color: #fff; }
        body.snake-on td.snake-head a { color: #fff; }
        body.snake-on td.snake-food { background: #ffe082; }
    </style>
</head>
<body>
    <button type='button' id='snake-hatch' tabindex='-1' aria-hidden='true'></button>
    <div id='report-chrome'>
    <h1>GitHub Pull Requests Report</h1>

    <div class="rules-panel">
        <strong>Rules:</strong>
        <div>⚠️ PR is not merged in 10 days</div>
        <div>❌ PR must be linked with Issue (set 'Development' field in PR).<br>
             If no related issue (chore, docs, small tech improvements cases) – PR must be added to GitHub Project
             to current Sprint directly (set 'Project' field in PR)</div>
    </div>
    </div>

    <div id='pr-report'>
    <div id='snake-hud' hidden>
        <span id='snake-score'>0</span>
        <span id='snake-hint'></span>
    </div>
    <div class='filters'>
        {% for filt in report_filters %}
        <div class='filter-dropdown' data-prefix='{{ filt.prefix }}' data-attr='{{ filt.attr }}'>
            <button type='button' class='filter-toggle' aria-haspopup='true' aria-expanded='false'></button>
            <div class='filter-menu' role='group' aria-label='{{ filt.prefix }}'>
                {% for opt in filt.options %}
                <label>
                    <input type='checkbox' value='{{ opt.value }}'{% if opt.checked %} checked{% endif %}>
                    {{ opt.label }}
                </label>
                {% endfor %}
            </div>
        </div>
        {% endfor %}
        <input class='pr-search' placeholder='Filter PRs...' aria-label='Filter PRs'>
        <span id='visible-count'></span>
    </div>
    <table>
        <thead>
            <tr>
                <th class='sort' data-sort='repo'>📁 Repository</th>
                <th class='sort' data-sort='title'>📌 PR name</th>
                <th class='sort' data-sort='author'>👤 PR author</th>
                <th class='sort' data-sort='status'>📋 Status</th>
                <th class='sort' data-sort='ci'>CI</th>
                <th class='sort' data-sort='approval'>Approvals</th>
                <th class='sort' data-sort='age'>📅 PR age</th>
                <th class='sort' data-sort='assignee'>👤 PR assignee</th>
                <th>🔗 PR issues</th>
                <th class='sort' data-sort='comment'>Last comment</th>
                <th class='sort' data-sort='attention'>❗ Attention Required</th>
            </tr>
        </thead>
        <tbody class='list'>
            {% set repo_colors = {} %}
            {% for repo, prs in grouped_prs.items() %}
                {% if repo not in repo_colors %}
                    {% set _ = repo_colors.update({repo: 'color-' ~ (loop.index0 % 5)}) %}
                {% endif %}
                {% for pr in prs %}
                <tr class='{{ repo_colors[repo] }}' data-status='{{ pr.status }}' data-user-group='{{ pr.user_group }}' data-repo-group='{{ pr.repo_group }}'>
                    <td class='repo'>{{ pr.repo }}</td>
                    <td class='title'><a href='{{ pr.html_url }}' target='_blank'>{{ pr.title }}</a></td>
                    <td class='author'>{{ pr.user }}</td>
                    <td class='status'>{{ pr.status }}</td>
                    <td class='ci'>
                        {% if pr.ci == 'red' %}
                        <span class='ci-mark ci-red' title='At least one check failed'>red</span>
                        {% elif pr.ci == 'in progress' %}
                        <span class='ci-mark ci-progress' title='Checks are still running'>in progress</span>
                        {% elif pr.ci == 'green' %}
                        <span class='ci-mark ci-green' title='No failing checks'>green</span>
                        {% else %}
                        <span class='ci-mark ci-none'>no checks</span>
                        {% endif %}
                    </td>
                    <td class='approval'>{{ pr.approval }}</td>
                    <td class='age'>{{ pr.age }}</td>
                    <td class='assignee'>{{ pr.assignee }}</td>
                    <td class='issues'>
                        {% for issue in pr.issues %}
                            <a href='{{ issue[0] }}' target='_blank'>{{ issue[1] }}</a>{% if not loop.last %}, {% endif %}
                        {% endfor %}
                    </td>
                    <td class='comment'><div class='comment-clip' title='{{ pr.comment_title }}'>{{ pr.comment }}</div></td>
                    <td class='attention'>
                        {% if pr.attention_reasons %}
                            <span class="attention-icon">❗</span>
                            <div class="attention-text">{{ pr.attention_reasons | join('<br/>') | safe }}</div>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            {% endfor %}
        </tbody>
    </table>
    </div>
    <script>
        function closeDropdowns() {
            document.querySelectorAll('#pr-report .filter-dropdown.open').forEach(function(dropdown) {
                dropdown.classList.remove('open');
                dropdown.querySelector('.filter-toggle').setAttribute('aria-expanded', 'false');
            });
        }

        function updateToggleLabel(dropdown) {
            var boxes = dropdown.querySelectorAll('input[type="checkbox"]');
            var selected = [];
            boxes.forEach(function(box) {
                if (box.checked) {
                    selected.push(box.parentElement.textContent.trim());
                }
            });
            var prefix = dropdown.getAttribute('data-prefix');
            var text;
            if (selected.length === 0) {
                text = prefix + ': None';
            } else if (selected.length === boxes.length) {
                text = prefix + ': All';
            } else {
                text = prefix + ': ' + selected.join(', ');
            }
            var button = dropdown.querySelector('.filter-toggle');
            button.textContent = text;
            button.title = text;
        }

        function applyFilters() {
            var query = document.querySelector('#pr-report .pr-search').value.trim().toLowerCase();
            var criteria = [];
            document.querySelectorAll('#pr-report .filter-dropdown').forEach(function(dropdown) {
                var values = [];
                dropdown.querySelectorAll('input[type="checkbox"]:checked').forEach(function(box) {
                    values.push(box.value);
                });
                criteria.push({
                    attr: dropdown.getAttribute('data-attr'),
                    values: values
                });
                updateToggleLabel(dropdown);
            });

            var visibleCount = 0;
            document.querySelectorAll('#pr-report tbody.list tr').forEach(function(row) {
                var visible = true;
                for (var i = 0; i < criteria.length; i++) {
                    if (criteria[i].values.indexOf(row.getAttribute(criteria[i].attr)) === -1) {
                        visible = false;
                        break;
                    }
                }
                if (visible && query && row.textContent.toLowerCase().indexOf(query) === -1) {
                    visible = false;
                }
                row.style.display = visible ? '' : 'none';
                if (visible) {
                    visibleCount++;
                }
            });
            var countLabel = visibleCount === 1 ? '1 pull request' : visibleCount + ' pull requests';
            document.getElementById('visible-count').textContent = countLabel;
        }

        var prList = new List('pr-report', {
            valueNames: ['repo', 'title', 'author', 'status', 'ci', 'approval', 'age', 'assignee', 'issues', 'comment', 'attention'],
            page: 10000
        });

        document.querySelectorAll('#pr-report .filter-toggle').forEach(function(button) {
            button.addEventListener('click', function(event) {
                event.stopPropagation();
                var dropdown = button.parentElement;
                var willOpen = !dropdown.classList.contains('open');
                closeDropdowns();
                if (willOpen) {
                    dropdown.classList.add('open');
                    button.setAttribute('aria-expanded', 'true');
                }
            });
        });

        document.querySelectorAll('#pr-report .filter-dropdown').forEach(function(dropdown) {
            dropdown.addEventListener('click', function(event) {
                event.stopPropagation();
            });
            dropdown.querySelectorAll('input[type="checkbox"]').forEach(function(box) {
                box.addEventListener('change', applyFilters);
            });
        });

        document.querySelector('#pr-report .pr-search').addEventListener('input', applyFilters);
        document.addEventListener('click', closeDropdowns);
        document.addEventListener('keydown', function(event) {
            if (snakeState) {
                handleSnakeKey(event);
                return;
            }
            if (event.key === 'Escape') {
                closeDropdowns();
            }
        });

        document.querySelectorAll('#pr-report th.sort').forEach(function(header) {
            header.addEventListener('click', function() {
                applyFilters();
            });
        });

        applyFilters();

        var snakeState = null;
        var SNAKE_TICK_MS = 150;

        document.getElementById('snake-hatch').addEventListener('click', function(event) {
            event.stopPropagation();
            startSnake();
        });

        function stopSnakeLoop() {
            if (snakeState && snakeState.timer) {
                clearInterval(snakeState.timer);
                snakeState.timer = null;
            }
        }

        function clearSnakeMarks() {
            document.querySelectorAll('#pr-report td.snake-head, #pr-report td.snake-body, #pr-report td.snake-food').forEach(function(cell) {
                cell.classList.remove('snake-head', 'snake-body', 'snake-food');
            });
        }

        function exitSnake() {
            stopSnakeLoop();
            clearSnakeMarks();
            snakeState = null;
            document.body.classList.remove('snake-on');
            document.getElementById('snake-hud').hidden = true;
        }

        function updateSnakeHud() {
            document.getElementById('snake-score').textContent = String(snakeState.score);
            document.getElementById('snake-hint').textContent = snakeState.hint;
        }

        function paintSnake() {
            clearSnakeMarks();
            snakeState.snake.forEach(function(part, index) {
                var cell = snakeState.grid[part.r][part.c];
                cell.classList.add(index === 0 ? 'snake-head' : 'snake-body');
            });
            if (snakeState.food) {
                snakeState.grid[snakeState.food.r][snakeState.food.c].classList.add('snake-food');
            }
        }

        function snakeOccupied(row, column, ignoreTail) {
            var parts = snakeState.snake;
            var limit = ignoreTail ? parts.length - 1 : parts.length;
            for (var i = 0; i < limit; i++) {
                if (parts[i].r === row && parts[i].c === column) {
                    return true;
                }
            }
            return false;
        }

        function finishSnake(message) {
            stopSnakeLoop();
            snakeState.alive = false;
            snakeState.hint = message + ' Enter retries. Esc leaves.';
            updateSnakeHud();
            paintSnake();
        }

        function placeSnakeFood() {
            var empty = [];
            for (var row = 0; row < snakeState.grid.length; row++) {
                for (var column = 0; column < snakeState.grid[row].length; column++) {
                    if (!snakeOccupied(row, column, false)) {
                        empty.push({r: row, c: column});
                    }
                }
            }
            if (!empty.length) {
                snakeState.food = null;
                finishSnake('Cleared the table.');
                return;
            }
            snakeState.food = empty[Math.floor(Math.random() * empty.length)];
        }

        function snakeTick() {
            if (!snakeState || !snakeState.alive) {
                return;
            }
            var dir = snakeState.nextDir;
            if (dir.r === -snakeState.dir.r && dir.c === -snakeState.dir.c) {
                dir = snakeState.dir;
            }
            snakeState.dir = dir;
            snakeState.nextDir = {r: dir.r, c: dir.c};
            var head = snakeState.snake[0];
            var nextRow = head.r + dir.r;
            var nextColumn = head.c + dir.c;
            var rowCount = snakeState.grid.length;
            var columnCount = snakeState.grid[0].length;
            if (nextRow < 0 || nextColumn < 0 || nextRow >= rowCount || nextColumn >= columnCount) {
                finishSnake('Hit the edge.');
                return;
            }
            var eating = snakeState.food && snakeState.food.r === nextRow && snakeState.food.c === nextColumn;
            if (snakeOccupied(nextRow, nextColumn, !eating)) {
                finishSnake('Bit itself.');
                return;
            }
            snakeState.snake.unshift({r: nextRow, c: nextColumn});
            if (eating) {
                snakeState.score += 1;
                placeSnakeFood();
                if (!snakeState.alive) {
                    return;
                }
                updateSnakeHud();
            } else {
                snakeState.snake.pop();
            }
            paintSnake();
        }

        function startSnake() {
            exitSnake();
            var grid = [];
            document.querySelectorAll('#pr-report tbody.list tr').forEach(function(row) {
                if (row.style.display === 'none') {
                    return;
                }
                var cells = [];
                Array.prototype.forEach.call(row.children, function(cell) {
                    if (cell.tagName === 'TD') {
                        cells.push(cell);
                    }
                });
                if (cells.length) {
                    grid.push(cells);
                }
            });
            if (!grid.length) {
                return;
            }
            var columns = grid[0].length;
            grid.forEach(function(line) {
                if (line.length < columns) {
                    columns = line.length;
                }
            });
            grid = grid.map(function(line) { return line.slice(0, columns); });
            if (columns < 1 || grid.length * columns < 2) {
                return;
            }

            var snake = [];
            var dir;
            if (columns >= 2) {
                var length = Math.min(3, columns - 1);
                for (var index = 0; index < length; index++) {
                    snake.push({r: 0, c: length - 1 - index});
                }
                dir = {r: 0, c: 1};
            } else {
                var verticalLength = Math.min(3, grid.length - 1);
                for (var verticalIndex = 0; verticalIndex < verticalLength; verticalIndex++) {
                    snake.push({r: verticalLength - 1 - verticalIndex, c: 0});
                }
                dir = {r: 1, c: 0};
            }

            snakeState = {
                grid: grid,
                snake: snake,
                dir: dir,
                nextDir: {r: dir.r, c: dir.c},
                food: null,
                score: 0,
                alive: true,
                hint: 'Arrows move. Esc leaves.',
                timer: null
            };
            document.body.classList.add('snake-on');
            document.getElementById('snake-hud').hidden = false;
            closeDropdowns();
            placeSnakeFood();
            updateSnakeHud();
            paintSnake();
            if (snakeState.alive) {
                snakeState.timer = setInterval(snakeTick, SNAKE_TICK_MS);
            }
        }

        function handleSnakeKey(event) {
            var key = event.key;
            if (key === 'Escape') {
                event.preventDefault();
                exitSnake();
                return;
            }
            if (!snakeState) {
                return;
            }
            if (key.length === 1) {
                key = key.toLowerCase();
            }
            if ((key === 'Enter' || key === ' ') && !snakeState.alive) {
                event.preventDefault();
                startSnake();
                return;
            }
            var directions = {
                ArrowUp: {r: -1, c: 0},
                ArrowDown: {r: 1, c: 0},
                ArrowLeft: {r: 0, c: -1},
                ArrowRight: {r: 0, c: 1},
                w: {r: -1, c: 0},
                a: {r: 0, c: -1},
                s: {r: 1, c: 0},
                d: {r: 0, c: 1}
            };
            var next = directions[key];
            if (!next || !snakeState.alive) {
                return;
            }
            event.preventDefault();
            if (next.r === -snakeState.dir.r && next.c === -snakeState.dir.c) {
                return;
            }
            snakeState.nextDir = next;
        }
    </script>
</body>
</html>
"""

# --- Generate report ---
def generate_html_report():
    repositories = get_repositories_with_topic(ORG_NAME, TOPIC_FILTER)
    grouped_prs = {}
    now = datetime.datetime.utcnow()

    for repo in repositories:
        prs = get_pull_requests(repo)
        for pr in prs:
            created = datetime.datetime.strptime(pr["created_at"], "%Y-%m-%dT%H:%M:%SZ")
            pr["age"] = str((now - created).days) + " days"
        grouped_prs[repo["full_name"]] = prs

    template = Template(HTML_TEMPLATE)
    rendered = template.render(grouped_prs=grouped_prs, report_filters=REPORT_FILTERS)
    filename = f"report_prs_{now.strftime('%Y%m%d_%H%M%S')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"✅ Report saved to file: {filename}")

def main():
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()
    VERBOSE = args.verbose
    generate_html_report()

if __name__ == "__main__":
    main()
