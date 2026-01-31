import os
import sys
import requests
import json
import re
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import easyocr
from functools import wraps
import firebase_admin
from firebase_admin import credentials, firestore
import google.generativeai as genai

# --- DB Import ---
# Importing the new Firestore 'Student' class from your models.py
from models import Student

# -------------------------------
# LLaMA / OpenRouter Config
# -------------------------------
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")
URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3-8b-instruct"
GITHUB_API_BASE = "https://api.github.com"

if not API_KEY:
    print("WARNING: OPENROUTER_API_KEY not set in .env")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)
app.secret_key = 'super_secret_key'

# --- Configuration ---
basedir = os.path.abspath(os.path.dirname(__file__))
# SQLALCHEMY CONFIG REMOVED

# UPLOAD_FOLDER REMOVED (No longer needed since we aren't saving files)

# --- Lazy Loading OCR Reader ---
reader_instance = None

def get_reader():
    global reader_instance
    if reader_instance is None:
        print("Initializing OCR engine... (This happens only once)")
        reader_instance = easyocr.Reader(['en'], gpu=False)
    return reader_instance

# --- Helper: LeetCode Stats ---
def get_leetcode_topic_stats(username):
    url = "https://leetcode.com/graphql"
    query = """
    query skillStats($username: String!) {
      matchedUser(username: $username) {
        tagProblemCounts {
          advanced { tagName problemsSolved }
          intermediate { tagName problemsSolved }
          fundamental { tagName problemsSolved }
        }
      }
    }
    """
    variables = {"username": username}
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "errors" in data or not data.get("data", {}).get("matchedUser"):
                return None
            return data["data"]["matchedUser"]["tagProblemCounts"]
    except Exception as e:
        print(f"LeetCode Error: {e}")
    return None

# --- Helper: Send Question to LLaMA ---
def ask_llama(context_text, question):
    """Universal helper to communicate with LLaMA via OpenRouter."""
    if not API_KEY:
        return "API Key missing."
        
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a specialized Career & Tech Lead AI. Return strictly valid JSON when requested. No conversational filler or markdown code blocks."
            },
            {
                "role": "user",
                "content": f"Context/Resume:\n{context_text}\n\nQuestion/Task:\n{question}"
            }
        ],
        "temperature": 0.2,
        "max_tokens": 1000
    }

    try:
        response = requests.post(URL, headers=HEADERS, json=payload)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        return f"Error: {response.text}"
    except Exception as e:
        return f"Request Failed: {str(e)}"

# -------------------------------
# GITHUB UTILITIES
# -------------------------------
def fetch_github_data(username):
    """Fetch repos and their details from GitHub API."""
    try:
        res = requests.get(f"{GITHUB_API_BASE}/users/{username}/repos", timeout=5)
        if res.status_code != 200: return []
        
        repos = []
        for repo in res.json():
            # Get languages for each repo
            lang_res = requests.get(repo["languages_url"], timeout=5)
            langs = list(lang_res.json().keys()) if lang_res.status_code == 200 else []
            
            repos.append({
                "name": repo["name"],
                "description": repo["description"] or "No description provided.",
                "languages": langs,
                "url": repo["html_url"]
            })
        return repos
    except Exception as e:
        print(f"GitHub Fetch Error: {e}")
        return []

# --- Helper: Connect to LLaMA for Chat ---
def chat_llama(messages):
    """
    Sends a full conversation history to LLaMA.
    Used for the interactive chatbot.
    """
    if not API_KEY:
        return "API Key missing."
        
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.7, # Higher temperature for conversation
        "max_tokens": 800
    }

    try:
        response = requests.post(URL, headers=HEADERS, json=payload)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        return f"Error: {response.text}"
    except Exception as e:
        return f"Request Failed: {str(e)}"

# --- Authentication Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # FIRESTORE CHANGE: Use get_by_email
        student = Student.get_by_email(email)
        
        if student and student.password_hash and check_password_hash(student.password_hash, password):
            session['user_id'] = student.id
            session['user_name'] = student.name
            return redirect(url_for('create_resume'))
        else:
            flash('Invalid email or password')
            
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        department = request.form.get('department')
        enrollment_year = request.form.get('enrollment_year')
        
        # FIRESTORE CHANGE: Check existence
        if Student.get_by_email(email):
            flash('Email already registered')
            return redirect(url_for('signup'))
        
        hashed_password = generate_password_hash(password)
        
        # FIRESTORE CHANGE: Create new student doc
        new_student = Student.create(
            name=name, 
            email=email, 
            password_hash=hashed_password,
            department=department,
            enrollment_year=int(enrollment_year)
        )
        
        # ID is now the Firestore Document ID
        session['user_id'] = new_student.id
        session['user_name'] = new_student.name
        
        return redirect(url_for('create_resume'))
        
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    # FIRESTORE CHANGE: get_by_id
    student = Student.get_by_id(session['user_id'])
    
    if not student:
        session.clear()
        flash('Session expired. Please login again.')
        return redirect(url_for('login'))
    
    # Use dynamic top_roles if available, otherwise empty
    top_roles = student.top_roles or []
    
    # Sort just in case LLaMA returned unsorted
    try:
        if isinstance(top_roles, list):
            top_roles.sort(key=lambda x: x.get('score', 0), reverse=True)
    except Exception as e:
        print(f"Sorting error: {e}") 

    # Prepare data for frontend
    best_role = top_roles[0] if top_roles else None
    
    # FIRESTORE CHANGE: Skills are now in the student object
    verified_skills = student.verified_skills
    
    # --- Daily Bounty Logic ---
    bounty = None
    today = datetime.utcnow().date()
    
    # Check if already solved today (Handle potential string conversion from DB)
    is_solved_today = False
    
    # Convert DB date (which might be a full datetime or string) to date obj for comparison
    last_bounty_val = student.last_bounty_date
    if last_bounty_val:
        if isinstance(last_bounty_val, datetime):
            if last_bounty_val.date() == today:
                is_solved_today = True
        elif isinstance(last_bounty_val, str):
            # If stored as ISO string
            try:
                if datetime.fromisoformat(last_bounty_val).date() == today:
                    is_solved_today = True
            except: pass

    if is_solved_today:
        pass # Already solved
    elif verified_skills:
        # Check session for existing bounty
        # skills in Firestore are dicts: {'skill_name': '...', 'verified': True}
        skill_names = [s['skill_name'] for s in verified_skills if s.get('verified')]
        
        if session.get('bounty_data') and session.get('bounty_skill') in skill_names:
            bounty = session['bounty_data']
        else:
            # Generate new bounty
            import random
            if skill_names:
                target_skill = random.choice(skill_names)
                print(f"Generating Daily Bounty for: {target_skill}")
                
                bounty_prompt = (
                    f"Create a specific, TOUGH, advanced-level multiple choice question for a developer skilled in '{target_skill}'. "
                    "The question should test deep understanding or edge cases. "
                    "Provide 4 distinct options. Mark the correct one INDEPENDENTLY in the 'answer' field (e.g., index 0-3). "
                    "Return strictly JSON: {\"question\": \"...\", \"options\": [\"A. ...\", \"B. ...\", \"C. ...\", \"D. ...\"], \"answer\": 0} "
                    "No markdown."
                )
                
                bounty_resp = ask_llama("", bounty_prompt)
                
                # Parse
                import json
                import re
                clean_bounty = re.sub(r'```json\s*|\s*```', '', bounty_resp).strip()
                try:
                    s_idx = clean_bounty.find('{')
                    e_idx = clean_bounty.rfind('}')
                    if s_idx != -1 and e_idx != -1:
                        bounty_data = json.loads(clean_bounty[s_idx:e_idx+1])
                        bounty_data['skill'] = target_skill
                        session['bounty_data'] = bounty_data
                        session['bounty_skill'] = target_skill
                        bounty = bounty_data
                except Exception as be:
                    print(f"Bounty Generation Error: {be}")
    else:
        session.pop('bounty_data', None)

    scores = {
        'roles': top_roles,
        'best_fit': best_role['role'] if best_role else 'N/A',
        'best_score': best_role['score'] if best_role else 0
    }

    return render_template('dashboard.html', student=student, scores=scores, verified_skills=verified_skills, bounty=bounty, is_solved_today=is_solved_today)

@app.route('/solve_bounty', methods=['POST'])
@login_required
def solve_bounty():
    selected_option = int(request.form.get('option_index'))
    bounty_data = session.get('bounty_data')
    
    if not bounty_data:
        flash("Expired or invalid bounty.")
        return redirect(url_for('dashboard'))
        
    correct_answer = int(bounty_data.get('answer'))
    
    student = Student.get_by_id(session['user_id'])
    
    # FIRESTORE CHANGE: Update logic
    updates = {}
    updates['last_bounty_date'] = datetime.utcnow() # Store as datetime
    
    if selected_option == correct_answer:
        # Correct!
        updates['xp'] = student.xp + 50
        flash("Correct! +50 XP Added.")
    else:
        # Incorrect - No XP, but burnt the chance
        flash("Incorrect answer. Better luck tomorrow!")
        
    student.update(updates)
    session.pop('bounty_data', None) # Clear from session
        
    return redirect(url_for('dashboard'))

@app.route('/upload_resume', methods=['POST'])
def upload_resume():
    # 1. Check File Presence
    if 'resume' not in request.files:
        flash('No file part')
        return redirect(url_for('dashboard'))
    
    file = request.files['resume']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('dashboard'))
    
    if file:
        filename = secure_filename(file.filename)
        # --- CHANGED: Read file content directly into memory ---
        file_bytes = file.read()

        # 2. OCR and Analysis Processing
        try:
            reader = get_reader()
            # Pass bytes directly to readtext
            results = reader.readtext(file_bytes, detail=0) 
            extracted_text = " ".join(results)
            
            # --- LLaMA Analysis Start ---
            print("\n📊 Calling LLaMA for Top 3 Role Suggestions...")
            
            prompt = (
                "Analyze the resume content below. Identify the top 3 most suitable specific job roles for this candidate. "
                "For each role, provide a suitability score (0-100) based on skills and experience. "
                "Return strictly a JSON array of objects, where each object has 'role' (string) and 'score' (integer). "
                "Example: [{\"role\": \"Backend Developer\", \"score\": 90}, {\"role\": \"Data Analyst\", \"score\": 85}]. "
                "Do NOT include markdown formatting or extra text.\n\n"
                f"Resume Text: {extracted_text[:1000]}..." 
            )
            
            response_text = ask_llama(extracted_text, prompt)
            print(f"DEBUG: LLaMA Raw Response: {response_text}")
            
            top_roles_data = []
            try:
                # cleans markdown code blocks if present
                clean_text = re.sub(r'```json\s*|\s*```', '', response_text).strip()
                # find first [ and last ]
                start = clean_text.find('[')
                end = clean_text.rfind(']')
                if start != -1 and end != -1:
                    json_str = clean_text[start:end+1]
                    top_roles_data = json.loads(json_str)
                    print(f"DEBUG: Parsed Roles: {top_roles_data}")
                else:
                    print("DEBUG: Could not find JSON array in response.")
            except Exception as js_e:
                 print(f"DEBUG: JSON Parsing Failed: {js_e}")

            # Fallback if empty
            if not top_roles_data:
                top_roles_data = [
                    {'role': 'SDE (Fallback)', 'score': 0}, 
                    {'role': 'Full Stack (Fallback)', 'score': 0}, 
                    {'role': 'AI/ML (Fallback)', 'score': 0}
                ]

            # --- LLaMA Analysis End ---

            # 3. Store in DB
            student = None
            if 'user_id' in session:
                 student_id = session['user_id']
                 student = Student.get_by_id(student_id)
                 if student:
                     print(f"DEBUG: Found logged-in student [ID: {student_id}]")
            
            if not student:
                flash('Please login to save resume data.')
                return redirect(url_for('login'))

            # FIRESTORE CHANGE: Update Fields via .update()
            updates = {}
            updates['top_roles'] = top_roles_data
            updates['market_analysis'] = None # Force regeneration
            
            # --- ROADMAP GENERATION ---
            try:
                # Determine best role (fallback to software engineer)
                best_role = top_roles_data[0]['role'] if top_roles_data else "Software Engineer"
                print(f"Generating personalized roadmap for: {best_role}")
                
                roadmap_prompt = (
                    f"Create a step-by-step learning roadmap for a student aspiring to be a '{best_role}'. "
                    "Based on the resume content provided earlier, mark steps as 'Completed' if they clearly have the skill. "
                    "Mark ALL remaining steps as 'Focus'. Do not use 'Locked' or 'In Progress'. "
                    "CRITICAL LOGIC RULE: If a higher-level step (e.g., Step 4) is marked 'Completed', ALL previous steps (Step 1, 2, 3) MUST also be marked 'Completed', regardless of explicit mention in the resume. "
                    "Return strictly a JSON list of objects. Each object must have: "
                    "'title' (string), 'description' (short string), 'status' ('Completed', 'Focus'). "
                    "Example: [{\"title\": \"Python\", \"description\": \"Data Structures\", \"status\": \"Completed\"}]. "
                    "Generate exactly 5-6 major steps. Do not use Markdown.\n\n"
                    f"Resume Context: {extracted_text[:1000]}"
                )
                
                roadmap_response = ask_llama("", roadmap_prompt)
                
                # Parse Roadmap JSON
                clean_rmap = re.sub(r'```json\s*|\s*```', '', roadmap_response).strip()
                # Find JSON array
                idx_start = clean_rmap.find('[')
                idx_end = clean_rmap.rfind(']')
                if idx_start != -1 and idx_end != -1:
                    roadmap_data = json.loads(clean_rmap[idx_start:idx_end+1])
                    updates['roadmap'] = roadmap_data
                    print(f"DEBUG: Roadmap saved with {len(roadmap_data)} steps.")
                else:
                    print("DEBUG: Roadmap JSON not found in response.")
            except Exception as r_e:
                print(f"Error generating roadmap: {r_e}")

            # APPLY UPDATES
            student.update(updates)

            # Create Resume Record (Subcollection)
            # Note: We are just saving the OCR text, not the file itself
            student.add_resume(filename=filename, ocr_content=extracted_text)
            
            print("DEBUG: Database update successful.")
            flash('Resume analyzed! Top suitable roles updated.')

        except Exception as e:
            flash(f'Error processing resume: {str(e)}')
            print(f"Error: {e}")
            
        return redirect(url_for('dashboard'))
    
    return redirect(url_for('dashboard'))

@app.route('/upload_certificate', methods=['POST'])
@login_required
def upload_certificate():
    if 'certificate' not in request.files:
        flash('No file part')
        return redirect(url_for('dashboard'))
    file = request.files['certificate']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('dashboard'))
    if file:
        filename = secure_filename(file.filename)
        # --- CHANGED: Read file content directly into memory ---
        file_bytes = file.read()
        
        # 1. OCR (Reuse get_reader)
        try:
            reader = get_reader()
            # Pass bytes directly to readtext
            results = reader.readtext(file_bytes, detail=0) 
            extracted_text = " ".join(results)
            print(f"DEBUG: Certificate OCR Text: {extracted_text[:100]}...")

            # 2. LLaMA Verification
            prompt = (
                "Analyze the following text from a file uploaded as a certificate. "
                "Step 1: Determine if this is a valid certificate of completion, achievement, or skill verification. "
                "Step 2: If valid (1), identify the primary skill or subject (e.g., 'Python', 'Machine Learning'). "
                "Step 3: If invalid (0), return empty skill. "
                "Return JSON ONLY: {\"valid\": 1, \"skill\": \"SkillName\"} or {\"valid\": 0}. "
                "No markdown.\n\n"
                f"Text: {extracted_text[:1000]}"
            )
            
            response_text = ask_llama(extracted_text, prompt)
            print(f"DEBUG: LLaMA Cert Response: {response_text}")
            
            # Parse JSON
            import re
            clean_text = re.sub(r'```json\s*|\s*```', '', response_text).strip()
            # Simple fallback regex parser if strict JSON fails
            match_valid = re.search(r'"valid":\s*(\d)', clean_text)
            is_valid = int(match_valid.group(1)) if match_valid else 0
            
            skill_name = "Unknown Skill"
            match_skill = re.search(r'"skill":\s*"([^"]+)"', clean_text)
            if match_skill:
                # Normalize: Strip whitespace and Title Case (e.g., "python " -> "Python")
                skill_name = match_skill.group(1).strip().title()
            
            # 3. DB Update
            if is_valid == 1:
                student = Student.get_by_id(session['user_id'])
                
                # Check for existing skill is handled inside add_skill
                success, msg = student.add_skill(skill_name=skill_name, proficiency=5, verified=True)
                
                if success:
                    flash(f"Skill '{skill_name}' added and verified!")
                else:
                    flash(f"Skill '{skill_name}' was already verified.")
            else:
                flash("Could not verify certificate. Please upload a clear image of a valid certificate.")
                
        except Exception as e:
             print(f"Error processing certificate: {e}")
             flash("Error processing certificate.")

    return redirect(url_for('dashboard'))

@app.route('/leetcode')
@login_required
def leetcode():
    student = Student.get_by_id(session['user_id'])
    return render_template('leetcode.html', student=student)

@app.route('/leetcode_analysis', methods=['POST'])
@login_required
def leetcode_analysis():
    username = request.form.get('username')
    if not username:
        flash('Please enter a username.')
        return redirect(url_for('dashboard'))

    stats = get_leetcode_topic_stats(username)
    if not stats:
        flash(f"User '{username}' not found on LeetCode.")
        if request.form.get('source_page') == 'leetcode':
            return redirect(url_for('leetcode'))
        return redirect(url_for('dashboard'))

    # Store username (FIRESTORE CHANGE)
    student = Student.get_by_id(session['user_id'])
    if student:
        student.update({'leetcode_username': username})

    # Sort and Flatten stats for LLaMA
    all_tags = []
    categories = ['advanced', 'intermediate', 'fundamental']
    for category in categories:
        if category in stats:
            for tag in stats[category]:
                if tag['problemsSolved'] > 0:
                    all_tags.append({
                        "topic": tag['tagName'],
                        "solved": tag['problemsSolved'],
                        "category": category.capitalize()
                    })

    # Sort descending by solved count
    sorted_tags = sorted(all_tags, key=lambda x: x['solved'], reverse=True)

    # Create summary text for prompt
    stats_text = "Topic | Solved | Category\n"
    stats_text += "---|---|---\n"
    for item in sorted_tags:
        stats_text += f"{item['topic']} | {item['solved']} | {item['category']}\n"
    
    prompt = (
        "Analyze the following LeetCode topic statistics for a student.\n\n"
        f"{stats_text}\n\n"
        "Based *strictly* on these stats, provide a personalized study strategy in strictly valid JSON format with three keys:\n"
        "1. \"strengths\": Identify what they are good at and suggest one advanced concept. (Use HTML <ul><li> tags)\n"
        "2. \"focus\": Identify the most critical area they are neglecting and explain why. (Use HTML <p> or <ul> tags)\n"
        "3. \"plan\": Suggest 3 specific types of problems they should solve next. (Use HTML <ul><li> tags)\n\n"
        "Example Output:\n"
        "{\"strengths\": \"<ul><li>...</li></ul>\", \"focus\": \"<p>...</p>\", \"plan\": \"<ul><li>...</li></ul>\"}\n"
        "Do NOT return markdown code blocks. Return ONLY the raw JSON string."
    )
    
    response_text = ask_llama("", prompt)
    
    # Parse JSON
    import json
    import re
    cleaned_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
    
    try:
        suggestion_data = json.loads(cleaned_json)
        # Ensure keys exist
        if not isinstance(suggestion_data, dict):
            raise ValueError("Not a dictionary")
            
        session['leetcode_suggestion_json'] = suggestion_data
        session['leetcode_suggestion'] = None # Clear legacy non-json if any
    except Exception as e:
        print(f"JSON Parse Error for LeetCode: {e}")
        # Fallback to string if JSON fails
        session['leetcode_suggestion'] = response_text
        session['leetcode_suggestion_json'] = None
    
    session['leetcode_stats'] = stats
    
    flash("LeetCode profile analyzed successfully!")
    
    if request.form.get('source_page') == 'leetcode':
        return redirect(url_for('leetcode'))
        
    return redirect(url_for('dashboard'))

# --- Resume Builder Routes ---
@app.route('/resume_builder')
# @login_required 
def resume_builder():
    resume_data = session.get('resume_data', {})
    return render_template('resume_builder.html', resume_data=resume_data)

@app.route('/create-resume')
# @login_required
def create_resume():
    """Separate route for the specific 'Create Your Resume' page."""
    resume_data = session.get('resume_data', {})
    return render_template('create_resume.html', resume_data=resume_data, hide_sidebar=True)

@app.route('/generate_resume', methods=['POST'])
def generate_resume():
    full_name = request.form.get('full_name')
    institute_name = request.form.get('institute_name')
    degree = request.form.get('degree')
    github_id = request.form.get('github_id')
    leetcode_id = request.form.get('leetcode_id')
    skills_str = request.form.get('skills')
    specialization = request.form.get('specialization')
    summary = request.form.get('summary')
    
    skills_list = [s.strip() for s in skills_str.split(',') if s.strip()]
    
    # Process Projects
    project_titles = request.form.getlist('project_title')
    project_descs = request.form.getlist('project_desc')
    project_links = request.form.getlist('project_link')
    
    projects = []
    if project_titles:
        for i in range(len(project_titles)):
            if project_titles[i].strip():
                projects.append({
                    'title': project_titles[i],
                    'desc': project_descs[i] if i < len(project_descs) else "",
                    'link': project_links[i] if i < len(project_links) else ""
                })

    # Process Achievements
    achievements_str = request.form.get('achievements')
    achievements_list = []
    if achievements_str:
        # Split by new line
        achievements_list = [a.strip() for a in achievements_str.split('\n') if a.strip()]

    # Construct Links
    github_url = f"https://github.com/{github_id}" if github_id else "#"
    leetcode_url = f"https://leetcode.com/{leetcode_id}" if leetcode_id else "#"
    
    # Get Email if logged in
    email = session.get('user_email', '') 
    if 'user_id' in session:
        student = Student.get_by_id(session['user_id'])
        if student:
            email = student.email

    data = {
        'full_name': full_name,
        'institute_name': institute_name,
        'degree': degree,
        'github_id': github_id,
        'leetcode_id': leetcode_id,
        'github_url': github_url,
        'leetcode_url': leetcode_url,
        'skills_list': skills_list,
        'specialization': specialization,
        'summary': summary, # Add summary
        'projects': projects,
        'achievements': achievements_list,
        'email': email
    }

    # --- SESSION STORAGE FOR EDITING ---
    # --- SESSION STORAGE FOR EDITING ---
    session['resume_data'] = {
        'full_name': full_name,
        'institute_name': institute_name,
        'degree': degree,
        'github_id': github_id,
        'leetcode_id': leetcode_id,
        'skills': skills_str,
        'specialization': specialization,
        'summary': summary, # Add summary
        'projects': projects,
        'achievements': achievements_str
    }

    # --- ONE-TIME CAREER PATHWAY DERIVATION (FIREBASE) ---
    try:
        if 'user_id' in session:
            student = Student.get_by_id(session['user_id'])
            
            # RUN ONCE RULE: Only if not already derived
            if student and not student.data.get('profileDerived'):
                print("🧠 Deriving Career Pathway for the first time...")
                
                # Construct strict prompt for LLaMA
                pathway_prompt = (
                    "You are a strict Career Pathway Engine. Analyze this student profile and derive metadata.\n"
                    "RULES:\n"
                    "1. Anchor to Course/Degree/Branch (60% weight).\n"
                    "   - If 'Specialization' field is provided, it modifies/refines the Course anchor.\n"
                    "   - software: cse, it, ai, or software specialization\n"
                    "   - hardware: ece, eee, biomedical, or hardware specialization\n"
                    "   - core: mech, civil\n"
                    "2. Resume Skills are secondary (40% weight).\n"
                    "3. If Specialization strongly conflicts with Course (e.g. Civil + Data Science), treat Course as Primary foundation and Specialization as dominant Secondary Track.\n"
                    "4. Output strict JSON with fields: 'course' (inferred), 'primaryDomain', 'secondaryDomains' (list), 'pathwayType', 'pathwayWeights'.\n"
                    "\n"
                    f"Degree: {degree}\n"
                    f"Institute: {institute_name}\n"
                    f"Specialization: {specialization}\n"
                    f"Skills: {', '.join(skills_list)}\n"
                    f"Projects: {str(projects)}\n"
                    "\n"
                    "Return JSON only."
                )
                
                # Call AI
                ai_resp = ask_llama("", pathway_prompt)      
                
                # Parse and Save
                import json
                import re
                try:
                    clean_json = re.sub(r'```json\s*|\s*```', '', ai_resp).strip()
                    pathway_data = json.loads(clean_json)
                    
                    # Add system fields
                    pathway_data['profileDerived'] = True
                    pathway_data['derivedAt'] = datetime.utcnow().isoformat()
                    pathway_data['derivationTrigger'] = "profile_creation"
                    
                    # Update Firestore
                    student.update(pathway_data)
                    print("✅ Career Pathway Saved to Firebase.")
                    
                except Exception as parse_err:
                    print(f"❌ Pathway Derivation Failed: {parse_err}")

        # --- ROADMAP GENERATION (ALWAYS UPDATE) ---
        try:
            print("🗺️ Generating Roadmap...")
            roadmap_prompt = (
                "Create a 5-step detailed learning roadmap for this student.\n"
                "JSON format list of objects: [{'title', 'description', 'status'}].\n"
                "Status options: 'Completed' (if they have skills), 'Focus' (next step), 'Locked' (future).\n"
                "\n"
                f"Course: {degree}\n"
                f"Specialization: {specialization}\n"
                f"Current Skills: {', '.join(skills_list)}\n"
                f"Goal Role: {specialization if specialization else 'Software Engineer'}\n"
                "\n"
                "Return JSON only."
            )
            
            roadmap_resp = ask_llama("", roadmap_prompt)
            import re
            import json
            clean_roadmap_json = re.sub(r'```json\s*|\s*```', '', roadmap_resp).strip()
            
            # Handle potential wrapping in quotes or dict
            try:
                roadmap_data = json.loads(clean_roadmap_json)
                
                # Check if wrapped in a key
                if isinstance(roadmap_data, dict):
                    # Try to find a list value or use the first key
                    for k, v in roadmap_data.items():
                        if isinstance(v, list):
                            roadmap_data = v
                            break
                
                if isinstance(roadmap_data, list):
                    student.update({'roadmap': roadmap_data})
                    print("✅ Roadmap Updated.")
                else:
                    print("⚠️ Roadmap format invalid (not a list).")
                    
            except json.JSONDecodeError:
                print("⚠️ Roadmap JSON Decode Error.")

        except Exception as r_err:
             print(f"❌ Roadmap Generation Error: {r_err}")

    except Exception as e:
        print(f"⚠️ Pathway Logic Error: {e}")

    return render_template('generated_resume.html', data=data)

# --- Pages ---

@app.route('/career')
def career():
    return render_template('career.html')

@app.route('/roadmap')
@login_required
def roadmap():
    student = Student.get_by_id(session['user_id'])
    return render_template('roadmap.html', student=student)

@app.route('/market')
@login_required
def market():
    student = Student.get_by_id(session['user_id'])
    
    if not student:
        flash('User not found.')
        return redirect(url_for('login'))
    
    # Check if analysis exists, if so render it to save API calls
    if student.market_analysis:
        return render_template('market.html', student=student, analysis=student.market_analysis)

    # Generate Analysis
    # FIRESTORE CHANGE: Get latest resume from subcollection
    resume = student.get_latest_resume()
    resume_text = resume['ocr_content'] if resume else "Student with basic Computer Science skills."

    print("Generating Market Analysis...")
    prompt = (
        "Analyze the current tech job market and this candidate's resume.\n"
        "1. Identify 3 High Paying 'Booming' Roles. For each, provide Avg Package (e.g. '$150k') and 3 specific skills they lack.\n"
        "2. Identify 2 Target Roles suitable for them. Estimate progress (0-100%) and provide strategic advice + 2 action items.\n"
        "Return strict JSON with keys: 'market_roles' and 'optimization'.\n"
        "Example:\n"
        "{\n"
        "  \"market_roles\": [{\"role\": \"AI Architect\", \"package\": \"$160k\", \"skills\": [\"LLMs\", \"System Design\"]}],\n"
        "  \"optimization\": [{\"role\": \"Backend Dev\", \"progress\": 60, \"advice\": \"Good Python, weak DB.\", \"actions\": [\"Learn Redis\", \"Build API\"]}]\n"
        "}\n\n"
        f"Resume Content: {resume_text[:2000]}"
    )

    response = ask_llama("", prompt)
    
    # Parse JSON
    import json
    import re
    clean_json = re.sub(r'```json\s*|\s*```', '', response).strip()
    try:
        # Find start/end brackets to be safe
        s = clean_json.find('{')
        e = clean_json.rfind('}')
        if s != -1 and e != -1:
            analysis_data = json.loads(clean_json[s:e+1])
            # FIRESTORE CHANGE: Update logic
            student.update({'market_analysis': analysis_data})
            return render_template('market.html', student=student, analysis=analysis_data)
    except Exception as e:
        print(f"Market Analysis Error: {e}")
    
    # Fallback empty
    return render_template('market.html', student=student, analysis=None)

@app.route('/mentors')
def mentors():
    return render_template('mentors.html')

@app.route('/stories')
def stories():
    return render_template('stories.html')

@app.route('/institution')
def institution():
    return render_template('institution.html')

@app.route('/support')
def support():
    return render_template('support.html')

@app.route('/profile') 
def profile():
    return render_template('profile.html')

@app.route('/skills') 
def skills():
    return render_template('skills.html')

# Initialize DB
# REMOVED: db.create_all() (Not needed for Firestore)

# -------------------------------
# ANALYSIS CONFIG (GITHUB/LEETCODE)
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
    "software": ["python", "java", "javascript", "react", "node", "flask", "django", "c++", "golang"],
    "data": ["machine learning", "ml", "pandas", "numpy", "pytorch", "tensorflow", "data analysis"],
    "hardware": ["arduino", "esp32", "embedded", "iot", "circuit", "pcb", "verilog", "fpga"],
    "web": ["html", "css", "react", "frontend", "backend", "full stack"],
    "core": ["matlab", "ansys", "solidworks", "cad", "simulation", "thermodynamics", "mechanics"]
}

REQUIRED_PROJECTS = {
    "software": ["backend api", "database integration", "full stack app"],
    "hardware": ["embedded system", "sensor interfacing", "iot dashboard"],
    "data": ["ml model deployment", "exploratory data analysis"],
    "core": ["simulation project", "design prototype"],
    "web": ["responsive website", "full stack app"]
}

# -------------------------------
# GITHUB HELPER FUNCTIONS
# -------------------------------
def get_github_repos(username):
    try:
        url = f"{GITHUB_API_BASE}/users/{username}/repos"
        res = requests.get(url, timeout=5)
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
    except:
        return []

def get_repo_languages(languages_url):
    try:
        res = requests.get(languages_url, timeout=5)
        if res.status_code != 200:
            return []
        return list(res.json().keys())
    except:
        return []

def classify_project(description, languages):
    text = (description + " " + " ".join(languages)).lower()
    scores = {d: 0 for d in PROJECT_DOMAIN_RULES}
    for domain, keywords in PROJECT_DOMAIN_RULES.items():
        for kw in keywords:
            if kw in text:
                scores[domain] += 1
    # If all scores 0, return unknown or default
    if max(scores.values()) == 0:
        return "unknown"
    return max(scores, key=scores.get)

def analyze_github(username):
    repos = get_github_repos(username)
    analysis = []
    domains_found = []
    for repo in repos:
        languages = get_repo_languages(repo["languages_url"])
        domain = classify_project(repo["description"], languages)
        if domain != 'unknown':
            domains_found.append(domain)
        analysis.append({
            "repo_name": repo["name"],
            "domain": domain,
            "languages": languages,
            "url": repo["html_url"]
        })
    return analysis, list(set(domains_found))

def detect_primary_domain(course):
    course = course.lower() if course else ""
    for key in COURSE_DOMAIN_MAP:
        if key in course:
            return COURSE_DOMAIN_MAP[key]
    return "software"

# -------------------------------
# ANALYSIS ROUTES
# -------------------------------
@app.route("/analyze", methods=["POST"])
@login_required 
def analyze_profile():
    data = request.json
    github_username = data.get("github_username")
    
    if not github_username:
        return jsonify({"error": "github_username is required"}), 400

    student = Student.get_by_id(session['user_id'])
    
    # 1. Determine Target Domains (Database + Input)
    primary_domain = student.data.get('primaryDomain')
    if not primary_domain:
         course_name = data.get("course") or student.data.get('degree', "")
         primary_domain = detect_primary_domain(course_name)
         
    secondary_domains = student.data.get('secondaryDomains', [])
    target_domains_str = f"{primary_domain}" + (f", {', '.join(secondary_domains)}" if secondary_domains else "")
    
    # 2. Fetch raw data from GitHub
    repos = fetch_github_data(github_username)
    if not repos:
        return jsonify({
            "error": "No data found",
            "projects": [], 
            "missing_projects": ["Could not fetch GitHub data"], 
            "github_domains_detected": [],
            "ai_suggestions": [],
            "career_readiness": "Unknown",
            "primary_domain": primary_domain
        })

    # 3. Prepare Context for LLaMA
    # Limit to top 15 repos to fit context window if needed, but 1000 tokens output is limit.
    # Input context can be larger.
    repo_summary = []
    for r in repos[:15]: 
        repo_summary.append(f"- Name: {r['name']} | Langs: {', '.join(r['languages'])} | Desc: {r['description']}")
    
    repo_text = "\n".join(repo_summary)

    # 4. Comprehensive LLaMA Analysis
    print(f"🤖 LLaMA Analysis for {github_username} on domain {target_domains_str}...")
    
    prompt = (
        f"Act as a Senior Tech Interviewer. Analyze these GitHub repositories for a student targeting: {target_domains_str}.\n\n"
        f"Repositories:\n{repo_text}\n\n"
        "Perform a comprehensive analysis and return a STRICT JSON object with these exact keys:\n"
        "1. \"repo_classifications\": A dictionary mapping EACH repo name to its specific technical domain (e.g., \"Web Dev\", \"ML\", \"IoT\").\n"
        "2. \"detected_domains\": A list of unique domains evident in their work.\n"
        "3. \"gaps\": A list of 2-3 critical missing project types or skills required for their target but missing in repos.\n"
        "4. \"readiness\": A string rating (\"Job Ready\", \"Good Progress\", \"Needs Improvement\", or \"Beginner\").\n"
        "5. \"suggestions\": A list of 3 high-impact project ideas. Each object must have: \"title\", \"description\", \"tech\".\n\n"
        "JSON ONLY. No markdown."
    )

    ai_response = ask_llama("", prompt)
    
    # 5. Parse and Format Response
    import json
    import re
    
    try:
        clean_json = re.sub(r'```json\s*|\s*```', '', ai_response).strip()
        analysis_data = json.loads(clean_json)
    except Exception as e:
        print(f"LLaMA Analysis Parse Error: {e} | Response: {ai_response}")
        # Fallback partial data
        analysis_data = {
            "repo_classifications": {},
            "detected_domains": [],
            "gaps": ["Error analyzing profile"],
            "readiness": "Analysis Failed",
            "suggestions": []
        }

    # 6. Construct Frontend Response
    # Map LLaMA classifications back to the repo list
    formatted_projects = []
    classifications = analysis_data.get("repo_classifications", {})
    
    for r in repos:
        # Use AI classification or fallback to language-based guess
        domain = classifications.get(r['name'])
        if not domain:
            # Fallback (simple heuristic if AI missed one)
            desc_lower = (r['description'] + " " + " ".join(r['languages'])).lower()
            if "html" in desc_lower or "react" in desc_lower: domain = "Web"
            elif "python" in desc_lower and "data" in desc_lower: domain = "Data/ML"
            elif "c++" in desc_lower or "arduino" in desc_lower: domain = "Embedded"
            else: domain = "General Config/Other"
            
        formatted_projects.append({
            "repo_name": r["name"],
            "domain": domain, # Used by frontend
            "languages": r["languages"],
            "url": r["url"]
        })

    response = {
        "github_user": github_username,
        "primary_domain": primary_domain,
        "secondary_domains": secondary_domains,
        "repo_count": len(repos),
        "projects": formatted_projects, # Matches frontend expectation
        "github_domains_detected": analysis_data.get("detected_domains", []),
        "missing_projects": analysis_data.get("gaps", []),
        "ai_suggestions": analysis_data.get("suggestions", []),
        "career_readiness": analysis_data.get("readiness", "Pending")
    }
    
    # Save to DB for record (optional but good practice)
    student.update({'last_github_analysis': response})

    return jsonify(response)

@app.route('/analysis')
@login_required
def analysis():
    student = Student.get_by_id(session['user_id'])
    return render_template('analysis.html', student=student)

# -------------------------------
# AI CHATBOT ROUTE
# -------------------------------
@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.json
    user_message = data.get('message')
    history = data.get('history', []) # Expects list of {role, content}
    
    if not user_message:
        return jsonify({'error': 'Message required'}), 400
        
    student = Student.get_by_id(session['user_id'])
    
    # 1. Construct Context System Prompt
    # Extract relevant student info
    
    # Skills
    skills_list = [s['skill_name'] for s in student.verified_skills if s.get('verified')]
    skills_str = ", ".join(skills_list) if skills_list else "None verified yet"
    
    # Domain
    domain = student.data.get('primaryDomain', 'General Engineering')
    secondary = ", ".join(student.data.get('secondaryDomains', []))
    
    # Roadmap context (optional, simple summary)
    current_roadmap = "Not generated"
    if student.roadmap:
        # Just take the first incomplete step
        for step in student.roadmap:
            if step['status'] == 'Focus':
                current_roadmap = f"Focusing on: {step['title']} - {step['description']}"
                break
    
    system_prompt = (
        f"You are EduBot, an AI mentor for {student.name}.\n"
        f"Student Profile:\n"
        f"- Course: {student.department} (Year {student.enrollment_year})\n"
        f"- Target Domain: {domain} {f'({secondary})' if secondary else ''}\n"
        f"- Verified Skills: {skills_str}\n"
        f"- Current Goal: {current_roadmap}\n\n"
        "Instructions:\n"
        "1. Answer questions based on their specific skills and domain.\n"
        "2. If they ask about learning, refer to their gaps or next roadmap steps.\n"
        "3. Be encouraging, professional, and concise.\n"
        "4. Do NOT explicitly mention 'I checked your database record'. Just know the facts.\n"
    )
    
    # 2. Build Message Chain
    # We shouldn't trust client history blindly for system prompt, so we prepend system prompt here.
    # History from client should be just user/assistant exchange.
    
    # Limit history to last 6 messages to save tokens
    trimmed_history = history[-6:] 
    
    messages = [{"role": "system", "content": system_prompt}] + trimmed_history + [{"role": "user", "content": user_message}]
    
    # 3. Call AI
    ai_response = chat_llama(messages)
    
    return jsonify({
        "reply": ai_response
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)