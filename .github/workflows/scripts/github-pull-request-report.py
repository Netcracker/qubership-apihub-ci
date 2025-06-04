import requests
import datetime
import os
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

# --- Argument parser for verbose mode ---
parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
args = parser.parse_args()
VERBOSE = args.verbose

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

# --- GraphQL helper to get linked issues via the Development section ---
def get_linked_issues_via_graphql(owner, repo, pr_number):
    """
    Fetch closing issues for a given pull request via GraphQL.
    Returns a list of (url, title) tuples.
    """
    query = '''
    query($owner: String!, $repo: String!, $prNumber: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $prNumber) {
          closingIssuesReferences(first: 10) {
            nodes {
              title
              url
            }
          }
        }
      }
    }
    '''
    variables = {"owner": owner, "repo": repo, "prNumber": pr_number}
    if VERBOSE:
        print(f"[GraphQL] Requesting issues for {owner}/{repo} PR #{pr_number} with variables: {variables}")
    response = requests.post(GRAPHQL_URL, json={"query": query, "variables": variables}, headers=HEADERS)
    data = response.json()
    if VERBOSE:
        print(f"[GraphQL] Response for issues (PR #{pr_number}): {json.dumps(data, indent=2)}")

    repository = data.get("data", {}).get("repository") or {}
    pr_node = repository.get("pullRequest") or {}
    issues = []
    for node in pr_node.get("closingIssuesReferences", {}).get("nodes", []):
        url = node.get("url")
        title = node.get("title")
        if url and title:
            issues.append((url, title))
    if VERBOSE:
        print(f"[GraphQL] Parsed issues for PR #{pr_number}: {issues}")
    return issues

# --- GraphQL helper to get project assignments from ProjectsV2 ---
def get_pr_projects_via_graphql(owner, repo, pr_number):
    """
    Fetch ProjectsV2 entries (project titles) for a given pull request via GraphQL.
    Returns a list of project titles.
    """
    query = '''
    query($owner: String!, $repo: String!, $prNumber: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $prNumber) {
          projectsV2(first: 10) {
            nodes {
              title
            }
          }
        }
      }
    }
    '''
    variables = {"owner": owner, "repo": repo, "prNumber": pr_number}
    if VERBOSE:
        print(f"[GraphQL] Requesting projectsV2 for {owner}/{repo} PR #{pr_number} with variables: {variables}")
    response = requests.post(GRAPHQL_URL, json={"query": query, "variables": variables}, headers=HEADERS)
    data = response.json()
    if VERBOSE:
        print(f"[GraphQL] Response for projectsV2 (PR #{pr_number}): {json.dumps(data, indent=2)}")

    repository = data.get("data", {}).get("repository") or {}
    pr_node = repository.get("pullRequest") or {}
    projects = []
    for node in pr_node.get("projectsV2", {}).get("nodes", []):
        title = node.get("title")
        if title:
            projects.append(title)
    if VERBOSE:
        print(f"[GraphQL] Parsed projects for PR #{pr_number}: {projects}")
    return projects

# --- Search for repositories with the specified topic using GitHub search API ---
def get_repositories_with_topic(org, topic):
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/search/repositories?q=topic:{topic}+org:{org}&per_page=100&page={page}"
        if VERBOSE:
            print(f"[REST] Searching repositories from: {url}")
        resp = requests.get(url, headers=HEADERS).json()
        if VERBOSE:
            print(f"[REST] Response repos page {page}: {json.dumps(resp, indent=2)[:500]}...")
        if not resp.get("items"):
            break
        for repo in resp["items"]:
            repos.append(repo["full_name"])
        if len(resp["items"]) < 100:
            break
        page += 1
    if VERBOSE:
        print(f"[REST] Total repositories found: {len(repos)}")
    return repos

# --- Fetch open pull requests along with issues and projects ---
def get_pull_requests(repo_full_name):
    prs = []
    url = f"https://api.github.com/repos/{repo_full_name}/pulls?state=open"
    if VERBOSE:
        print(f"[REST] Fetching PRs from: {url}")
    resp = requests.get(url, headers=HEADERS).json()
    if VERBOSE:
        print(f"[REST] Response PRs for {repo_full_name}: {json.dumps(resp, indent=2)[:500]}...")
    for pr in resp:
        owner, repo = repo_full_name.split("/")
        pr_number = pr["number"]

        # Fetch issues via GraphQL
        issues = get_linked_issues_via_graphql(owner, repo, pr_number)
        # Fetch projects via GraphQL
        projects = get_pr_projects_via_graphql(owner, repo, pr_number)

        pr_details = {
            "number": pr_number,
            "html_url": pr.get("html_url", ""),
            "title": pr.get("title", ""),
            "user": pr.get("user", {}).get("login", ""),
            "created_at": pr.get("created_at", ""),
            "assignee": pr.get("assignee", {}).get("login", "Empty") if pr.get("assignee") else "Empty",
            "repo": repo_full_name,
            "repo_name": repo,
            "issues": issues,
            "projects": projects
        }
        if VERBOSE:
            print(f"[PR] Collected details for PR #{pr_number}: issues={issues}, projects={projects}")
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
        body { font-family: Arial, sans-serif; padding: 20px; }
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
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; vertical-align: top; }
        th { cursor: pointer; }
        .color-0 { background-color: #f9f9f9; }
        .color-1 { background-color: #e7f4ff; }
        .color-2 { background-color: #fef9e7; }
        .color-3 { background-color: #eaf7ea; }
        .color-4 { background-color: #fceeee; }
        .hidden { display: none; }
        .attention-icon { color: red; font-weight: bold; display: block; }
        .attention-text { margin-left: 4px; font-style: italic; }
    </style>
</head>
<body>
    <h1>GitHub Pull Requests Report</h1>

    <div class="rules-panel">
        <strong>Rules:</strong>
        <div>⚠️ PR is not merged in 10 days</div>
        <div>❌ PR must be linked with Issue (set 'Development' field in PR).<br>
             If no related issue (chore, docs, small tech improvements cases) – PR must be added to GitHub Project
             to current Sprint directly (set 'Project' field in PR)</div>
    </div>

    <button id="toggleButton" onclick='toggleCLPLCI()'>Show PRs from NetcrackerCLPLCI</button>
    <input class='search' placeholder='Filter PRs...'>
    <table id='pr-table'>
        <thead>
            <tr>
                <th class='sort' data-sort='repo'>📁 Repository</th>
                <th class='sort' data-sort='title'>📌 PR name</th>
                <th class='sort' data-sort='author'>👤 PR author</th>
                <th class='sort' data-sort='age'>📅 PR age</th>
                <th class='sort' data-sort='assignee'>👤 PR assignee</th>
                <th>🔗 PR issues</th>
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
                <tr class='{{ repo_colors[repo] }}{% if pr.user == "NetcrackerCLPLCI" %} netcrackerclplci hidden{% endif %}'>
                    <td class='repo'>{{ pr.repo }}</td>
                    <td class='title'><a href='{{ pr.html_url }}' target='_blank'>{{ pr.title }}</a></td>
                    <td class='author'>{{ pr.user }}</td>
                    <td class='age'>{{ pr.age }}</td>
                    <td class='assignee'>{{ pr.assignee }}</td>
                    <td>
                        {% for issue in pr.issues %}
                            <a href='{{ issue[0] }}' target='_blank'>{{ issue[1] }}</a>{% if not loop.last %}, {% endif %}
                        {% endfor %}
                    </td>
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
    <script>
        function toggleCLPLCI() {
            const button = document.getElementById('toggleButton');
            const isHidden = document.querySelector('.netcrackerclplci').classList.contains('hidden');
            
            document.querySelectorAll('.netcrackerclplci').forEach(row => {
                row.classList.toggle('hidden');
            });
            
            button.textContent = isHidden 
                ? 'Hide PRs from NetcrackerCLPLCI' 
                : 'Show PRs from NetcrackerCLPLCI';
        }
        
        // Initialize List.js for sorting and searching
        var options = {
            valueNames: ['repo', 'title', 'author', 'age', 'assignee', 'attention']
        };
        var prList = new List('pr-table', options);
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
        grouped_prs[repo] = prs

    template = Template(HTML_TEMPLATE)
    rendered = template.render(grouped_prs=grouped_prs)
    filename = f"report_prs_{now.strftime('%Y%m%d_%H%M%S')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"✅ Report saved to file: {filename}")

if __name__ == "__main__":
    generate_html_report()
