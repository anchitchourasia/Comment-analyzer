# Complete Docker Deployment Plan for Comment-Analyzer

This document provides a comprehensive, step-by-step blueprint for deploying the **Comment-Analyzer** full-stack application (FastAPI Backend + Angular Frontend) using **Docker and Docker Compose** on a Linux server (VPS).

---

## 🏗️ Architecture Overview

```
[ User Browser (Internet) ]
           │
           │ (HTTP Port 80 / HTTPS Port 443)
           ▼
┌─────────────────────────────────────────────────────────────┐
│ VPS Host Machine                                            │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ Docker Container: frontend (Nginx)                  │   │
│   │   - Serves Angular static files                      │   │
│   │   - Proxies `/api/*` to `http://backend:8000/api/` │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │ Internal Docker Network      │
│                              ▼                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ Docker Container: backend (FastAPI / Uvicorn)       │   │
│   │   - Handles API endpoints & Live Chat polling       │   │
│   │   - Persists state to `./data` volume               │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │                              │
└──────────────────────────────┼──────────────────────────────┘
                               ▼
            ┌────────────────────────────────────┐
            │ Host Directory: ./data             │
            │ (OAuth tokens, Q&A records, logs)  │
            └────────────────────────────────────┘
```

---

## 📁 Phase 1: Local Docker Files Setup

Create the following files in your project repository before pushing to GitHub.

### 1. `Dockerfile.backend` (Project Root)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose backend port
EXPOSE 8000

# Start Uvicorn single-instance server
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2. `frontend/nginx.conf` (Inside `frontend/` directory)
```nginx
server {
    listen 80;
    server_name _;

    # Serve Angular Static Files
    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # Reverse Proxy API requests to Backend container
    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. `frontend/Dockerfile` (Inside `frontend/` directory)
```dockerfile
# Stage 1: Build Angular static bundle
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build -- --configuration production

# Stage 2: Serve via Nginx
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### 4. `docker-compose.yml` (Project Root)
```yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    container_name: comment_analyzer_backend
    restart: always
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    ports:
      - "8000:8000"

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: comment_analyzer_frontend
    restart: always
    ports:
      - "80:80"
    depends_on:
      - backend
```

### 5. Update Angular API Base URL
In `frontend/src/environments/environment.ts`:
```typescript
export const environment = {
  production: true,
  apiUrl: '', // Uses relative paths (/api) handled by Nginx proxy
};
```

Commit & push to GitHub:
```bash
git add .
git commit -m "Add Docker and Nginx deployment files"
git push origin main
```

---

## 🖥️ Phase 2: VPS Server Setup

1. **Rent a Linux VPS** (DigitalOcean Droplet, Hetzner, AWS EC2, or Linode) running Ubuntu 22.04 / 24.04 LTS.
2. **Connect via SSH**:
   ```bash
   ssh root@YOUR_SERVER_IP
   ```
3. **Install Docker & Docker Compose**:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y docker.io docker-compose-v2 git
   sudo systemctl enable --now docker
   ```

---

## 🚀 Phase 3: Project Deployment

1. **Clone your GitHub Repository**:
   ```bash
   cd /opt
   git clone https://github.com/YOUR_USERNAME/Comment-analyzer.git
   cd Comment-analyzer
   ```

2. **Create the Production `.env` File**:
   ```bash
   nano .env
   ```
   Paste environment variables:
   ```env
   GROQ_API_KEY=your_actual_groq_key
   ENCRYPTION_KEY=your_actual_fernet_key
   GOOGLE_CLIENT_ID=your_google_client_id
   GOOGLE_CLIENT_SECRET=your_google_client_secret
   REDIRECT_URI=http://YOUR_SERVER_IP/api/v1/auth/google/callback
   SECRET_KEY=your_random_secret_key
   ```
   *(Press `Ctrl+O` then `Enter` to save, `Ctrl+X` to exit)*.

3. **Build and Launch Containers**:
   ```bash
   docker compose up -d --build
   ```

4. **Verify Container Status**:
   ```bash
   docker compose ps
   ```

---

## 🔒 Phase 4: Domain & Free SSL Setup (HTTPS)

1. **DNS A Record**: Point `yourdomain.com` to `YOUR_SERVER_IP` in your DNS settings.
2. **Install Certbot**:
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   ```
3. **Run Certbot**:
   ```bash
   sudo certbot --nginx -d yourdomain.com
   ```

---

## 🔑 Phase 5: Google Cloud Console OAuth Configuration

1. Go to [Google Cloud Console Credentials](https://console.cloud.google.com/apis/credentials).
2. Edit your OAuth 2.0 Client ID:
   - **Authorized JavaScript origins**: `https://yourdomain.com` (or `http://YOUR_SERVER_IP`)
   - **Authorized redirect URIs**: `https://yourdomain.com/api/v1/auth/google/callback` (or `http://YOUR_SERVER_IP/api/v1/auth/google/callback`)
3. Save changes.

---

## 🛠️ Phase 6: Maintenance & Logging Commands

| Operation | Command |
| :--- | :--- |
| Check running containers | `docker compose ps` |
| View live logs | `docker compose logs -f` |
| View backend logs only | `docker compose logs -f backend` |
| Restart containers | `docker compose restart` |
| Pull updates & rebuild | `git pull && docker compose up -d --build` |
| Stop application | `docker compose down` |
