import os
import json
import logging
import csv
import re
from datetime import datetime
from pydub import AudioSegment
from openai import OpenAI
import google.generativeai as genai
from json_repair import repair_json
import streamlit as st

# --- THE SMART SWITCH ---
# 1. If on the Cloud, use the Vault.
# 2. If on Laptop, use the keys below.
if "OPENAI_API_KEY" in st.secrets:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    # --- PASTE YOUR REAL KEYS HERE FOR LOCAL TESTING ---
    OPENAI_API_KEY = "sk-..." 
    GEMINI_API_KEY = "AIza..."

# --- SETUP ---
logging.basicConfig(level=logging.INFO, format='%(message)s')
client = OpenAI(api_key=OPENAI_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)

# Smart PDF Import
try:
    from weasyprint import HTML
    PDF_AVAILABLE = True
except (ImportError, OSError):
    PDF_AVAILABLE = False

class StrataEngine:
    def __init__(self):
        self.model_id = 'gemini-2.5-flash'
        self.model = genai.GenerativeModel(self.model_id)

    def process_audio_robust(self, file_path):
        logging.info(f"🎧 Loading audio: {file_path}...")
        try:
            audio = AudioSegment.from_file(file_path)
        except Exception as e:
            raise ValueError(f"Could not load audio: {e}")

        audio = audio.normalize()
        # Chunking: 10 mins with 30s overlap
        chunk_length_ms = 10 * 60 * 1000
        overlap_ms = 30 * 1000
        chunks = []
        start = 0
        
        while start < len(audio):
            end = min(start + chunk_length_ms, len(audio))
            chunks.append(audio[start:end])
            if end == len(audio): break
            start += (chunk_length_ms - overlap_ms)

        full_transcript = ""
        for i, chunk in enumerate(chunks):
            chunk_name = f"temp_chunk_{i}.mp3"
            chunk.export(chunk_name, format="mp3", bitrate="64k")
            try:
                with open(chunk_name, "rb") as f:
                    res = client.audio.transcriptions.create(model="whisper-1", file=f)
                    full_transcript += res.text + " "
            finally:
                if os.path.exists(chunk_name): os.remove(chunk_name)
        
        return full_transcript

    def analyze_text(self, transcript, strata_plan="SP [Unknown]"):
        today_str = datetime.now().strftime("%d %B %Y")
        
        prompt = f"""
        ROLE: Professional Strata Managing Agent (NSW/VIC jurisdiction).
        CONTEXT: Today's date is {today_str}. Strata Plan: {strata_plan}.
        TASK: Convert transcript to strict, legally compliant minutes following Agency Standards.
        
        INPUT TRANSCRIPT:
        {{transcript}}

        LEGAL GUIDELINES (STRICT):
        1. QUORUM: Check attendees. If valid, state: "A quorum was declared pursuant to Schedule 1 of the Strata Schemes Management Act."
        2. MOTIONS: Use the phrasing "That the Owners Corporation RESOLVED to..." for decisions.
        3. STATUS: Append "(CARRIED)" or "(DEFEATED)" to the end of every Item Title.
        4. VOICE: Strict Passive Voice. (e.g. "It was noted that..." NOT "Dave said...").
        5. DATES/TIMES: If not explicitly spoken, use "Not Recorded". Do not guess.

        FORMATTING RULES:
        - Header Style: "MINUTES OF STRATA COMMITTEE MEETING"
        - Item numbering: "Item 1:", "Item 2:" (Do not use "3.1" or "Motion 1").
        - EMAIL DRAFT: Subject and Body ONLY. Do not include a sign-off or signature.

        OUTPUT FORMAT (JSON ONLY):
        {{{{
            "meeting_metadata": {{{{ "date": "...", "time_commenced": "...", "attendees": "...", "strata_plan": "{strata_plan}" }}}},
            "minutes_html_body": "<p><em>A quorum was declared...</em></p><h3>Item 1: [Title] (CARRIED)</h3><p>That the Owners Corporation RESOLVED to...</p>...",
            "action_list": [ {{{{ "task": "...", "assignee": "...", "priority": "..." }}}} ],
            "email_draft": "Subject: ... Body: ..."
        }}}}
        """
        try:
            response = self.model.generate_content(prompt.format(transcript=transcript))
            return json.loads(repair_json(response.text))
        except Exception:
            return {}

    def clean_markdown(self, text):
        if not text: return ""
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text) # Remove bold
        text = re.sub(r'#{1,6}\s?', '', text)         # Remove headers
        return text

    def generate_pdf(self, data, filename):
        if not PDF_AVAILABLE: return None
        
        # PRO LEVEL STYLING (Mimicking the Agency PDF)
        html = f"""
        <html><head><style>
            body {{ font-family: 'Helvetica', sans-serif; padding: 40px; line-height: 1.5; font-size: 11pt; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            h1 {{ font-size: 16pt; margin-bottom: 5px; text-transform: uppercase; }}
            h2 {{ font-size: 12pt; margin-top: 0; font-weight: normal; color: #555; }}
            .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            .meta-table td {{ padding: 5px; border-bottom: 1px solid #eee; }}
            .label {{ font-weight: bold; width: 150px; }}
            h3 {{ margin-top: 20px; font-size: 12pt; border-bottom: 1px solid #000; padding-bottom: 3px; }}
            p {{ margin-bottom: 10px; text-align: justify; }}
        </style></head><body>
            
            <div class="header">
                <h1>Minutes of Meeting</h1>
                <h2>Strata Plan {data.get('meeting_metadata', {}).get('strata_plan', 'N/A')}</h2>
            </div>

            <table class="meta-table">
                <tr><td class="label">Date:</td><td>{data.get('meeting_metadata', {}).get('date', 'Not Recorded')}</td></tr>
                <tr><td class="label">Commenced:</td><td>{data.get('meeting_metadata', {}).get('time_commenced', 'Not Recorded')}</td></tr>
                <tr><td class="label">Attendees:</td><td>{data.get('meeting_metadata', {}).get('attendees', 'Not Recorded')}</td></tr>
            </table>

            {data.get('minutes_html_body', '<p>No minutes generated.</p>')}
            
            <br><br>
            <p style="text-align: center; font-size: 9pt; color: #888;">Generated by StrataScribe</p>
        </body></html>
        """
        HTML(string=html).write_pdf(filename)
        return filename

    def generate_csv(self, data, filename="Action_List.csv"):
        actions = data.get('action_list', [])
        if not actions: return None
        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["Priority", "Assignee", "Task"])
            for item in actions:
                writer.writerow([item.get('priority'), item.get('assignee'), item.get('task')])
        return filename