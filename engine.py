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
if "OPENAI_API_KEY" in st.secrets:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    # PASTE YOUR KEYS HERE FOR LOCAL USE
    OPENAI_API_KEY = ""
    GEMINI_API_KEY = ""

# --- SETUP ---
logging.basicConfig(level=logging.INFO, format='%(message)s')
client = OpenAI(api_key=OPENAI_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)

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

    def analyze_text(self, transcript):
        today_str = datetime.now().strftime("%d %B %Y")
        
        prompt = f"""
        ROLE: Professional Strata Managing Agent (NSW/VIC jurisdiction).
        CONTEXT: Today's date is {today_str}.
        TASK: Convert transcript to strict legal minutes.
        
        INPUT TRANSCRIPT:
        {{transcript}}

        LEGAL GUIDELINES:
        1. Passive Voice Only.
        2. No Defamation.
        3. Action Items must be imperative.
        4. DATES: If unknown, use {today_str}.
        
        FORMATTING RULES:
        - Use "Item 1:", "Item 2:" structure.
        - EMAIL DRAFT: Generate the Subject and Body ONLY. Do NOT include a sign-off (e.g., "Sincerely", "Regards") or a signature block. End with the final sentence of the body.

        OUTPUT FORMAT (JSON ONLY):
        {{{{
            "meeting_metadata": {{{{ "date": "DD/MM/YYYY", "attendees": "..." }}}},
            "minutes_html_body": "<h3>Item 1: Title</h3><p>Resolution text...</p>...",
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
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'#{1,6}\s?', '', text)
        return text

    def generate_pdf(self, data, filename):
        if not PDF_AVAILABLE: return None
        html = f"""
        <html><head><style>
            body {{ font-family: Helvetica, sans-serif; padding: 40px; line-height: 1.6; }}
            h1 {{ border-bottom: 2px solid #333; padding-bottom: 10px; }}
            h3 {{ margin-top: 20px; color: #2c3e50; border-bottom: 1px solid #eee; }}
            .meta {{ color: #666; font-size: 0.9em; margin-bottom: 30px; }}
        </style></head><body>
            <h1>MINUTES OF MEETING</h1>
            <div class="meta">
                <p><strong>Date:</strong> {data.get('meeting_metadata', {}).get('date', 'Not Recorded')}</p>
            </div>
            {data.get('minutes_html_body', '<p>No minutes generated.</p>')}
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