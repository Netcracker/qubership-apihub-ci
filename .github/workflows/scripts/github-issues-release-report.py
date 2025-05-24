import requests
import re
import argparse
import datetime

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PROJECT_URL = "https://github.com/orgs/Netcracker/projects/9"
RELEASE_NAME = os.environ.get("RELEASE_NAME")

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

API_URL = "https://api.github.com/graphql"

parser = argparse.ArgumentParser()
parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
args = parser.parse_args()
VERBOSE = args.verbose

def log(msg):
    if VERBOSE:
        print(f"[Debug] {msg}")

def run_query(query, variables=None):
    response = requests.post(API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    if response.status_code != 200:
        raise Exception(f"Query failed: {response.text}")
    return response.json()

def extract_org_and_number(url):
    match = re.match(r"https://github.com/orgs/([^/]+)/projects/(\d+)", url)
    if not match:
        raise ValueError("Invalid project URL")
    return match.group(1), int(match.group(2))

def get_project_fields(org, number):
    query = """
    query($org: String!, $number: Int!) {
      organization(login: $org) {
        projectV2(number: $number) {
          id
          fields(first: 50) {
            nodes {
              __typename
              ... on ProjectV2IterationField {
                id
                name
                configuration {
                  iterations {
                    id
                    title
                    startDate
                    duration
                  }
                  completedIterations {
                    id
                    title
                    startDate
                    duration
                  }
                }
              }
              ... on ProjectV2SingleSelectField {
                id
                name
                options {
                  id
                  name
                }
              }
            }
          }
        }
      }
    }
    """
    result = run_query(query, {"org": org, "number": number})
    project = result["data"]["organization"]["projectV2"]
    project_id = project["id"]
    fields = project["fields"]["nodes"]

    sprint_field_id = None
    matched_sprints = {}
    field_options = {"Status": {}, "Priority": {}}

    for f in fields:
        if f["__typename"] == "ProjectV2IterationField" and f["name"] == "Sprint":
            sprint_field_id = f["id"]
            all_iterations = f["configuration"].get("iterations", []) + f["configuration"].get("completedIterations", [])
            for it in all_iterations:
                if RELEASE_NAME in it["title"]:
                    matched_sprints[it["id"]] = it["title"]
        if f["__typename"] == "ProjectV2SingleSelectField" and f["name"] in field_options:
            for opt in f.get("options", []):
                field_options[f["name"]][opt["id"]] = opt["name"]

    if not sprint_field_id or not matched_sprints:
        raise Exception("Matching sprints not found or sprint field missing")

    return project_id, sprint_field_id, matched_sprints, field_options

def get_issues_for_sprints(project_id, sprint_field_id, sprint_id_to_title, field_options):
    query = """
    query($projectId: ID!, $after: String) {
      node(id: $projectId) {
        ... on ProjectV2 {
          items(first: 50, after: $after) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              content {
                ... on Issue {
                  title
                  url
                  issueType {
                    name
                  }
                  assignees(first: 10) {
                    nodes { login }
                  }
                }
              }
              fieldValues(first: 30) {
                nodes {
                  __typename
                  ... on ProjectV2ItemFieldIterationValue {
                    iterationId
                  }
                  ... on ProjectV2ItemFieldSingleSelectValue {
                    optionId
                    field {
                      ... on ProjectV2SingleSelectField {
                        name
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    issues = []
    after = None
    while True:
        result = run_query(query, {"projectId": project_id, "after": after})
        items = result["data"]["node"]["items"]["nodes"]
        for item in items:
            content = item.get("content")
            if not content or content.get("title") is None:
                continue
            assignees = [u["login"] for u in content.get("assignees", {}).get("nodes", [])] or ["Unassigned"]

            status = "Empty"
            priority = "Empty"
            type_ = content.get("issueType").get("name") if content.get("issueType") else "Empty"
            matched_sprint_id = None

            for fv in item["fieldValues"]["nodes"]:
                if fv["__typename"] == "ProjectV2ItemFieldIterationValue":
                    if fv.get("iterationId") in sprint_id_to_title:
                        matched_sprint_id = fv.get("iterationId")
                if fv["__typename"] == "ProjectV2ItemFieldSingleSelectValue":
                    field_name = fv.get("field", {}).get("name")
                    option_id = fv.get("optionId")
                    if field_name in field_options:
                        value = field_options[field_name].get(option_id, option_id)
                        if field_name == "Status":
                            status = value
                        elif field_name == "Priority":
                            priority = value

            if matched_sprint_id:
                issues.append({
                    "assignee": assignees[0],
                    "name": content["title"],
                    "type": type_,
                    "priority": priority,
                    "status": status,
                    "url": content["url"],
                    "sprint": sprint_id_to_title[matched_sprint_id]
                })

        if not result["data"]["node"]["items"]["pageInfo"]["hasNextPage"]:
            break
        after = result["data"]["node"]["items"]["pageInfo"]["endCursor"]

    return issues

def generate_html_report(data, release_name):
    timestamp_display = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
    timestamp_filename = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{timestamp_filename}.html"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"""
<html>
<head>
  <meta charset='utf-8'>
  <title>GitHub Release Report - {release_name} - {timestamp_display}</title>
  <style>
    body {{ font-family: sans-serif; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 4px; text-align: left; }}
    th {{ background-color: #f2f2f2; cursor: pointer; }}
    tr:hover {{ background-color: #f1f1f1; }}
  </style>
  <script src='https://cdnjs.cloudflare.com/ajax/libs/tablesort/5.2.1/tablesort.min.js'></script>
</head>
<body>
  <h1>Release Report - {release_name} - {timestamp_display}</h1>
  <table id='reportTable'>
    <thead>
      <tr>
        <th>Assignee</th>
        <th>Name</th>
        <th>Type</th>
        <th>Priority</th>
        <th>Status</th>
        <th>Sprint Name</th>
        <th>URL</th>
      </tr>
    </thead>
    <tbody>
""")

        for issue in data:
            f.write(f"      <tr><td>{issue['assignee']}</td><td>{issue['name']}</td><td>{issue['type']}</td><td>{issue['priority']}</td><td>{issue['status']}</td><td>{issue['sprint']}</td><td><a href='{issue['url']}' target='_blank'>Link</a></td></tr>\n")

        f.write("""
    </tbody>
  </table>
  <script>new Tablesort(document.getElementById('reportTable'));</script>
</body>
</html>
""")
    print(f"Report written to {filename}")

def main():
    org, number = extract_org_and_number(PROJECT_URL)
    project_id, sprint_field_id, matched_sprints, field_options = get_project_fields(org, number)
    data = get_issues_for_sprints(project_id, sprint_field_id, matched_sprints, field_options)
    generate_html_report(data, RELEASE_NAME)

if __name__ == "__main__":
    main()
