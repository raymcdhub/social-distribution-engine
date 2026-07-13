"""Social media caption generation via Groq (Llama 3.3 70B)."""

import os

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

PROMPT_TEMPLATE = """THE HomeShare facilitates homesharing arrangements, which are made up of two parties ( a sharer- a younger person (21 yo min) who needs an accommodation and needs to provide 10 hours per week of companionship and support. The older person, the householder, needs to live in their own house with some extra help from the sharer. so it's a mutually beneficial arrangement where everybody wins.
Consider this Instagram listing:
🏡 ROOM AVAILABLE — Delgany, Co. Wicklow
female sharer | 21+ | Animal lover | Non-smoker
✅ Double bedroom with private bathroom
✅ Shared kitchen & cosy sitting room
✅ Off-street parking
✅ Beautiful location in Delgany (A63)
🚌 25 mins by bus · 5 min drive to Delgany Village
🚙 15 min drive to Bray (~30 by bus)
🛣️ Easy M11 access to Dublin & Wicklow
💶 €355/month (in exchange for 10 hrs/week support & companionship)
👉 Apply at https://thehomeshare.ie/find-a-home-online-application-form/

Recreate this post using this new listing. If the new listing mentions Help4Housing, PLEASE DO ALSO. if the new listing mentions another price, PLEASE DO ALSO. Keep the format and tone, just change the relevant information about this new opportunity, just return the post caption ready to copy and paste. Note: the link never changes. The URL is always the same.

New listing:
Title: {title}
Location: {location}
Programme: {programme}
Gender preference: {gender}

Description:
{description}
"""


def generate_caption(listing):
    api_key = os.environ["GROQ_API_KEY"]
    prompt = PROMPT_TEMPLATE.format(
        title=listing["title"],
        location=listing["location"],
        programme=listing["programme"],
        gender=listing["gender"],
        description=listing["description"],
    )

    response = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()
