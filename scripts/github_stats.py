import os
import time
from datetime import datetime, timezone

import requests


API = "https://api.github.com"
TOKEN = os.environ["GH_STATS_TOKEN"]

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
})


def github_get(url, params=None):
    response = session.get(url, params=params, timeout=30)

    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")

        if remaining == "0":
            reset = int(
                response.headers.get(
                    "X-RateLimit-Reset",
                    time.time(),
                )
            )

            wait = max(
                reset - int(time.time()) + 2,
                1,
            )

            print(
                f"Rate limit reached. "
                f"Waiting {wait} seconds..."
            )

            time.sleep(wait)

            response = session.get(
                url,
                params=params,
                timeout=30,
            )

    response.raise_for_status()
    return response


def get_all_pages(url, params=None):
    results = []
    page = 1

    while True:
        current_params = dict(params or {})
        current_params["per_page"] = 100
        current_params["page"] = page

        response = github_get(
            url,
            current_params,
        )

        data = response.json()

        if not data:
            break

        results.extend(data)

        if len(data) < 100:
            break

        page += 1

    return results


def get_user():
    return github_get(
        f"{API}/user"
    ).json()


def get_repositories(username):
    repositories = get_all_pages(
        f"{API}/user/repos",
        {
            "visibility": "all",
            "affiliation": "owner",
            "sort": "full_name",
            "direction": "asc",
        },
    )

    return [
        repo
        for repo in repositories
        if repo["owner"]["login"].lower()
        == username.lower()
        and not repo["fork"]
    ]


def get_commit_stats(repo):
    additions = 0
    deletions = 0
    commits = 0

    commits_url = (
        f"{API}/repos/"
        f"{repo['full_name']}/commits"
    )

    page = 1

    while True:
        response = github_get(
            commits_url,
            {
                "per_page": 100,
                "page": page,
            },
        )

        commit_list = response.json()

        if not commit_list:
            break

        for commit in commit_list:
            # Ignore merge commits
            if len(commit.get("parents", [])) > 1:
                continue

            sha = commit["sha"]

            detail = github_get(
                f"{API}/repos/"
                f"{repo['full_name']}/commits/{sha}"
            ).json()

            stats = detail.get("stats")

            if not stats:
                continue

            commits += 1
            additions += stats.get(
                "additions",
                0,
            )
            deletions += stats.get(
                "deletions",
                0,
            )

        if len(commit_list) < 100:
            break

        page += 1

    return additions, deletions, commits


def search_count(query):
    response = github_get(
        f"{API}/search/issues",
        {
            "q": query,
            "per_page": 1,
        },
    )

    return response.json()["total_count"]


def get_contributions(username):
    query = """
    query($user: String!) {
      user(login: $user) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
          }
        }
      }
    }
    """

    response = session.post(
        "https://api.github.com/graphql",
        json={
            "query": query,
            "variables": {
                "user": username,
            },
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if "errors" in data:
        print("GraphQL contribution error:")
        print(data["errors"])
        return 0

    return (
        data["data"]["user"]
        ["contributionsCollection"]
        ["contributionCalendar"]
        ["totalContributions"]
    )


def format_number(number):
    return f"{number:,}"


def update_readme(stats):
    readme_path = "README.md"

    with open(
        readme_path,
        "r",
        encoding="utf-8",
    ) as file:
        readme = file.read()

    start_marker = (
        "<!-- GITHUB_STATS_START -->"
    )

    end_marker = (
        "<!-- GITHUB_STATS_END -->"
    )

    if (
        start_marker not in readme
        or end_marker not in readme
    ):
        raise RuntimeError(
            "README.md does not contain "
            "the GitHub stats markers."
        )

    additions_k = stats["additions"] / 1000
    deletions_k = stats["deletions"] / 1000

    # IMPORTANT:
    # The HTML starts at column 0.
    # Otherwise GitHub Markdown may
    # interpret it as a code block.

    stats_block = f"""<!-- GITHUB_STATS_START -->

<p align="center">
  <sub>GITHUB ACTIVITY</sub>
</p>

<p align="center">
  <strong>{format_number(stats["commits"])}</strong> commits
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <strong>{format_number(stats["contributions"])}</strong> contributions
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <strong>{format_number(stats["repositories"])}</strong> repositories
</p>

<p align="center">
  <code>+{additions_k:.1f}K</code> added
  &nbsp;&nbsp;
  <code>−{deletions_k:.1f}K</code> deleted
  &nbsp;&nbsp;
  <code>{format_number(stats["pull_requests"])}</code> PRs
</p>

<p align="center">
  <sub>updated daily · {datetime.now(timezone.utc).strftime("%d.%m.%Y")}</sub>
</p>

<!-- GITHUB_STATS_END -->"""

    start = readme.index(start_marker)

    end = (
        readme.index(end_marker)
        + len(end_marker)
    )

    new_readme = (
        readme[:start]
        + stats_block
        + readme[end:]
    )

    with open(
        readme_path,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(new_readme)


def main():
    user = get_user()
    username = user["login"]

    print(
        f"Collecting GitHub statistics "
        f"for @{username}..."
    )

    repositories = get_repositories(
        username
    )

    print(
        f"Found {len(repositories)} repositories."
    )

    total_additions = 0
    total_deletions = 0
    total_commits = 0

    for index, repo in enumerate(
        repositories,
        start=1,
    ):
        print(
            f"[{index}/{len(repositories)}] "
            f"Processing "
            f"{repo['full_name']}..."
        )

        (
            additions,
            deletions,
            commits,
        ) = get_commit_stats(repo)

        total_additions += additions
        total_deletions += deletions
        total_commits += commits

        print(
            f"  +{additions:,} / "
            f"-{deletions:,} "
            f"({commits:,} commits)"
        )

    pull_requests = search_count(
        f"author:{username} is:pr"
    )

    issues = search_count(
        f"author:{username} is:issue"
    )

    contributions = get_contributions(
        username
    )

    stats = {
        "additions": total_additions,
        "deletions": total_deletions,
        "commits": total_commits,
        "repositories": len(repositories),
        "pull_requests": pull_requests,
        "issues": issues,
        "contributions": contributions,
        "updated_at": datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M UTC"
        ),
    }

    print("\nFinal statistics:")

    for key, value in stats.items():
        print(f"{key}: {value}")

    update_readme(stats)

    print(
        "\nREADME.md updated successfully."
    )


if __name__ == "__main__":
    main()
