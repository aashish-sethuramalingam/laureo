"""Creates sample_data/students.xlsx: 50 fictional students with deliberate mistakes for the demo.

Run:  python make_sample_data.py
"""
import datetime
import os

import pandas as pd

NAMES = [
    "Ishaan Kapoor", "Meghana Reddy", "Arnav Joshi", "Sanjana Pillai", "Kabir Malhotra",
    "Tanisha Bose", "Vihaan Deshmukh", "Riya Fernandes", "Aryan Choudhary", "Nandini Iyer",
    "Dhruv Saxena", "Pranavi Rao", "Yash Thakur", "Ananya Krishnan", "Siddharth Menon",
    "Harshita Agarwal", "Rudra Patil", "Diya Banerjee", "Aditya Varma", "Keerthana Subramanian",
    "Reyansh Mehta", "Sneha Kulkarni", "Vivaan Sinha", "Lavanya Nair", "Arjun Rathore",
    "Shreya Ghosh", "Krishna Teja", "Aisha Siddiqui", "Neil D'Souza", "Pooja Hegde",
    "Om Prakash Yadav", "Ira Chatterjee", "Rohan Gill", "Bhavya Shetty", "Samar Kaur",
    "Tejaswini Naidu", "Aarush Bhatt", "Mahima Jain", "Karan Sethi", "Divya Murthy",
    "Zoya Khan", "Pranav Hegde", "Charvi Mishra", "Hrithik Pandey", "Gayatri Raman",
    "Anirudh Srinivasan", "Esha Tiwari", "Jayant Bhosale", "Navya Gowda", "Rehan Qureshi",
]
AWARDS = {0: "Winner", 1: "First Runner-up", 2: "Second Runner-up", 3: "Best Design", 4: "Most Innovative Idea"}

rows = []
for i, name in enumerate(NAMES):
    sid = f"se26u{i + 1:03d}"
    first = name.split()[0].lower().replace("'", "")
    last = name.split()[-1].lower().replace("'", "")
    rows.append({
        "Student Name": name,
        "Student ID": sid.upper(),
        "Student Email": f"{sid}@college.edu.in",
        "Personal Email": f"{first}.{last}{i + 1}@gmail.com",
        "Event": "IEEE Hackathon 2026",
        "Certificate Type": "Merit" if i in AWARDS else "Participation",
        "Achievement": AWARDS.get(i, "Participation"),
        "Date": datetime.datetime(2026, 11, 4),
    })

# Planted problems the app must catch (row numbers are Excel rows: data starts on row 2)
rows[4]["Student Name"] = "  TANISHA   bose "                        # row 6: messy name, auto-formatted
rows[9]["Student Name"] = ""                                         # row 11: missing name
rows[14]["Student Email"] = ""                                       # row 16: empty email, fallback used
rows[19]["Student Email"] = "keerthana-at-college"                   # row 21: invalid email...
rows[19]["Personal Email"] = ""                                      #         ...and no fallback
rows[26]["Student Email"] = ""                                       # row 28: typo in the fallback
rows[26]["Personal Email"] = "krishna.teja27@gmial.com"
rows[33]["Student Email"] = "bounce.test@college.edu.in"             # row 35: fails on send (demo retry)
rows[45]["Student Name"] = "Anirudh Venkata Lakshmi Narasimha Srinivasan"  # row 47: very long name
rows.append(dict(rows[7]))                                           # row 52: duplicate of row 9
rows.append(dict(rows[22]))                                          # row 53: duplicate of row 24

os.makedirs("sample_data", exist_ok=True)
pd.DataFrame(rows).to_excel("sample_data/students.xlsx", index=False)
print(f"Wrote sample_data/students.xlsx with {len(rows)} rows")
