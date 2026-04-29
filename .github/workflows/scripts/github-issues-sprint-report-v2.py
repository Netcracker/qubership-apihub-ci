import requests
import re
import os
import argparse
import datetime
from collections import defaultdict

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
PROJECT_URL = "https://github.com/orgs/Netcracker/projects/9"
SPRINT_FIELD_NAME = "Sprint"
ESTIMATE_FIELD_NAME = "Estimate, md"
TIME_SPENT_FIELD_NAME = "Time spent, md"

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
    payload = response.json()
    if payload.get("errors"):
        msgs = "; ".join(err.get("message", str(err)) for err in payload["errors"])
        raise Exception(f"GraphQL errors: {msgs}")
    if "data" not in payload:
        raise Exception(f"Unexpected GraphQL response (no data): {payload}")
    return payload

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
                  ... on ProjectV2IterationFieldConfiguration {
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
              }
              ... on ProjectV2SingleSelectField {
                id
                name
                options {
                  id
                  name
                }
              }
              ... on ProjectV2Field {
                id
                name
                dataType
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
    numeric_fields = {}

    now = datetime.datetime.utcnow().date()

    for f in fields:
        if f["__typename"] == "ProjectV2IterationField" and f["name"] == SPRINT_FIELD_NAME:
            sprint_field_id = f["id"]
            cfg = f.get("configuration") or {}
            all_iterations = cfg.get("iterations", []) + cfg.get("completedIterations", [])
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
        if f["__typename"] == "ProjectV2Field" and f.get("dataType") == "NUMBER":
            if f["name"] == ESTIMATE_FIELD_NAME:
                numeric_fields["estimate"] = f["id"]
            elif f["name"] == TIME_SPENT_FIELD_NAME:
                numeric_fields["time_spent"] = f["id"]

    if not sprint_field_id or not current_sprint_id:
        raise Exception("Current sprint not found or sprint field missing")

    return project_id, sprint_field_id, current_sprint_id, sprint_iterations, field_options, numeric_fields

def get_issues_by_assignee(project_id, sprint_field_id, sprint_id, field_options, numeric_fields):
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
                  ... on ProjectV2ItemFieldNumberValue {
                    number
                    field {
                      ... on ProjectV2Field {
                        id
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
            estimate = ""
            time_spent = ""

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
                if fv["__typename"] == "ProjectV2ItemFieldNumberValue":
                    field_id = fv.get("field", {}).get("id")
                    number_value = fv.get("number")
                    if field_id == numeric_fields.get("estimate"):
                        estimate = number_value
                    elif field_id == numeric_fields.get("time_spent"):
                        time_spent = number_value

            if belongs_to_sprint:
                for a in assignees:
                    issues.append({
                        "assignee": a,
                        "name": content["title"],
                        "type": type_,
                        "priority": priority,
                        "status": status,
                        "url": content["url"],
                        "estimate": estimate,
                        "time_spent": time_spent
                    })

        if not result["data"]["node"]["items"]["pageInfo"]["hasNextPage"]:
            break
        after = result["data"]["node"]["items"]["pageInfo"]["endCursor"]

    return sorted(issues, key=lambda x: (x["assignee"] == "Unassigned", x["assignee"]))

assignee_map = {
    "alagishev": {"name": "Aleksandr Agishev", "team": "BE"},
    "b41ex": {"name": "Alexey Bochencev", "team": "FE"},
    "iurii-golovinskii": {"name": "Iurii Golovinskii", "team": "FE"},
    "makeev-pavel": {"name": "Pavel Makeev", "team": "FE"},
    "JayLim2": {"name": "Sergei Komarov", "team": "FE"},
    "viacheslav-lunev": {"name": "Viacheslav Lunev", "team": "BE"},
    "karpov-aleksandr": {"name": "Aleksandr V. Karpov", "team": "BE"},
    "AndreiChek": {"name": "Andrei Chekalin", "team": None},
    "Roman-cod": {"name": "Roman Babenko", "team": None},
    "Maryna-Ko": {"name": "Maryna Kovalenko", "team": None},
    "ArtemNalesnikovskyi": {"name": "Artem Nalesnikovskyi", "team": None},
    "vOrigins": {"name": "Vladyslav Novikov", "team": "FE"},
    "tanabebr": {"name": "Felipe Tanabe", "team": None},
    "zloiadil": {"name": "Adil Bektursunov", "team": None},
    "oommenmathewpanicker": {"name": "Oommen Mathew Panicker", "team": None},
    "sujithn-nc": {"name": "Sujith N", "team": "BE"},
    "TODO": {"name": "TODO", "team": None}
}

def determine_team(issue_name, assignee_login):
    if "[FE]" in issue_name:
        return "FE"
    if "[BE]" in issue_name:
        return "BE"
    info = assignee_map.get(assignee_login)
    if info and info.get("team"):
        return info["team"]
    return "Not Defined"

def generate_html_report(data, sprint_name):
    timestamp_display = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
    timestamp_filename = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_sprint_{sprint_name}_{timestamp_filename}.html"

    team_totals = defaultdict(lambda: {"estimate": 0, "time_spent": 0})

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"""
<html>
<head>
  <meta charset='utf-8'>
  <title>GitHub Sprint Report - {sprint_name} - {timestamp_display}</title>
  <style>
    body {{ font-family: sans-serif; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 4px; text-align: left; }}
    th {{ background-color: #f2f2f2; cursor: pointer; }}
    tr:hover {{ background-color: #f1f1f1; }}
    .numeric {{ text-align: right; mso-number-format:'\\@'; }}
    h2 {{ margin-top: 40px; }}
    .summary-table {{ width: auto; }}
    .summary-table td, .summary-table th {{ padding: 6px 16px; }}
  </style>
  <script src='https://cdnjs.cloudflare.com/ajax/libs/tablesort/5.2.1/tablesort.min.js'></script>
  <script src='https://code.jquery.com/jquery-3.6.0.min.js'></script>
</head>
<body>
  <h1>Sprint Report - {sprint_name} - {timestamp_display}</h1>
  <input type='text' id='filterInput' placeholder='Filter table...' style='margin-bottom:10px;width:300px;padding:5px;'>
  <table id='reportTable'>
    <thead>
      <tr>
        <th>Assignee &#x25B2;&#x25BC;</th>
        <th>Name &#x25B2;&#x25BC;</th>
        <th>Team &#x25B2;&#x25BC;</th>
        <th>Type &#x25B2;&#x25BC;</th>
        <th>Priority &#x25B2;&#x25BC;</th>
        <th>Status &#x25B2;&#x25BC;</th>
        <th>Estimate, md &#x25B2;&#x25BC;</th>
        <th>Time Spent, md &#x25B2;&#x25BC;</th>
        <th>URL</th>
      </tr>
    </thead>
    <tbody>
""")

        assignee_colors = {}
        color_palette = ["#f0f8ff", "#f5f5dc", "#f0fff0", "#fffaf0", "#fdf5e6", "#f5fffa", "#fffff0", "#f0ffff"]

        for issue in data:
            assignee = issue['assignee']
            display_name = f"{assignee_map[assignee]['name']} ({assignee})" if assignee in assignee_map else assignee
            if assignee not in assignee_colors:
                assignee_colors[assignee] = color_palette[len(assignee_colors) % len(color_palette)]
            color = assignee_colors[assignee]

            team = determine_team(issue['name'], assignee)

            estimate_val = issue['estimate'] if issue['estimate'] not in (None, "") else 0
            time_spent_val = issue['time_spent'] if issue['time_spent'] not in (None, "") else 0
            team_totals[team]["estimate"] += estimate_val
            team_totals[team]["time_spent"] += time_spent_val

            estimate_display = f"\u200B{issue['estimate']}" if issue['estimate'] not in (None, "") else ""
            time_spent_display = f"\u200B{issue['time_spent']}" if issue['time_spent'] not in (None, "") else ""

            f.write(f"      <tr style='background-color:{color};'>")
            f.write(f"        <td>{display_name}</td>")
            f.write(f"        <td>{issue['name']}</td>")
            f.write(f"        <td>{team}</td>")
            f.write(f"        <td>{issue['type']}</td>")
            f.write(f"        <td>{issue['priority']}</td>")
            f.write(f"        <td>{issue['status']}</td>")
            estimate_missing = issue['type'] in ("Task", "Feature") and issue['estimate'] in (None, "")
            estimate_style = " style='background-color:#ffcccc;'" if estimate_missing else ""
            f.write(f"        <td class='numeric'{estimate_style}>{estimate_display}</td>")
            f.write(f"        <td class='numeric'>{time_spent_display}</td>")
            f.write(f"        <td><a href='{issue['url']}' target='_blank'>Link</a></td>")
            f.write("      </tr>")

        f.write("""
    </tbody>
  </table>
""")

        f.write("""
  <h2>Team Summary</h2>
  <table class='summary-table' id='summaryTable'>
    <thead>
      <tr>
        <th>Team</th>
        <th>Estimate sum</th>
        <th>Time Spent sum</th>
        <th>Delta</th>
      </tr>
    </thead>
    <tbody>
""")
        total_estimate = 0
        total_time_spent = 0
        for team_name in sorted(team_totals.keys()):
            t = team_totals[team_name]
            delta = t["estimate"] - t["time_spent"]
            total_estimate += t["estimate"]
            total_time_spent += t["time_spent"]
            est_str = f"{t['estimate']:.1f}" if t['estimate'] != int(t['estimate']) else str(int(t['estimate']))
            ts_str = f"{t['time_spent']:.1f}" if t['time_spent'] != int(t['time_spent']) else str(int(t['time_spent']))
            delta_str = f"{delta:.1f}" if delta != int(delta) else str(int(delta))
            f.write(f"      <tr><td>{team_name}</td><td class='numeric'>{est_str}</td><td class='numeric'>{ts_str}</td><td class='numeric'>{delta_str}</td></tr>\n")

        total_delta = total_estimate - total_time_spent
        te_str = f"{total_estimate:.1f}" if total_estimate != int(total_estimate) else str(int(total_estimate))
        tts_str = f"{total_time_spent:.1f}" if total_time_spent != int(total_time_spent) else str(int(total_time_spent))
        td_str = f"{total_delta:.1f}" if total_delta != int(total_delta) else str(int(total_delta))
        f.write(f"      <tr style='font-weight:bold;'><td>Sum by all teams</td><td class='numeric'>{te_str}</td><td class='numeric'>{tts_str}</td><td class='numeric'>{td_str}</td></tr>\n")

        f.write("""
    </tbody>
  </table>

  <script>
    $(document).ready(function() {{
      $('table').each(function() {{ new Tablesort(this); }});
      $('#filterInput').on('keyup', function() {{
        var value = $(this).val().toLowerCase();
        $('#reportTable tbody tr').each(function() {{
          var row = $(this);
          row.toggle(row.text().toLowerCase().indexOf(value) > -1);
        }});
      }});
    }});
  </script>
</body>
</html>
""")
    print(f"Report written to {filename}")

def main():
    org, number = extract_org_and_number(PROJECT_URL)
    project_id, sprint_field_id, current_sprint_id, sprint_iterations, field_options, numeric_fields = get_project_fields(org, number)
    sprint_name = next(name for name, sid in sprint_iterations.items() if sid == current_sprint_id)
    data = get_issues_by_assignee(project_id, sprint_field_id, current_sprint_id, field_options, numeric_fields)
    generate_html_report(data, sprint_name)

if __name__ == "__main__":
    main()
