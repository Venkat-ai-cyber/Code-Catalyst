from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__, template_folder='../templates', static_folder='../static')

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

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

@app.route('/profile') # Kept for backward compatibility/sub-routing
def profile():
    return render_template('profile.html')

@app.route('/skills') # Kept for backward compatibility/sub-routing
def skills():
    return render_template('skills.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)
