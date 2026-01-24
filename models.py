from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True) # made nullable for now to avoid immediate break, but logic will require it
    enrollment_year = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    leetcode_username = db.Column(db.String(100), nullable=True)
    
    # Suitability Scores (0-100)

    sde_score = db.Column(db.Integer, default=0)
    fsd_score = db.Column(db.Integer, default=0)
    ai_score = db.Column(db.Integer, default=0)
    
    # Dynamic Top Roles - Stores JSON list [{'role': '...', 'score': 90}, ...]
    top_roles = db.Column(db.JSON, nullable=True)
    
    # Dynamic Roadmap - Stores JSON list [{'title': '...', 'description': '...', 'status': '...'}, ...]
    roadmap = db.Column(db.JSON, nullable=True)
    
    # Market Analysis - Stores JSON { 'market_roles': [...], 'optimization': [...] }
    market_analysis = db.Column(db.JSON, nullable=True)

    # Gamification
    xp = db.Column(db.Integer, default=0)
    last_bounty_date = db.Column(db.Date, nullable=True) # Tracks when the daily bounty was solved
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    academic_records = db.relationship('AcademicRecord', backref='student', lazy=True)
    skills = db.relationship('Skill', backref='student', lazy=True)
    career_goals = db.relationship('CareerGoal', backref='student', lazy=True)
    resumes = db.relationship('Resume', backref='student', lazy=True)

class AcademicRecord(db.Model):
    __tablename__ = 'academic_records'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    gpa = db.Column(db.Float, nullable=False)
    courses = db.Column(db.JSON, nullable=True)

class Skill(db.Model):
    __tablename__ = 'skills'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    skill_name = db.Column(db.String(100), nullable=False)
    proficiency_level = db.Column(db.Integer, nullable=False) # 1-10
    verified = db.Column(db.Boolean, default=False)
    
    # Prevent duplicate skills for the same student
    __table_args__ = (db.UniqueConstraint('student_id', 'skill_name', name='_student_skill_uc'),)

class CareerGoal(db.Model):
    __tablename__ = 'career_goals'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    target_role = db.Column(db.String(100), nullable=False)
    target_industry = db.Column(db.String(100), nullable=False)

class Resume(db.Model):
    __tablename__ = 'resumes'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    ocr_content = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
