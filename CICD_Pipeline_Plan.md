# Complete CI/CD Pipeline Plan for Comment-Analyzer

This document provides a complete blueprint for setting up an automated **CI/CD Pipeline** using **GitHub Actions** to automatically test, build, and deploy the **Comment-Analyzer** project to your VPS whenever code is pushed to the `main` branch.

---

## 🔄 CI/CD Pipeline Workflow Diagram

```
[ Developer ] ──► git push origin main
                        │
                        ▼
            ┌───────────────────────┐
            │    GitHub Actions     │
            └───────────┬───────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
┌───────────────┐               ┌───────────────┐
│ Job 1: Test   │               │ Job 2: Test   │
│ Backend       │               │ Frontend      │
│ (Python/FastAPI)              │ (Node/Angular)│
└───────┬───────┘               └───────┬───────┘
        │                               │
        └───────────────┬───────────────┘
                        ▼ (On Success)
            ┌───────────────────────┐
            │ Job 3: CD Deploy      │
            │ Connect via SSH       │
            └───────────┬───────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │ VPS Host Server       │
            │ 1. git pull           │
            │ 2. docker compose up  │
            │ 3. Health Check       │
            └───────────────────────┘
```

---

## 🔑 Phase 1: Configure GitHub Secrets

To allow GitHub Actions to securely access your VPS, add SSH credentials to your GitHub Repository:

1. Go to your GitHub repository: **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**.
2. Click **New repository secret** and add the following 4 secrets:

| Secret Name | Description | Example Value |
| :--- | :--- | :--- |
| `SSH_HOST` | Server IP address or domain | `192.0.2.1` or `app.yourdomain.com` |
| `SSH_USER` | Server SSH username | `root` or `ubuntu` |
| `SSH_KEY` | Private SSH key (`~/.ssh/id_rsa`) | `-----BEGIN OPENSSH PRIVATE KEY----- ...` |
| `SSH_PORT` | SSH Port (default is 22) | `22` |

---

## 🛠️ Phase 2: Create GitHub Actions Workflow File

Create `.github/workflows/deploy.yml` in your repository:

```yaml
name: CI/CD Pipeline - Test & Deploy

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

jobs:
  # -------------------------------------------------------------
  # Job 1: Backend CI (Test Python FastAPI)
  # -------------------------------------------------------------
  test-backend:
    name: 🐍 Test FastAPI Backend
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Backend Tests
        run: |
          python -m unittest discover -s . -p "test_*.py"

  # -------------------------------------------------------------
  # Job 2: Frontend CI (Build & Lint Angular)
  # -------------------------------------------------------------
  test-frontend:
    name: 🅰️ Build & Test Angular Frontend
    runs-on: ubuntu-latest

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Node.js 20
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install Frontend Dependencies
        run: |
          cd frontend
          npm ci

      - name: Build Angular Frontend
        run: |
          cd frontend
          npm run build -- --configuration production

  # -------------------------------------------------------------
  # Job 3: Automated CD Deployment to VPS
  # -------------------------------------------------------------
  deploy:
    name: 🚀 Deploy to Docker VPS
    needs: [test-backend, test-frontend]
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest

    steps:
      - name: Execute Remote SSH Commands
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.SSH_HOST }}
          username: ${{ secrets.SSH_USER }}
          key: ${{ secrets.SSH_KEY }}
          port: ${{ secrets.SSH_PORT }}
          script: |
            set -e
            echo "1. Navigating to project directory..."
            cd /opt/Comment-analyzer

            echo "2. Pulling latest changes from GitHub..."
            git pull origin main

            echo "3. Rebuilding & restarting Docker containers..."
            docker compose up -d --build --remove-orphans

            echo "4. Cleaning up unused Docker images..."
            docker image prune -f

            echo "5. Verifying container health..."
            docker compose ps
```

---

## 🚀 Phase 3: How the Automated Pipeline Executes

1. **You push code**:
   ```bash
   git add .
   git commit -m "Feature: Updated Q&A engine logic"
   git push origin main
   ```
2. **GitHub Actions automatically triggers**:
   - Runs Python unit tests (`test_*.py`).
   - Compiles Angular frontend assets (`npm run build`).
3. **If tests pass**, GitHub Actions SSHs into your server:
   - Executes `git pull origin main`.
   - Runs `docker compose up -d --build`.
   - Prunes stale Docker layers to save disk space.
4. **Zero-Downtime Handover**: Docker Compose builds the new image in the background and only swaps the container once the build completes successfully!

---

## 🔒 Best Practices & Security

- **SSH Key Pair**: Generate a dedicated SSH key pair on your VPS specifically for deployment:
  ```bash
  ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy -N ""
  cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
  ```
  Copy the contents of `~/.ssh/github_deploy` into the GitHub Secret `SSH_KEY`.
- **Environment Secrets**: Keep your production `.env` file on the VPS (`/opt/Comment-analyzer/.env`). It will remain intact across `git pull` updates and won't be overwritten.
