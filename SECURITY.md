# Security Policy

## 🛡️ Supported Versions

We recommend always running the latest code on the `main` branch.

| Version | Supported          |
| ------- | ------------------ |
| Main (`main`) | yes |

---

## 🔒 Reporting a Vulnerability

If you discover a potential security vulnerability in this repository, **do not open a public issue**. Instead, please follow responsible disclosure practices:

1. **Email Notification**: Send details of the vulnerability to the project maintainers.
2. **Details to Include**:
   - Description of the vulnerability and potential impact.
   - Step-by-step instructions or proof-of-concept script to reproduce.
   - Any suggested remediations or mitigations.
3. **Response Time**: We will acknowledge receipt of your vulnerability report within **48 hours** and provide periodic updates until the patch is released.

---

## 🔑 Secret & Key Management Policy

- No API keys, passwords, private keys, database credentials, or secret tokens should ever be committed to git version control.
- Configuration templates (`.env.example`, `db_config.json.example`) must only contain non-sensitive sample placeholders.
