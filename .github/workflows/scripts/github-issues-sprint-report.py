import requests
import re
import os
import argparse
import datetime
from collections import defaultdict

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PROJECT_URL = "https://github.com/orgs/Netcracker/projects/9"
SPRINT_FIELD_NAME = "Sprint"

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
    sprint_iterations = {}
    current_sprint_id = None
    field_options = {"Status": {}, "Priority": {}}

    now = datetime.datetime.utcnow().date()

    for f in fields:
        if f["__typename"] == "ProjectV2IterationField" and f["name"] == SPRINT_FIELD_NAME:
            sprint_field_id = f["id"]
            all_iterations = f["configuration"].get("iterations", []) + f["configuration"].get("completedIterations", [])
            for it in all_iterations:
                sprint_iterations[it["title"]] = it["id"]
                start_date = datetime.datetime.strptime(it["startDate"], "%Y-%m-%d").date()
                duration = it["duration"]
                end_date = start_date + datetime.timedelta(days=duration)
                if start_date <= now < end_date:
                    current_sprint_id = it["id"]
        if f["__typename"] == "ProjectV2SingleSelectField" and f["name"] in field_options:
            for opt in f.get("options", []):
                field_options[f["name"]][opt["id"]] = opt["name"]

    if not sprint_field_id or not current_sprint_id:
        raise Exception("Current sprint not found or sprint field missing")

    return project_id, sprint_field_id, current_sprint_id, sprint_iterations, field_options

def get_issues_by_assignee(project_id, sprint_field_id, sprint_id, field_options):
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
            belongs_to_sprint = False

            for fv in item["fieldValues"]["nodes"]:
                if fv["__typename"] == "ProjectV2ItemFieldIterationValue" and fv.get("iterationId") == sprint_id:
                    belongs_to_sprint = True
                if fv["__typename"] == "ProjectV2ItemFieldSingleSelectValue":
                    field_name = fv.get("field", {}).get("name")
                    option_id = fv.get("optionId")
                    if field_name in field_options:
                        value = field_options[field_name].get(option_id, option_id)
                        if field_name == "Status":
                            status = value
                        elif field_name == "Priority":
                            priority = value

            if belongs_to_sprint:
                for a in assignees:
                    issues.append({
                        "assignee": a,
                        "name": content["title"],
                        "type": type_,
                        "priority": priority,
                        "status": status,
                        "url": content["url"]
                    })

        if not result["data"]["node"]["items"]["pageInfo"]["hasNextPage"]:
            break
        after = result["data"]["node"]["items"]["pageInfo"]["endCursor"]

    return sorted(issues, key=lambda x: (x["assignee"] == "Unassigned", x["assignee"]))

def generate_html_report(data, sprint_name):
    assignee_map = {
        "alagishev": "Aleksandr Agishev",
        "b41ex": "Alexey Bochencev",
        "iurii-golovinskii": "Iurii Golovinskii",
        "makeev-pavel": "Pavel Makeev",
        "JayLim2": "Sergei Komarov",
        "viacheslav-lunev": "Viacheslav Lunev",
        "karpov-aleksandr": "Aleksandr V. Karpov",
        "CountRedClaw": "Ilia Borsuk",
        "AndreiChek": "Andrei Chekalin",
        "Roman-cod": "Roman Babenko",
        "raa1618033": "Alexey Rodionov",
        "tiutiunnyk-ivan": "Ivan Tiutiunnyk",
        "Maryna-Ko": "Maryna Kovalenko",
        "iugaidiana": "Diana Iugai",
        "vOrigins": "Vladyslav Novikov",
        "tanabebr": "Felipe Tanabe",
        "zloiadil": "Adil Bektursunov",
        "nilesh25890": "Nilesh Ashokrao Shinde",
        "oommenmathewpanicker": "Oommen Mathew Panicker",
        "TODO": "TODO",
        "divy-netcracker": "Divy Tripathy"
    }
    timestamp_display = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
    timestamp_filename = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"report_{timestamp_filename}.html"
    assignee_colors = {}
    color_palette = ["#f0f8ff", "#f5f5dc", "#f0fff0", "#fffaf0", "#fdf5e6", "#f5fffa", "#fffff0", "#f0ffff"]

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"<html><head><meta charset='utf-8'><title>GitHub Sprint Report - {sprint_name} - {timestamp_display}</title>")
        f.write("<style>\n")
        f.write("body { font-family: sans-serif; }\n")
        f.write("table { border-collapse: collapse; width: 100%; }\n")
        f.write("th, td { border: 1px solid #ccc; padding: 4px; text-align: left; }\n")
        f.write("th { background-color: #f2f2f2; cursor: pointer; }\n")
        f.write("tr:hover { background-color: #f1f1f1; }\n")
        f.write("</style>\n")
        f.write("<script src='https://cdnjs.cloudflare.com/ajax/libs/tablesort/5.2.1/tablesort.min.js'></script>\n")
        f.write("<script src='https://code.jquery.com/jquery-3.6.0.min.js'></script>\n")
        f.write("<script>\n")
        f.write("$(document).ready(function(){\n")
        f.write("  $('table').each(function() { new Tablesort(this); });\n")
        f.write("  $('#filterInput').on('keyup', function() {\n")
        f.write("    var value = $(this).val().toLowerCase();\n")
        f.write("    $('table tbody tr').filter(function() {\n")
        f.write("      $(this).toggle($(this).text().toLowerCase().indexOf(value) > -1)\n")
        f.write("    });\n")
        f.write("  });\n")
        f.write("});\n")
        f.write("</script>\n")
        f.write("</head><body>\n")
        f.write(f"<h1>Sprint Report - {sprint_name} - {timestamp_display}</h1>\n")
        f.write("<input type='text' id='filterInput' placeholder='Filter table...' style='margin-bottom:10px;width:300px;padding:5px;'>\n")
        f.write("""
<table id='reportTable'>
<thead>
<tr>
<th>Assignee &#x25B2;&#x25BC;</th>
<th>Name &#x25B2;&#x25BC;</th>
<th>Type &#x25B2;&#x25BC;</th>
<th>Priority &#x25B2;&#x25BC;</th>
<th>Status &#x25B2;&#x25BC;</th>
<th>URL</th>
</tr>
</thead>
<tbody>
""")
        for issue in data:
            assignee = issue['assignee']
            display_name = f"{assignee_map[assignee]} ({assignee})" if assignee in assignee_map else assignee
            if assignee not in assignee_colors:
                assignee_colors[assignee] = color_palette[len(assignee_colors) % len(color_palette)]
            color = assignee_colors[assignee]
            f.write(f"<tr style='background-color:{color};'>")
            f.write(f"<td>{display_name}</td><td>{issue['name']}</td><td>{issue['type']}</td><td>{issue['priority']}</td><td>{issue['status']}</td><td><a href='{issue['url']}' target='_blank'>Link</a></td>")
            f.write("</tr>\n")

        f.write("</tbody></table>\n")
        f.write("</body></html>\n")

    print(f"Report written to {filename}")



def main():
    org, number = extract_org_and_number(PROJECT_URL)
    project_id, sprint_field_id, current_sprint_id, sprint_iterations, field_options = get_project_fields(org, number)
    sprint_name = next(name for name, sid in sprint_iterations.items() if sid == current_sprint_id)
    data = get_issues_by_assignee(project_id, sprint_field_id, current_sprint_id, field_options)
    generate_html_report(data, sprint_name)

if __name__ == "__main__":
    main()
