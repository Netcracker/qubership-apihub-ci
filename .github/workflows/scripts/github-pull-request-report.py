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
def rule_older_than_10_days(pr):
    """
    Rule: PR has been open for more than 10 days.
    """
    created = datetime.datetime.strptime(pr["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    age_days = (datetime.datetime.utcnow() - created).days
    return age_days > 10

def rule_no_issues_and_not_chore_not_docs(pr):
    """
    Rule: PR has no linked issues and its title does not start with 'chore'/'docs'.
    """
    no_issues = len(pr.get("issues", [])) == 0
    title_not_chore = not pr["title"].lower().startswith("chore")
    title_not_docs = not pr["title"].lower().startswith("docs")
    return no_issues and (title_not_chore and title_not_docs)

# List of rules: each rule has a function and a human-readable description
ATTENTION_RULES = [
    {
        "func": rule_older_than_10_days,
        "description": "PR open for more than 10 days"
    },
    {
        "func": rule_no_issues_and_not_chore_not_docs,
        "description": "No linked issues and title does not start with 'chore'/'docs'"
    },
    # Add new rules here if needed:
    # {
    #     "func": another_rule_function,
    #     "description": "Description of the new rule"
    # },
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
        except Exception:
            # Skip the rule if it raises an exception
            continue
    return reasons

# --- Search for repositories with the specified topic using GitHub search API ---
def get_repositories_with_topic(org, topic):
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/search/repositories?q=topic:{topic}+org:{org}&per_page=100&page={page}"
        if VERBOSE:
            print(f"Searching repositories from: {url}")
        resp = requests.get(url, headers=HEADERS).json()
        if VERBOSE:
            print(f"Found {len(resp.get('items', []))} repositories on page {page}")
        if not resp.get("items"):
            break
        for repo in resp["items"]:
            repos.append(repo["full_name"])
        if len(resp["items"]) < 100:
            break
        page += 1
    return repos

# --- GraphQL helper to get linked issues from the PR development section ---
def get_linked_issues_via_graphql(owner, repo, pr_number):
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
    response = requests.post(GRAPHQL_URL, json={"query": query, "variables": variables}, headers=HEADERS)
    data = response.json()
    issues = []
    nodes = data.get("data", {}).get("repository", {}).get("pullRequest", {}).get("closingIssuesReferences", {}).get("nodes", [])
    for node in nodes:
        issues.append((node["url"], node["title"]))
    return issues

# --- Fetch open pull requests and linked issues from the development section ---
def get_pull_requests(repo_full_name):
    prs = []
    url = f"https://api.github.com/repos/{repo_full_name}/pulls?state=open"
    if VERBOSE:
        print(f"Fetching PRs from: {url}")
    resp = requests.get(url, headers=HEADERS).json()
    for pr in resp:
        owner, repo = repo_full_name.split("/")
        pr_number = pr["number"]
        pr_details = {
            "html_url": pr["html_url"],
            "title": pr["title"],
            "user": pr["user"]["login"],
            "created_at": pr["created_at"],
            "assignee": pr["assignee"]["login"] if pr["assignee"] else "Empty",
            "repo": repo_full_name,
            "repo_name": repo,
            "issues": get_linked_issues_via_graphql(owner, repo, pr_number)
        }
        # Collect reasons why this PR requires attention
        pr_details["attention_reasons"] = get_attention_reasons(pr_details)
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
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        th { cursor: pointer; }
        .color-0 { background-color: #f9f9f9; }
        .color-1 { background-color: #e7f4ff; }
        .color-2 { background-color: #fef9e7; }
        .color-3 { background-color: #eaf7ea; }
        .color-4 { background-color: #fceeee; }
        .hidden { display: none; }
        .attention-icon { color: red; font-weight: bold; }
        .attention-text { margin-left: 4px; font-style: italic; }
    </style>
</head>
<body>
    <h1>Qubership APIHUB Pull Requests Report</h1>
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
                            <span class="attention-text">({{ pr.attention_reasons | join(', ') }})</span>
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
    filename = f"report_{now.strftime('%Y%m%d_%H%M%S')}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"✅ Report saved to file: {filename}")

if __name__ == "__main__":
    generate_html_report()
