# =============================================================================
# dashboard_finder_list_metrics.py
#
# --------------------------------------
# This script searches through ALL dashboards in your Wavefront account and
# finds every metric name that starts with a specific prefix (e.g. "test.").
#
# Instead of just telling you WHICH dashboards match, this version goes one
# step further, it extracts and lists the actual metric names it found inside
# each matching dashboard. So you get a clear picture of exactly what metrics
# are being used and where.
#
# HOW IT WORKS:
# 1. It connects to your Wavefront account using an API token.
# 2. It downloads a list of all your dashboards, 999 at a time (to avoid
#    overloading the API).
# 3. Once the full list is downloaded, it fetches the full details of each
#    dashboard simultaneously (in parallel) to speed things up.
# 4. Inside each dashboard, it reads through all the chart queries (the WQL
#    expressions that power each chart).
# 5. It uses a pattern-matching technique (Regex) to find any metric names
#    that start with your chosen prefix.
# 6. If any are found, it prints the dashboard name and the list of matching
#    metric names.
#
# WHEN TO USE THIS vs dashboard_finder.py:
# Use THIS script when you want to know the exact metric names found.
# Use dashboard_finder.py when you just want a quick yes/no list of dashboards.
# =============================================================================

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

# --- CONFIGURATION ---
# Replace these placeholder values with your real details before running.

# The base URL of your Wavefront instance.
WAVEFRONT_URL = "https://xx.wavefront.com"

# Your personal API token. Found in Wavefront under your profile settings.
# Treat this like a password , do not share or commit it to source control.
API_TOKEN = "xx"

# The metric prefix you want to search for.
# The dot at the end is important , it ensures "test.cpu" matches but
# something like "tester.cpu" does not.
PREFIX_TO_FIND = "test."

# How many dashboards to fetch and scan at the same time (in parallel).
# 15 is a safe number , going too high risks hitting Wavefront rate limits.
MAX_WORKERS = 15

# Build the auth header that gets sent with every API request.
# Wavefront requires this to verify who you are.
headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}


def extract_metrics_only(dash_json):
    """
    WHAT THIS FUNCTION DOES:
    Looks through the full JSON data of a single dashboard and finds all
    metric names that start with our target prefix.

    HOW:
    A dashboard is made up of sections → rows → charts → sources (queries).
    This function drills into that nested structure and runs a Regex pattern
    against each query string to find matching metric names.

    A Regex (Regular Expression) is a way of searching text using a pattern.
    Here the pattern means: "find anything that starts with 'test.' and is
    followed by letters, numbers, dots, or hyphens."

    Returns a sorted list of unique metric names found (no duplicates).
    """
    found_metrics = set()  # A set automatically removes duplicates
    sections = dash_json.get('sections', [])

    # Build the search pattern:
    # - re.escape() safely handles any special characters in the prefix
    # - [\w\.-]+ means "match any word characters, dots, or hyphens after"
    regex_pattern = rf"({re.escape(PREFIX_TO_FIND)}[\w\.-]+)"

    # Drill through the nested dashboard structure: sections > rows > charts > sources
    for section in sections:
        for row in section.get('rows', []):
            for chart in row.get('charts', []):
                for source in chart.get('sources', []):
                    query = source.get('query', '')  # This is the WQL query string
                    matches = re.findall(regex_pattern, query)  # Find all metric names
                    for m in matches:
                        found_metrics.add(m.strip())  # Add to our set (strip whitespace)

    return sorted(list(found_metrics))  # Return as a clean sorted list


def check_dashboard(dash):
    """
    WHAT THIS FUNCTION DOES:
    Takes a single dashboard's basic info (name + ID), fetches its full
    details from the Wavefront API, and then scans it for matching metrics.

    This function is called in parallel for many dashboards at once,
    which is why it's kept as a standalone function (one per thread).

    Returns a formatted string with results if metrics are found,
    or None if the dashboard has no matching metrics (or the API call fails).
    """
    dash_id = dash.get('id')
    dash_name = dash.get('name')

    # Build the API URL to get this dashboard's FULL details
    # (the initial list only gives us basic info like name and ID)
    url = f"{WAVEFRONT_URL}/api/v2/dashboard/{dash_id}"

    try:
        resp = requests.get(url, headers=headers, timeout=15)  # 15 second timeout

        if resp.status_code == 200:  # 200 means success
            dash_data = resp.json().get('response', {})
            metrics = extract_metrics_only(dash_data)  # Scan for matching metrics

            if metrics:
                # Build a readable output string for this dashboard
                output = f"Dashboard Name: {dash_name}\n"
                for m in metrics:
                    output += f"  - contains: {m}\n"
                return output

    except Exception:
        # If anything goes wrong (network timeout, bad data, etc.)
        # we silently skip this dashboard rather than crashing the whole script.
        pass

    return None  # Return nothing if no matches or an error occurred


def main():
    """
    WHAT THIS FUNCTION DOES:
    This is the main entry point , it coordinates everything:
    1. Downloads the full list of all dashboards (in batches of 999)
    2. Scans each one in parallel using multiple threads
    3. Prints the results as they come in
    """

    print(f"Fetching dashboard list...")
    all_dashboards = []  # This list will hold all dashboard stubs (name + ID only)
    offset = 0           # Pagination starting point
    limit = 999          # Maximum items per API page (Wavefront's max)

    # --- STEP 1: Download the full list of dashboards ---
    # We loop until we've fetched all pages of results.
    # Each page gives us up to 999 dashboards. If we get fewer than 999,
    # we've reached the last page.
    while True:
        url = f"{WAVEFRONT_URL}/api/v2/dashboard?offset={offset}&limit={limit}"
        try:
            r = requests.get(url, headers=headers).json()
            items = r.get('response', {}).get('items', [])  # The list of dashboards on this page
            all_dashboards.extend(items)                    # Add this page to our master list
            print(f" Loaded {len(all_dashboards)} stubs...")

            if len(items) < limit:
                break       # Fewer than 999 results = we're on the last page
            offset += limit  # Move to the next page
        except:
            break  # Stop if anything goes wrong during the list fetch

    print(f"\nScanning {len(all_dashboards)} dashboards for metrics under '{PREFIX_TO_FIND}'...\n")

    # --- STEP 2: Scan each dashboard in parallel ---
    # ThreadPoolExecutor runs up to MAX_WORKERS check_dashboard() calls at the same time.
    # This is much faster than doing them one at a time.
    # as_completed() lets us print results as each thread finishes, rather than waiting
    # for all of them to be done first.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_dash = {executor.submit(check_dashboard, d): d for d in all_dashboards}
        for future in as_completed(future_to_dash):
            result = future.result()
            if result:
                print(result)
                print("-" * 40)  # Visual separator between results


if __name__ == "__main__":
    # This line means: only run main() if this script is executed directly.
    # (Not if it's imported as a module by another script.)
    main()