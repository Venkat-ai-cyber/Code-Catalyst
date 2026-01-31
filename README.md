# 🎓 EduTrack  
### AI-Powered Career Navigation & Readiness Platform

EduTrack is an **AI-driven career navigation system** designed to help students understand **where they stand in their career journey**, **what skills or projects they are missing**, and **what to do next** to progress toward their desired career roles.

Instead of providing static career suggestions, EduTrack generates **progress-based career pathways** anchored to a student’s **academic background**, enhanced by their **resume, projects, and GitHub activity**.

---

## 📌 Table of Contents
- Problem Statement  
- Solution Overview  
- Key Features  
- How EduTrack Works  
- GitHub Analysis (Project Readiness)  
- Career Pathway & Progress Logic  
- Tech Stack  
- System Architecture  
- Setup & Installation  
- API Overview  
- Performance Optimizations  
- Supported Domains  
- Hackathon Context  
- Future Enhancements  
- Team  

---

## ❌ Problem Statement

Students often struggle with career planning due to:
- Fragmented platforms for learning and project building  
- Lack of personalized, measurable career guidance  
- Difficulty understanding career readiness  
- Unclear next steps after completing courses  

While students gain skills and work on projects, there is no unified system that connects:
**academic background → skills → projects → career readiness**

As a result, students rely on guesswork instead of informed decisions.

---

## ✅ Solution Overview

**EduTrack** acts as a **career GPS** for students.

By analyzing a student’s **resume** and **GitHub profile**, EduTrack:
- Anchors career guidance to the student’s **academic discipline**
- Verifies skills using **real project evidence**
- Supports **interdisciplinary and integrated profiles**
- Generates a **step-by-step career pathway**
- Tracks **percentage-based progress**
- Clearly explains what is missing and what to do next

---

## 🌟 Key Features

### 📄 Resume-Based Career Anchoring
- Resume upload (PDF / image)
- OCR using **EasyOCR**
- Degree and branch extracted as the **primary career anchor**
- Prevents unrealistic or misleading career recommendations

---

### 🛤️ Dynamic Career Pathways
- Role-specific pathways generated automatically
- Each pathway step includes:
	- Required skills
	- Completion percentage
	- Verified vs missing skills
	- Clear next action for improvement

---

### 🧩 Integrated & Interdisciplinary Profiles
- Supports students working across domains (e.g., AI + IoT)
- Maintains:
	- **Primary pathway** based on academic course
	- **Secondary tracks** based on projects and GitHub
- Uses weighted scoring for realistic guidance

---

### 🧑‍💻 GitHub Project Analysis (Readiness-Oriented)
- GitHub profile or repository link input
- Uses GitHub REST API to analyze:
	- Repositories
	- Languages used
	- README descriptions
- Maps projects to career pathway steps
- Identifies **missing real-world project types**
- Measures **practical engineering readiness**

---



```