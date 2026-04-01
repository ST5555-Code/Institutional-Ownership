# Deploying 13F Ownership Research to Render.com

## Prerequisites

- Free Render.com account (https://render.com)
- GitHub repo with the `13f.duckdb` database file
- Python 3.9+

## Local Testing

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership
pip install -r requirements.txt
python3 scripts/app.py --port 8001
```

Open http://localhost:8001.

## Deploy to Render.com (Free Tier)

### Step 1: Push to GitHub

```bash
cd ~/ClaudeWorkspace/Projects/13f-ownership

# Track large database file with Git LFS
git lfs install
git lfs track "*.duckdb"

git add .
git commit -m "13F Ownership Research web app"
git remote add origin https://github.com/YOUR_USERNAME/13f-ownership.git
git push -u origin main
```

### Step 2: Create Web Service on Render

1. Go to https://dashboard.render.com
2. Click **New** > **Web Service**
3. Connect your GitHub repo
4. Render will auto-detect `render.yaml`. Settings:
   - **Name**: 13f-ownership
   - **Region**: closest to you
   - **Branch**: main
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python scripts/app.py --port $PORT`
   - **Instance Type**: Free
5. Click **Create Web Service**

Your app will be at: `https://13f-ownership.onrender.com`

### Step 3: Access from Phone

Open the Render URL in your phone browser. The app is responsive.

## Updating Data

1. Rebuild `data/13f.duckdb` locally with `python3 scripts/update.py`
2. Commit and push the updated database
3. Render auto-deploys on push

## Troubleshooting

- **Timeout on free tier**: Free instances spin down after 15 min of inactivity.
  First request after idle takes ~30 sec to cold-start.
- **Memory errors**: Free tier has 512 MB RAM. If queries time out, consider
  filtering to latest quarter only.
- **DuckDB version mismatch**: Ensure the same DuckDB version is used locally
  and in requirements.txt.
