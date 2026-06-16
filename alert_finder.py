# =============================================================================
# SCRIPT: alert_finder.py
# --------------------------------------
# This script searches through ALL alerts in your Wavefront account and
# finds every alert that references a metric starting with a specific prefix
# (e.g. "test.metric.").
#
# HOW IT WORKS, STEP BY STEP:
# 1. It connects to your Wavefront account using an API token (like a password).
# 2. It downloads alerts in batches of 999, processing each batch immediately
#    (unlike the dashboard scripts, it does NOT wait to load everything first ,
#    it processes alerts as it downloads them, saving memory).
# 3. For each alert, it looks at two fields:
#    - "condition": the WQL query that determines when the alert fires
#    - "displayExpression": an optional secondary query used for display
# 4. It uses a pattern-matching technique (Regex) to find metric names that
#    start with your chosen prefix in both fields.
# 5. If matches are found, it prints the alert name, ID, and matching metrics.
# 6. It includes automatic retry logic , if an API call fails, it waits and
#    tries again up to 5 times before giving up.

# =============================================================================

import requests
import re
import sys
import time
import random

# --- CONFIGURATION ---
# Replace these placeholder values with your real details before running.

# The base URL of your Wavefront instance.
WAVEFRONT_URL = "https://xxxxx.wavefront.com"

# Your personal API token. Found in Wavefront under your profile settings.
API_TOKEN = "xxxxxx"

# The metric prefix you want to search for.
# Include the trailing dot to avoid partial matches ,
# e.g. "test.metric." matches "test.metric.cpu" but not "test.metricbad.cpu".
PREFIX_TO_FIND = "test.metric."

# Retry settings , if an API call fails, how hard should we try again?
MAX_RETRIES = 5     # Maximum number of retry attempts per API call
BACKOFF_FACTOR = 2  # How aggressively to increase the wait time between retries
                    # (e.g. wait 2s, then 4s, then 8s. , this is "exponential backoff")

# Build the auth header that gets sent with every API request.
headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}

# Pre-compile the Regex pattern once at startup for efficiency.
# This pattern means: "find anything starting with our prefix, followed by
# word characters, dots, or hyphens."
# re.escape() safely handles any special characters in PREFIX_TO_FIND.
REGEX_PATTERN = rf"({re.escape(PREFIX_TO_FIND)}[\w\.-]+)"


def extract_metrics_from_text(text):
    """
    WHAT THIS FUNCTION DOES:
    Searches a single string of text (e.g. a WQL query) and returns all
    metric names found that start with our target prefix.

    Uses Regex (pattern matching) to find all occurrences.
    Returns a set (no duplicates) of matched metric name strings.
    Returns an empty set if the input is empty/None.
    """
    if not text:
        return set()  # Nothing to search , return an empty set immediately

    matches = re.findall(REGEX_PATTERN, text)  # Find all metric names in the text
    return {m.strip() for m in matches}         # Return as a set (removes duplicates)


def fetch_and_process_alerts():
    """
    WHAT THIS FUNCTION DOES:
    This is the main function that does all the work:

    1. Downloads all alerts from Wavefront, one page (up to 999) at a time.
    2. For each page, immediately scans every alert for matching metrics.
    3. Prints results as it goes (no waiting for everything to finish first).
    4. Retries failed API calls automatically before giving up.
    5. Prints a final count summary at the end.

    WHY IT STREAMS INSTEAD OF LOADING ALL FIRST:
    Alerts can be very numerous. Processing batch-by-batch (streaming) means
    we never have to hold all alerts in memory at once , safer and more
    efficient for large accounts.
    """
    offset = 0      # Pagination cursor , which page we're currently fetching
    limit = 999     # Max alerts per page (Wavefront's maximum)
    match_count = 0  # Running count of alerts with matching metrics
    total_alerts = 0 # Running count of all alerts checked so far

    print(f"Starting scan of alerts on {WAVEFRONT_URL}...")

    # Keep fetching pages of alerts until there are no more left
    while True:
        url = f"{WAVEFRONT_URL}/api/v2/alert?offset={offset}&limit={limit}"

        # --- RETRY LOGIC ---
        # Sometimes API calls fail due to network hiccups or rate limiting.
        # Instead of crashing, we retry up to MAX_RETRIES times, waiting
        # a little longer between each attempt (exponential backoff).
        success = False
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, headers=headers, timeout=30)

                if response.status_code == 200:  # 200 = success
                    success = True
                    break  # Got a good response , exit the retry loop

                else:
                    # API returned an error (e.g. 429 rate limit, 500 server error).
                    # Calculate how long to wait: 2^attempt seconds + a small random
                    # amount to avoid all retries hitting the server at the same time.
                    wait_time = (BACKOFF_FACTOR ** attempt) + random.random()
                    sys.stderr.write(f"\nAPI returned {response.status_code}. Retrying in {wait_time:.2f}s...\n")
                    time.sleep(wait_time)

            except requests.exceptions.RequestException as e:
                # A network-level error (timeout, DNS failure, etc.)
                wait_time = (BACKOFF_FACTOR ** attempt) + random.random()
                sys.stderr.write(f"\nConnection error: {e}. Retrying in {wait_time:.2f}s...\n")
                time.sleep(wait_time)

        # If all retries failed, we can't continue , exit the loop
        if not success:
            sys.stderr.write("Max retries reached. Exiting.\n")
            break

        # --- DATA PROCESSING ---
        # We have a successful response , extract the list of alerts from it
        data = response.json()
        items = data.get('response', {}).get('items', [])

        # No items means we've gone past the last page , we're done
        if not items:
            break

        total_alerts += len(items)  # Track how many alerts we've seen so far

        # --- SCAN EACH ALERT IN THIS BATCH ---
        for alert in items:
            alert_name = alert.get('name')
            alert_id = alert.get('id')

            # Alerts have two query fields we need to check:
            # "condition" , the WQL that triggers the alert
            # "displayExpression" , an optional extra query shown in the alert view
            condition = alert.get('condition', '')
            display_expr = alert.get('displayExpression', '')

            # Search both fields for matching metric names
            found_metrics = extract_metrics_from_text(condition)
            found_metrics.update(extract_metrics_from_text(display_expr))  # Merge results

            if found_metrics:
                match_count += 1
                # Build a readable output block for this alert
                output = f"ALERT #{alert_id}: {alert_name}\n"
                for m in sorted(list(found_metrics)):
                    output += f"  - contains: {m}\n"
                print(output + "-" * 40)  # Print with a visual separator

        # Print a live progress update to stderr (doesn't interfere with match output on stdout)
        sys.stderr.write(f"\rProcessed {total_alerts} alerts...")
        sys.stderr.flush()

        # If this page had fewer than the max, it was the last page , stop here
        if len(items) < limit:
            break

        offset += limit  # Move to the next page

    # --- FINAL SUMMARY ---
    print(f"\n\n--- SCAN COMPLETE ---")
    print(f"Total alerts checked: {total_alerts}")
    print(f"Total matches found: {match_count}")


if __name__ == "__main__":
    # This line means: only run the function if this script is executed directly.
    # (Not if it's imported as a module by another script.)
    fetch_and_process_alerts()