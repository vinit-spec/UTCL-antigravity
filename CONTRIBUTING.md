# Contributing Guidelines

Thank you for considering contributing to the **UTCL Transit Management System**! We welcome bug reports, feature proposals, and code contributions.

---

## 🛠️ How to Contribute

1. **Fork the Repository**: Create your own fork of the project.
2. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/amazing-new-feature
   ```
3. **Make Your Changes**: Follow existing code style conventions and architecture patterns.
4. **Run Verification Scripts**:
   ```bash
   python verify_multi_plant_criteria.py
   ```
5. **Commit Your Changes**: Keep commit messages concise, descriptive, and clear:
   ```bash
   git commit -m "feat(auth): add rate limiting on password reset endpoint"
   ```
6. **Push to Your Branch**:
   ```bash
   git push origin feature/amazing-new-feature
   ```
7. **Open a Pull Request**: Submit a PR to the `main` branch using our PR template.

---

## 🔒 Security Requirements

- **Never Commit Secrets**: Ensure no credentials, API keys, passwords, or production database strings are committed in your PR.
- Use `.env` or environment variables for all sensitive configuration parameters.
- Verify that your changes do not introduce OWASP Top 10 vulnerabilities (XSS, SQL Injection, CSRF, insecure direct object references).

---

## 🐞 Reporting Bugs

- Search existing issues to ensure the bug hasn't already been reported.
- Open a new issue using the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md).
- Include steps to reproduce, expected vs actual behavior, and relevant environment details.
