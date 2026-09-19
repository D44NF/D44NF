import os
import time
from datetime import datetime, timezone

import requests

API = "https://api.github.com"
START = "<!-- GITHUB_STATS_START -->"
END = "<!-- GITHUB_STATS_END -->"

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {os.environ['GH_STATS_TOKEN']}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
})


def github_get(url, params=None):
    response = session.get(url, params=params, timeout=30)

    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        reset = int(response.headers.get("X-RateLimit-Reset", time.time()))
        wait = max(reset - int(time.time()) + 2, 1)
        print(f"Rate limit reached. Waiting {wait}s...")
        time.sleep(wait)
        response = session.get(url, params=params, timeout=30)

    response.raise_for_status()
    return response.json()


def get_all_pages(url, params=None):
    results = []

    for page in range(1, 1000):
        data = github_get(url, {**(params or {}), "per_page": 100, "page": page})
        results.extend(data)

        if len(data) < 100:
            break

    return results


def get_repositories(username):
    repos = get_all_pages(
        f"{API}/user/repos",
        {"visibility": "all", "affiliation": "owner", "sort": "full_name", "direction": "asc"},
    )
    return [
        r for r in repos
        if r["owner"]["login"].lower() == username.lower() and not r["fork"]
    ]


def get_commit_stats(repo):
    additions = deletions = commits = 0
    url = f"{API}/repos/{repo['full_name']}/commits"

    for commit in get_all_pages(url):
        if len(commit.get("parents", [])) > 1:  # Merge-Commits ignorieren
            continue

        stats = github_get(f"{url}/{commit['sha']}").get("stats")
        if not stats:
            continue

        commits += 1
        additions += stats.get("additions", 0)
        deletions += stats.get("deletions", 0)

    return additions, deletions, commits


def get_pull_requests(username):
    return github_get(
        f"{API}/search/issues",
        {"q": f"author:{username} is:pr", "per_page": 1},
    )["total_count"]


def get_contributions(username):
    query = """
    query($user: String!) {
      user(login: $user) {
        contributionsCollection {
          contributionCalendar { totalContributions }
        }
      }
    }
    """
    response = session.post(
        f"{API}/graphql",
        json={"query": query, "variables": {"user": username}},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if "errors" in data:
        print("GraphQL contribution error:", data["errors"])
        return 0

    return data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]


def update_readme(stats):
    with open("README.md", encoding="utf-8") as file:
        readme = file.read()

    if START not in readme or END not in readme:
        raise RuntimeError("README.md does not contain the GitHub stats markers.")

    # Das HTML muss bei Spalte 0 beginnen, sonst rendert GitHub es als Code-Block.
    block = f"""{START}

<p align="center">
  <sub>GITHUB ACTIVITY</sub>
</p>

<p align="center">
  <strong>{stats["commits"]:,}</strong> commits
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <strong>{stats["contributions"]:,}</strong> contributions
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <strong>{stats["repositories"]:,}</strong> repositories
</p>

<p align="center">
  <code>+{stats["additions"] / 1000:.1f}K</code> added
  &nbsp;&nbsp;
  <code>−{stats["deletions"] / 1000:.1f}K</code> deleted
  &nbsp;&nbsp;
  <code>{stats["pull_requests"]:,}</code> PRs
</p>

<p align="center">
  <sub>updated daily · {datetime.now(timezone.utc):%d.%m.%Y}</sub>
</p>

{END}"""

    start = readme.index(START)
    end = readme.index(END) + len(END)

    with open("README.md", "w", encoding="utf-8") as file:
        file.write(readme[:start] + block + readme[end:])


def main():
    username = github_get(f"{API}/user")["login"]
    print(f"Collecting GitHub statistics for @{username}...")

    repos = get_repositories(username)
    print(f"Found {len(repos)} repositories.")

    additions = deletions = commits = 0

    for i, repo in enumerate(repos, 1):
        print(f"[{i}/{len(repos)}] Processing {repo['full_name']}...")

        a, d, c = get_commit_stats(repo)
        additions += a
        deletions += d
        commits += c

        print(f"  +{a:,} / -{d:,} ({c:,} commits)")

    stats = {
        "additions": additions,
        "deletions": deletions,
        "commits": commits,
        "repositories": len(repos),
        "pull_requests": get_pull_requests(username),
        "contributions": get_contributions(username),
    }

    print("\nFinal statistics:")
    for key, value in stats.items():
        print(f"{key}: {value}")

    update_readme(stats)
    print("\nREADME.md updated successfully.")


if __name__ == "__main__":
    main()
