import os
import sys
import requests
import json
import re
from dotenv import load_dotenv
from sqlalchemy import func
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import easyocr
from functools import wraps

# Append parent dir to path to import models if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Ensure you have a models.py file with these defined
from models import db, Student, Resume, Skill

# -------------------------------
# LLaMA / OpenRouter Config
# -------------------------------
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")
URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3-8b-instruct"

if not API_KEY:
    print("WARNING: OPENROUTER_API_KEY not set in .env")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = 'super_secret_key'

# --- Configuration ---
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'instance', 'education_tracker.db')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = '../static/uploads/resumes'

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.dirname(db_path), exist_ok=True)

db.init_app(app)

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
def ask_llama(resume_text, question):
    if not API_KEY:
        return "API Key missing."
        
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Answer briefly. No explanation. Simple words only."
            },
            {
                "role": "user",
                "content": f"Resume Text:\n{resume_text}\n\nQuestion:\n{question}"
            }
        ],
        "temperature": 0.2,
        "max_tokens": 300  # Increased slightly to ensure JSON isn't cut off
    }

    try:
        response = requests.post(URL, headers=HEADERS, json=payload)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        else:
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
        
        student = Student.query.filter_by(email=email).first()
        
        if student and student.password_hash and check_password_hash(student.password_hash, password):
            session['user_id'] = student.id
            session['user_name'] = student.name
            return redirect(url_for('dashboard'))
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
        
        if Student.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('signup'))
        
        hashed_password = generate_password_hash(password)
        new_student = Student(
            name=name, 
            email=email, 
            password_hash=hashed_password,
            department=department,
            enrollment_year=int(enrollment_year)
        )
        
        db.session.add(new_student)
        db.session.commit()
        
        session['user_id'] = new_student.id
        session['user_name'] = new_student.name
        
        return redirect(url_for('dashboard'))
        
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
    student = Student.query.get(session['user_id'])
    
    if not student:
        session.clear()
        flash('Session expired. Please login again.')
        return redirect(url_for('login'))
    
    # Use dynamic top_roles if available, otherwise empty
    top_roles = getattr(student, 'top_roles', []) or []
    
    # Sort just in case LLaMA returned unsorted
    try:
        if isinstance(top_roles, list):
            top_roles.sort(key=lambda x: x.get('score', 0), reverse=True)
    except Exception as e:
        print(f"Sorting error: {e}") 

    # Prepare data for frontend
    best_role = top_roles[0] if top_roles else None
    
    # Fetch Verified Skills
    verified_skills = Skill.query.filter_by(student_id=student.id, verified=True).all()
    
    scores = {
        'roles': top_roles,
        'best_fit': best_role['role'] if best_role else 'N/A',
        'best_score': best_role['score'] if best_role else 0
    }

    return render_template('dashboard.html', student=student, scores=scores, verified_skills=verified_skills)

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
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # 2. OCR and Analysis Processing (FIXED: Moved Inside Function)
        try:
            reader = get_reader()
            results = reader.readtext(filepath, detail=0) 
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
                 student = Student.query.get(student_id)
                 if student:
                     print(f"DEBUG: Found logged-in student [ID: {student_id}]")
            
            if not student:
                # Handle guest uploads or missing sessions gracefully
                # For this fix, we assume login is required or we create a dummy, 
                # but usually, you should use @login_required on this route.
                flash('Please login to save resume data.')
                return redirect(url_for('login'))

            # Update Student Top Roles
            # Note: Ensure your Student model has a 'top_roles' column (JSON type)
            student.top_roles = top_roles_data
            
            # Create Resume Record
            new_resume = Resume(student_id=student.id, filename=filename, ocr_content=extracted_text)
            db.session.add(new_resume)
            
            db.session.commit()
            print("DEBUG: Database commit successful.")
            
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
        # Ensure certs folder exists
        cert_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'certs')
        os.makedirs(cert_folder, exist_ok=True)
        filepath = os.path.join(cert_folder, filename)
        file.save(filepath)
        
        # 1. OCR (Reuse get_reader)
        try:
            reader = get_reader()
            results = reader.readtext(filepath, detail=0) 
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
                student_id = session['user_id']
                # Check if skill exists (Case-Insensitive using func.lower)
                existing_skill = Skill.query.filter(
                    Skill.student_id == student_id, 
                    func.lower(Skill.skill_name) == skill_name.lower()
                ).first()
                
                if existing_skill:
                    # Update status if needed, but don't duplicate
                    if not existing_skill.verified:
                        existing_skill.verified = True
                        flash(f"Skill '{skill_name}' is now verified!")
                    else:
                        flash(f"Skill '{skill_name}' was already verified.")
                else:
                    new_skill = Skill(student_id=student_id, skill_name=skill_name, proficiency_level=5, verified=True) # Default level 5
                    db.session.add(new_skill)
                    flash(f"Skill '{skill_name}' added and verified!")
                
                db.session.commit()
            else:
                flash("Could not verify certificate. Please upload a clear image of a valid certificate.")
                
        except Exception as e:
             print(f"Error processing certificate: {e}")
             flash("Error processing certificate.")

    return redirect(url_for('dashboard'))

@app.route('/leetcode')
@login_required
def leetcode():
    student = Student.query.get(session['user_id'])
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

    # Store username
    student = Student.query.get(session['user_id'])
    if student:
        student.leetcode_username = username
        db.session.commit()

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
    
    # Check if request came from leetcode page or dashboard
    if request.form.get('source_page') == 'leetcode':
        return redirect(url_for('leetcode'))
        
    return redirect(url_for('dashboard'))

# --- Pages ---

@app.route('/career')
def career():
    return render_template('career.html')

@app.route('/roadmap')
def roadmap():
    return render_template('roadmap.html')

@app.route('/market')
def market():
    return render_template('market.html')

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
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)