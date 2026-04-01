# Deploying 13-F Ownership Research to Render.com

## Prerequisites
- A free Render.com account (https://render.com)
- The `13f.duckdb` database file built by the scripts
- Datasette installed (`pip install datasette datasette-duckdb`)

## Local Testing

Test locally before deploying:

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership

# Start Datasette locally
datasette data/13f.duckdb \
  --metadata web/datasette_config.yaml \
  --port 8001 \
  --setting sql_time_limit_ms 10000
```

Open http://localhost:8001 in your browser.

## Deploy to Render.com (Free Tier)

### Step 1: Create a Dockerfile

Create `web/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
RUN pip install datasette datasette-duckdb

COPY data/13f.duckdb /app/data/13f.duckdb
COPY web/datasette_config.yaml /app/metadata.yaml

EXPOSE 8001

CMD ["datasette", "serve", "/app/data/13f.duckdb", \
     "--metadata", "/app/metadata.yaml", \
     "--host", "0.0.0.0", "--port", "8001", \
     "--setting", "sql_time_limit_ms", "10000", \
     "--cors"]
```

### Step 2: Push to GitHub

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
git init
git add web/Dockerfile web/datasette_config.yaml data/13f.duckdb
git commit -m "13-F Ownership Database for Render deployment"
git remote add origin https://github.com/YOUR_USERNAME/13f-ownership.git
git push -u origin main
```

Note: The DuckDB file is large (~500 MB+). Consider using Git LFS:
```bash
git lfs install
git lfs track "*.duckdb"
```

### Step 3: Deploy on Render

1. Go to https://dashboard.render.com
2. Click **New** → **Web Service**
3. Connect your GitHub repo
4. Settings:
   - **Name**: 13f-ownership
   - **Region**: Pick closest to you
   - **Branch**: main
   - **Runtime**: Docker
   - **Instance Type**: Free
5. Click **Create Web Service**

Render will build and deploy. Your dashboard will be at:
`https://13f-ownership.onrender.com`

### Step 4: Access from Phone

Open the Render URL in your phone browser. Datasette is mobile-responsive.

Bookmark the named queries for quick access:
- `/13f/shareholder-register?ticker=AR`
- `/13f/ownership-change?ticker=AR`
- `/13f/active-holders?ticker=AR`

## Updating Data

When new 13F data is available:

1. Run the scripts locally to rebuild the DuckDB file
2. Copy the updated `data/13f.duckdb` to the repo
3. Push to GitHub — Render auto-deploys

## Alternative: Fly.io

If Render free tier is too slow:

```bash
# Install flyctl
brew install flyctl

# Create fly.toml in project root
flyctl launch --name 13f-ownership

# Deploy
flyctl deploy
```

## Troubleshooting

- **Timeout errors**: Increase `sql_time_limit_ms` in the CMD
- **Memory errors**: The free tier has limited RAM. Consider filtering
  to Q4 2025 only for a smaller database
- **DuckDB version mismatch**: Ensure the same DuckDB version is used
  locally and in the Docker image
