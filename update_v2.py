# SCOS 2.0 Daily Update & Deployment Script
# Location: C:\Users\User\Downloads\scos-v2\update_v2.py

import os
import subprocess
import sys

PWA_REPO_PATH = r"C:\Users\User\Downloads\pwa-push"
V2_REPO_PATH = r"C:\Users\User\Downloads\scos-v2"

def run_command(cmd, cwd):
    print(f"Running: {cmd} in {cwd}")
    result = subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Error executing command: {cmd}")
        print(result.stderr)
        return False, result.stdout, result.stderr
    return True, result.stdout, result.stderr

def main():
    print("=========================================")
    print("SCOS 2.0 DAILY PIPELINE RUNNER")
    print("=========================================\n")

    # 1. Pull latest raw sales data from pwa-push fallback repo
    print("Step 1: Pulling latest raw data from fallback pwa-push repo...")
    success, stdout, stderr = run_command("git pull", PWA_REPO_PATH)
    if not success:
        print("Warning: Could not pull latest changes from pwa-push. Proceeding with local raw files...")
    else:
        print("Success: Raw data repository updated.")

    # 2. Run the SCOS 2.0 data pipeline
    print("\nStep 2: Initializing SCOS 2.0 Database Core...")
    success, _, _ = run_command(f'"{sys.executable}" pipeline\\database.py', V2_REPO_PATH)
    if not success:
        print("Fatal error initializing database. Pipeline aborted.")
        sys.exit(1)

    print("\nStep 3: Compiling Authoritative Catalog from Excel master...")
    success, _, _ = run_command(f'"{sys.executable}" pipeline\\build_catalog.py', V2_REPO_PATH)
    if not success:
        print("Fatal error compiling catalog. Pipeline aborted.")
        sys.exit(1)

    print("\nStep 4: Ingesting Amazon & Flipkart sales data...")
    success, _, _ = run_command(f'"{sys.executable}" pipeline\\ingest_data.py', V2_REPO_PATH)
    if not success:
        print("Fatal error ingesting daily sales data. Pipeline aborted.")
        sys.exit(1)

    print("\nStep 5: Pre-aggregating metrics at all levels...")
    success, _, _ = run_command(f'"{sys.executable}" pipeline\\build_metrics.py', V2_REPO_PATH)
    if not success:
        print("Fatal error building metrics. Pipeline aborted.")
        sys.exit(1)

    print("\nStep 6: Running Revenue Coverage Auditor...")
    success, stdout, _ = run_command(f'"{sys.executable}" pipeline\\check_coverage.py', V2_REPO_PATH)
    if not success:
        print("Warning: Coverage audit script failed to execute.")
    else:
        # Check if audit status is PASS
        if "Audit Status:              PASS" in stdout:
            print("Revenue coverage audit: PASS")
        else:
            print("Warning: Revenue coverage audit returned warnings. Please inspect data/coverage_check.txt")

    # 3. Stage, commit and push changes to update GitHub Pages dashboard
    print("\nStep 7: Deploying updated data to SCOS 2.0 GitHub repository...")
    
    # Check if there are changes to stage
    _, status_out, _ = run_command("git status --porcelain", V2_REPO_PATH)
    if not status_out.strip():
        print("No new data changes to commit. SCOS 2.0 dashboard is already up to date.")
        sys.exit(0)

    # Stage files
    run_command("git add data/catalog.json data/catalog.js data/metrics.json data/metrics.js data/coverage_check.txt", V2_REPO_PATH)
    
    # Commit changes
    success, commit_out, _ = run_command('git commit -m "data: daily refresh of SCOS 2.0 metrics"', V2_REPO_PATH)
    if not success:
        print("Error committing changes.")
        sys.exit(1)
        
    # Push changes
    print("Pushing to GitHub Pages remote...")
    success, _, _ = run_command("git push origin main", V2_REPO_PATH)
    if not success:
        print("Fatal error pushing changes to GitHub. Please check network/auth status.")
        sys.exit(1)

    print("\n=========================================")
    print("SUCCESS: SCOS 2.0 PIPELINE RUN COMPLETE & DEPLOYED")
    print("=========================================")

if __name__ == "__main__":
    main()
