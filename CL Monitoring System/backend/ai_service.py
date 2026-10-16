import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")

client = genai.Client(api_key=GEMINI_API_KEY)


def analyze_ticket(description: str):

    prompt = f"""
You are the AI troubleshooting assistant for Centrum Laboratory.

A computer laboratory technician reported this problem:

"{description}"

Your task is to create a clear, step-by-step troubleshooting guide.

Use EXACTLY this format:

Category:
[hardware, software, network, system, or other category]

Possible Cause:
[brief explanation]

Priority:
[Low, Medium, or High]

Step-by-Step Troubleshooting:
1. [First action]
   Check: [What the technician should observe or verify]

2. [Second action]
   Check: [What the technician should observe or verify]

3. [Third action]
   Check: [What the technician should observe or verify]

4. [Next action]
   Check: [What the technician should observe or verify]

5. [Next action]
   Check: [What the technician should observe or verify]

Recommended Solution:
[What should be done if the problem is identified]

Escalation:
[When the technician should escalate the problem]

IMPORTANT RULES:
- Provide at least 5 troubleshooting steps when possible.
- Start with the safest and simplest troubleshooting step.
- Make each step specific and actionable.
- Explain what the technician should check after each step.
- If a step fixes the problem, tell the technician to stop.
- Do not skip directly to replacing hardware.
- Do not instruct the technician to open a power supply or handle exposed electrical components.
- Do not recommend dangerous procedures.
- If specialized hardware repair is required, recommend escalation.
- Use simple language suitable for a computer laboratory technician.
- Do not give a general summary instead of the step-by-step process.
"""

    interaction = client.interactions.create(model="gemini-3.8-flash", input=prompt)

    return interaction.output_text
