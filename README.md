# qubership-apihub-ci

This repository hosts reusable GitHub Actions workflows designed for CI/CD pipelines in the QUbership APIHUB application and its related components. These workflows provide standardized, automated processes for building, testing, and deploying services, ensuring consistency and efficiency across the project.

Additionally, many Qubership APIHUB repositories leverage shared workflows from qubership-workflow-hub, which offers a centralized collection of CI/CD templates and best practices. Using both repositories helps reduce code duplication, enforce DevOps standards, and streamline development processes.

By integrating these workflows, teams can maintain reliable and scalable automation while adhering to unified deployment practices across the QUbership ecosystem.

## Agent skills (APM)

Central store of agent skills and instruction rules for APIHub repositories, distributed via
[APM](https://microsoft.github.io/apm/). See
[`agent-skills/README.md`](agent-skills/README.md) for the catalog and consumption guide.

Also this repository contains some workflows with custom pyton scripts which generates various reports helpful for project management purposes:

- Epics per release report
- Current sprint stories report
- Pull Requests opened in all Qubership-APIHUB repositories (available on GitHub Pages: [report_prs_latest.html](https://netcracker.github.io/qubership-apihub-ci/report_prs_latest.html))
