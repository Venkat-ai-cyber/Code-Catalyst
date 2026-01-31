from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# -------------------------------
# CONFIG
# -------------------------------

GITHUB_API_BASE = "https://api.github.com"

COURSE_DOMAIN_MAP = {
    "cse": "software",
    "it": "software",
    "ai": "software",
    "aiml": "software",
    "ece": "hardware",
    "eee": "hardware",
    "biomedical": "hardware",
    "mechanical": "core",
    "mech": "core",
    "civil": "core"
}

PROJECT_DOMAIN_RULES = {
    "software": ["python", "java", "javascript", "react", "node", "flask", "django"],
    "data": ["machine learning", "ml", "pandas", "numpy"],
    "hardware": ["arduino", "esp32", "embedded", "iot"],
    "web": ["html", "css", "react", "frontend", "backend"]
}

REQUIRED_PROJECTS = {
    "software": ["backend api", "database integration"],
    "hardware": ["embedded system", "sensor interfacing"],
    "data": ["ml project", "data analysis"],
    "core": ["simulation project", "design project"]
}

# -------------------------------
# GITHUB FUNCTIONS
# -------------------------------

def get_github_repos(username):
    url = f"{GITHUB_API_BASE}/users/{username}/repos"
    res = requests.get(url)

    if res.status_code != 200:
        return []

    repos = []
    for repo in res.json():
        repos.append({
            "name": repo["name"],
            "description": repo["description"] or "",
            "languages_url": repo["languages_url"],
            "html_url": repo["html_url"],
            "commits": repo["size"]
        })
    return repos


def get_repo_languages(languages_url):
    res = requests.get(languages_url)
    if res.status_code != 200:
        return []
    return list(res.json().keys())


# -------------------------------
# ANALYSIS LOGIC
# -------------------------------

def classify_project(description, languages):
    text = (description + " " + " ".join(languages)).lower()
    scores = {d: 0 for d in PROJECT_DOMAIN_RULES}

    for domain, keywords in PROJECT_DOMAIN_RULES.items():
        for kw in keywords:
            if kw in text:
                scores[domain] += 1

    return max(scores, key=scores.get)


def analyze_github(username):
    repos = get_github_repos(username)
    analysis = []
    domains_found = []

    for repo in repos:
        languages = get_repo_languages(repo["languages_url"])
        domain = classify_project(repo["description"], languages)
        domains_found.append(domain)

        analysis.append({
            "repo_name": repo["name"],
            "domain": domain,
            "languages": languages,
            "url": repo["html_url"]
        })

    return analysis, list(set(domains_found))


def detect_primary_domain(course):
    course = course.lower()
    for key in COURSE_DOMAIN_MAP:
        if key in course:
            return COURSE_DOMAIN_MAP[key]
    return "software"


def find_gaps(primary_domain, github_domains):
    required = REQUIRED_PROJECTS.get(primary_domain, [])
    missing = []

    for req in required:
        if req.split()[0] not in github_domains:
            missing.append(req)

    return missing


# -------------------------------
# API ENDPOINT
# -------------------------------

@app.route("/", methods=["GET"])
def analyze_profile():
    data = request.json

    github_username = "Pranatheesh-S"
    # course = data.get("course")
    # resume_skills = data.get("resume_skills", [])

    if not github_username or not course:
        return jsonify({"error": "github_username and course are required"}), 400

    primary_domain = detect_primary_domain(course)
    repo_analysis, github_domains = analyze_github(github_username)
    gaps = find_gaps(primary_domain, github_domains)

    response = {
        "github_user": github_username,
        "course": course,
        "primary_domain": primary_domain,
        "repo_count": len(repo_analysis),
        "projects": repo_analysis,
        "github_domains_detected": github_domains,
        "missing_projects": gaps,
        "career_readiness": "Good" if not gaps else "Needs Improvement"
    }

    return jsonify(response)


# -------------------------------
# RUN SERVER
# -------------------------------

if __name__ == "__main__":
    app.run(debug=True)
