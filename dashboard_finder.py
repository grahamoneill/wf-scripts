# =============================================================================
# SCRIPT: dashboard_finder.py
# --------------------------------------
# This script searches through ALL dashboards in your Wavefront tenant and
# produces a simple list of which dashboards contain a specific metric prefix
# (e.g. "test.").
#
# Think of it like a "grep" across all your dashboards , it quickly tells you
# YES or NO: does this dashboard contain anything starting with "test."?
#
# 1. It connects to your Wavefront account using an API token (like a password).
# 2. It downloads the full list of all dashboards, 999 at a time.
# 3. Once the list is loaded, it fetches the full details of each dashboard
#    simultaneously (in parallel) to speed things up.
# 4. It does a simple text search , if the prefix appears ANYWHERE in the
#    dashboard's raw data, it counts as a match.
# 5. It prints each matching dashboard name and ID as it finds them, and
#    shows a summary count at the end.
#
# WHEN TO USE THIS vs dashboard_finder_list_metrics.py:
# Use THIS script for a fast, simple yes/no match list.
# Use dashboard_finder_list_metrics.py when you need to see the exact
# metric names found inside each dashboard.
# =============================================================================

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- CONFIGURATION ---
# Replace these placeholder values with your real details before running.

# The base URL of your Wavefront/Tanzu Observability instance.
WAVEFRONT_URL = "https://xx.wavefront.com"

# Your personal API token. Found in Wavefront under your profile settings.
# Treat this like a password , do not share or commit it to source control.
API_TOKEN = "xxx"

# The metric prefix you want to search for.
# The dot at the end is important , it ensures "test.cpu" matches but
# something like "tester.cpu" does not.
PREFIX_TO_FIND = "test."

# How many dashboards to fetch and scan at the same time (in parallel).
# 15 is a safe number , going too high risks hitting Wavefront's rate limit,
# which causes the API to temporarily block your requests (HTTP 429 error).
MAX_WORKERS = 15

# Build the auth header that gets sent with every API request.
# Wavefront requires this to verify who you are.
headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}


def check_dashboard(dash):
    """
    WHAT THIS FUNCTION DOES:
    Takes a single dashboard's basic info (name + ID), fetches its full
    details from the Wavefront API, and checks if the metric prefix appears
    anywhere in the response.

    This is a simple text search , it doesn't extract specific metric names,
    it just checks if the prefix string exists anywhere in the raw data.
    This makes it very fast.

    This function is called in parallel for many dashboards at once,
    which is why it's a standalone function (one call per thread).

    Returns the dashboard name and ID as a string if a match is found,
    or None if no match (or if the API call fails).
    """
    dash_id = dash.get('id')
    dash_name = dash.get('name')

    # Build the API URL to get this dashboard's FULL details.
    # The initial list only gives us basic info like name and ID ,
    # we need the full detail to see the WQL chart queries inside.
    url = f"{WAVEFRONT_URL}/api/v2/dashboard/{dash_id}"

    try:
        resp = requests.get(url, headers=headers, timeout=15)  # 15 second timeout

        if resp.status_code == 200:  # 200 = success
            # resp.text is the entire raw response as a string.
            # If our prefix appears anywhere in that text, it's a match.
            # This is simpler (but less precise) than the Regex approach
            # used in dashboard_finder_list_metrics.py.
            if PREFIX_TO_FIND in resp.text:
                return f"{dash_name} (ID: {dash_id})"

    except Exception:
        # If anything goes wrong (timeout, bad data, network issue etc.)
        # silently skip this dashboard so the rest of the scan can continue.
        pass

    return None  # Return nothing if no match or error


def main():
    """
    WHAT THIS FUNCTION DOES:
    This is the main entry point , it coordinates everything:
    1. Downloads the full list of all dashboards (in batches of 999)
    2. Validates the list was fetched successfully
    3. Scans each dashboard in parallel using multiple threads
    4. Collects and prints all matches, plus a final summary
    """

    print(f"Fetching dashboard list from {WAVEFRONT_URL}...")
    all_dashboards = []  # Will hold all dashboard stubs (name + ID only)
    offset = 0           # Pagination cursor , which page we're on
    limit = 999          # Max items per API page (Wavefront's maximum)

    # --- STEP 1: Download the complete list of all dashboards ---
    # We loop through pages of 999 until we've got them all.
    # When a page returns fewer than 999 items, we know it's the last page.
    while True:
        url = f"{WAVEFRONT_URL}/api/v2/dashboard?offset={offset}&limit={limit}"
        try:
            response = requests.get(url, headers=headers)

            # If the API returns an error code, stop and report it.
            if response.status_code != 200:
                print(f"Error fetching list: {response.status_code}")
                break

            data = response.json()
            resp_obj = data.get('response', {})
            items = resp_obj.get('items', [])  # The dashboards on this page

            all_dashboards.extend(items)        # Add to our master list
            print(f" Retrieved {len(all_dashboards)} dashboards...")

            if len(items) < limit:
                break        # Last page reached
            offset += limit  # Move to the next page

        except Exception as e:
            print(f"Connection error during fetch: {e}")
            break

    # --- Validate we actually got some dashboards ---
    # If the list is empty, something went wrong (bad token, wrong URL, etc.)
    if not all_dashboards:
        print("Search failed: No dashboards found. Verify your API token and 'xxx.wavefront' URL.")
        return

    print(f"\nSearching {len(all_dashboards)} dashboards for metrics starting with '{PREFIX_TO_FIND}'...")
    print(f"Using {MAX_WORKERS} parallel threads. This may take a while for a lot of dashboards...\n")

    # --- STEP 2: Scan each dashboard in parallel ---
    # ThreadPoolExecutor runs up to MAX_WORKERS threads at the same time.
    # Each thread calls check_dashboard() for one dashboard.
    # as_completed() lets us print results as each thread finishes,
    # so you see matches appearing in real time rather than at the very end.
    matches = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_dash = {executor.submit(check_dashboard, d): d for d in all_dashboards}
        for future in as_completed(future_to_dash):
            result = future.result()
            if result:
                matches.append(result)
                print(f" [MATCH FOUND]: {result}")

    # --- STEP 3: Print the final summary ---
    print("\n--- SCAN COMPLETE ---")
    print(f"Total dashboards scanned: {len(all_dashboards)}")
    print(f"Total matches found: {len(matches)}")


if __name__ == "__main__":
    # This line means: only run main() if this script is executed directly.
    # (Not if it's imported as a module by another script.)
    main()