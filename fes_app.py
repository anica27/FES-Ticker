import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import time
from datetime import datetime
from google import genai

# ==========================================
# 1. KONFIGURATION (LÄDT AUS SECRETS)
# ==========================================
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
BOT_TOKEN = st.secrets.get("BOT_TOKEN", "")
CHANNEL_ID = st.secrets.get("CHANNEL_ID", "")
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
# ==========================================

ai_client = genai.Client(api_key=GEMINI_API_KEY.strip()) if GEMINI_API_KEY else None

BASE_URL = "https://www.fes.de"
OVERVIEW_URL = "https://www.fes.de/landesbuero-sachsen/veranstaltungen-rueckblicke"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()

def markdown_to_telegram_html(text: str) -> str:
    """Wandelt eventuelle Markdown-Reste zuverlässig in Telegram-kompatibles HTML um."""
    if not text:
        return ""
    # Fett: **Text** oder __Text__ -> <b>Text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # Kursiv: *Text* oder _Text_ -> <i>Text</i>
    text = re.sub(r'(?<!^)(?<!\n)\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'(?<![a-zA-Z0-9])_(.+?)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)
    return text

def send_telegram_post(content: str, uploaded_image=None) -> bool:
    """Sendet Bild- oder Textnachricht mit HTML-Unterstützung."""
    token = BOT_TOKEN.strip()
    chat_id = CHANNEL_ID.strip()

    if uploaded_image is not None:
        endpoint = f"https://api.telegram.org/bot{token}/sendPhoto"
        files = {
            "photo": (uploaded_image.name, uploaded_image.getvalue(), uploaded_image.type)
        }
        data = {
            "chat_id": chat_id,
            "caption": content,
            "parse_mode": "HTML"
        }
        try:
            resp = requests.post(endpoint, data=data, files=files, timeout=20)
            return resp.status_code == 200
        except Exception as err:
            st.error(f"Fehler beim Bild-Upload: {err}")
            return False

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": content,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(endpoint, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as err:
        st.error(f"Verbindungsfehler: {err}")
        return False

def generate_post_with_gemini(raw_text: str, url: str):
    """Erstellt den ausführlichen Einzelpost für Telegram mit validen HTML-Tags."""
    if not ai_client:
        return None, "Kein GEMINI_API_KEY konfiguriert."

    prompt = (
        "Du bist Redakteur:in für den Telegram-Kanal der Friedrich-Ebert-Stiftung Sachsen.\n"
        "Erstelle aus dem folgenden Veranstaltungstext eine prägnante, hochwertige Telegram-Nachricht.\n\n"
        "STRIKTE FORMATIERUNGS-REGELN:\n"
        "1. Verwende AUSSCHLIESSLICH HTML-Tags: <b>Text</b> für fett und <i>Text</i> für kursiv.\n"
        "2. KEINE Markdown-Syntax, keine doppelten Sternchen (**), keine einfachen Sternchen (*).\n"
        "3. Jedes <b> und <i> muss korrekt wieder geschlossen werden (</b> bzw. </i>).\n"
        "4. Direkte, nahbare Du-Ansprache ('Sei dabei', 'Erlebe', 'Entdecke').\n\n"
        "STRIKTE REGELN ZU DEN PERSONEN (Mit dabei):\n"
        "- Nutze für jede Person zwingend einen Aufzählungspunkt mit dem Zeichen '•' und Trennung per Gedankenstrich '–'.\n"
        "- Schema je Zeile: • [Titel] [Vorname Nachname] – [Institution / Funktion / Fachbereich] (ggf. [als Rolle])\n"
        "- Schreibe NIEMALS bloß den reinen Stadtnamen (z. B. VERBOTEN: 'Name – Leipzig')! Nenne immer die Institution, den Sender, das Medium oder die Universität.\n"
        "- Falls Personen in historische oder philosophische Rollen schlüpfen, ergänze am Ende in Klammern: (als Rolle).\n"
        "- Falls keine Personen im Text genannt sind, den gesamten Block 'Mit dabei:' weglassen.\n\n"
        "INHALTLICHE VORGABEN ZUM HOOK:\n"
        "- Formuliere 1 bis maximal 2 Sätze Leitfrage oder packenden Einstieg zum Kern der Veranstaltung.\n"
        "- Fordere NICHT pauschal zum 'Mitdiskutieren' auf, wenn es sich um ein Schau-/Rollengespräch, "
        "ein Podium oder eine Lesung handelt! Lade stattdessen zum Zuhören, Erleben und Dabeisein ein.\n\n"
        "Nutze exakt folgendes Ausgabe-Schema:\n\n"
        "🔴 <b>Friedrich-Ebert-Stiftung Sachsen</b>\n"
        "🗣️ <b>[Format, z. B. Bürgergespräch / Fachgespräch / Szenische Diskussion / Lesung]</b>:\n"
        "<b>„[TITEL DER VERANSTALTUNG]“</b>\n\n"
        "[1–2 Sätze packender Einstieg zur Kernfrage des Abends, der Neugier weckt]\n\n"
        "<b>Mit dabei:</b>\n"
        "• Thomas Härrsch – ZDF Landesstudio Sachsen\n"
        "• Dr. Judith Kretzschmar – Universität Leipzig (Zentrum Journalismus und Demokratie)\n"
        "(ersetze diese Beispielzeilen durch die tatsächlichen Personen aus dem Text im exakt selben Stil: • Name – Institution / Funktion)\n\n"
        "<b>Moderation:</b> [Name, Funktion/Institution, falls vorhanden, sonst Zeile weglassen]\n\n"
        "🗓 [Wochentag, Datum | Uhrzeit – zwingend dem Block 'Termin' entnehmen]\n"
        "📍 [Veranstaltungsort mit vollständiger Adresse]\n"
        "📝 [Anmeldeschluss: Wochentag, Datum – NUR falls Anmeldefrist vorhanden, sonst Zeile weglassen]\n"
        f"🔗 {url}\n\n"
        "Wichtig: Gib NUR den finalen Nachrichtentext aus, keine Erklärungen davor oder danach.\n\n"
        f"Webseitentext:\n{raw_text[:14000]}"
    )

    models_to_try = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    ]

    last_error = ""
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response.text:
                    clean_output = markdown_to_telegram_html(response.text.strip())
                    return clean_output, None
            except Exception as e:
                last_error = str(e)
                time.sleep(1.5)

    return None, last_error

def generate_instagram_caption_with_gemini(raw_text: str, url: str):
    """Erstellt eine Instagram-Caption nach dem exakten CI-Stil der FES Sachsen mit faktenbasierter Barrierefreiheit."""
    if not ai_client:
        return None, "Kein GEMINI_API_KEY konfiguriert."

    prompt = (
        "Du bist Social-Media-Redakteur:in für den Instagram-Kanal der Friedrich-Ebert-Stiftung Sachsen (@fes_sachsen).\n"
        "Erstelle aus dem folgenden Veranstaltungstext eine Instagram-Caption.\n\n"
        "STRIKTE FORMATIERUNGS-REGELN:\n"
        "1. Verwende KEINE HTML-Tags (kein <b>, kein <i>) und KEINE Markdown-Sternchen (** oder *).\n"
        "2. Halte dich exakt an die vorgegebenen Emojis, Zeilenumbrüche und Satzformate.\n\n"
        "INHALTLICHE VORGABEN:\n"
        "- BESCHREIBUNGSTEXT EXTREM KURZ: Maximal 2 bis 3 prägnante Sätze (oder 1 kurzer Absatz) zum inhaltlichen Kern/Spannungsfeld! Keine langen Schachtelsätze, direkt auf den Punkt.\n"
        "- REFERIERENDE: Jede Zeile beginnt mit '👉[Vorname Nachname], [Institution/Funktion]'. Niemals nur eine Stadt nennen!\n"
        "- EINTRITT & PRÜFUNG DER BARRIEREFREIHEIT:\n"
        "  * Die Zeile beginnt immer mit '📎Der Eintritt ist frei.'\n"
        "  * Prüfe den Webseitentext genau auf Angaben zur Barrierefreiheit und ergänze ZWINGEND GENAU EINEN kurzen Folgesatz:\n"
        "    - Wenn der Ort laut Text barrierefrei / rollstuhlgerecht ist: 'Der Veranstaltungsort ist barrierefrei.'\n"
        "    - Wenn der Ort laut Text NICHT barrierefrei ist: 'Der Veranstaltungsort ist leider nicht barrierefrei.'\n"
        "    - Wenn der Ort laut Text nur teilweise/eingeschränkt zugänglich ist: 'Der Veranstaltungsort ist nur eingeschränkt barrierefrei.'\n"
        "    - Wenn im Text KEINE Angaben zur Barrierefreiheit zu finden sind: 'Bei Fragen zur Barrierefreiheit wende dich bitte rechtzeitig an uns.'\n"
        "  * Übernimm NIEMALS lange Detailbeschreibungen zu Aufzügen, Rampen, Sehbehinderten-Markierungen oder Sanitäranlagen!\n\n"
        "Nutze EXAKT folgende Vorlage und Struktur:\n\n"
        "📝Save the Date!\n"
        "[Exakter Titel der Veranstaltung]\n\n"
        "📍[Genauer Raum / Location, vollständige Adresse]\n"
        "📅[Wochentag-Kürzel, z. B. Di, TT.MM.JJ] 🕰[Uhrzeit, z. B. 18 Uhr oder 18:00–20:00 Uhr]\n\n"
        "[Hier der kurze, kompakte Beschreibungstext: maximal 2 bis 3 Sätze zur Kernfrage / zum Inhalt]\n\n"
        "Wir freuen uns u. a. auf:\n"
        "👉[Titel Vorname Nachname], [Institution / Funktion / Fachbereich] [ggf. (als Rolle)]\n"
        "(wiederhole die Zeile mit 👉 für jede beteiligte Person; falls keine Personen genannt sind, den gesamten Block weglassen)\n\n"
        "Moderation: [Name, Funktion/Medium, falls vorhanden, sonst Zeile weglassen]\n\n"
        "📎Der Eintritt ist frei. [Hier genau einer der 4 vorgegebenen Folgesätze zur Barrierefreiheit]\n\n"
        "❗️Anmeldung [ggf. bis Datum ergänzen], wie immer auf unserer Website (einfach den Link im Story-Highlight „Anmeldung“ nutzen).\n\n"
        "[Falls im Text Kooperationspartner genannt sind: 'Eine Veranstaltung in Kooperation von Friedrich-Ebert-Stiftung Sachsen und [Partner].' sonst Zeile weglassen]\n\n"
        "#fesSachsen #politischeBildung [3–5 passende thematische Hashtags wie z. B. #Sachsen #Demokratie]\n\n"
        "Wichtig: Gib NUR die finale Caption aus, keinerlei Erklärungen davor oder danach.\n\n"
        f"Webseitentext:\n{raw_text[:14000]}"
    )

    models_to_try = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    ]

    last_error = ""
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response.text:
                    clean_caption = re.sub(r'<[^>]+>', '', response.text.strip())
                    clean_caption = clean_caption.replace("**", "").replace("__", "")
                    return clean_caption, None
            except Exception as e:
                last_error = str(e)
                time.sleep(1.5)

    return None, last_error

def generate_monthly_overview_with_gemini(all_events: list, selected_month_name: str, selected_month_num: str):
    """Filtert und strukturiert alle Termine eines Monats in einem einzigen KI-Aufruf."""
    if not ai_client:
        return None, "Kein GEMINI_API_KEY konfiguriert."

    events_dump = ""
    for idx, ev in enumerate(all_events, 1):
        events_dump += f"\n--- VERANSTALTUNG {idx} ---\nLink: {ev['url']}\nText:\n{ev['raw_text'][:2500]}\n"

    prompt = (
        f"Du bist Redakteur:in für den Telegram-Kanal der Friedrich-Ebert-Stiftung Sachsen.\n"
        f"Erstelle eine prägnante Monatsübersicht aller Veranstaltungen für den Monat {selected_month_name}.\n\n"
        "Aufgaben:\n"
        f"1. Finde alle Veranstaltungen, die im Monat {selected_month_name} (Monat {selected_month_num}) stattfinden.\n"
        "2. Identifiziere für jede Veranstaltung das exakte Datum (Tag.Monat.), die Stadt/den konkreten Veranstaltungsort und den echten Haupttitel.\n"
        "3. Sortiere die Liste chronologisch nach Datum aufsteigend.\n"
        "4. Ignoriere Termine aus anderen Monaten vollständig.\n"
        "5. Verwende AUSSCHLIESSLICH Telegram-HTML (<b>fett</b>, <i>kursiv</i>) und KEIN Markdown (keine Sternchen oder Unterstriche)!\n\n"
        "Nutze exakt folgendes Ausgabe-Format:\n\n"
        "🔴 <b>Friedrich-Ebert-Stiftung Sachsen</b>\n"
        f"🗓 <b>Unsere Veranstaltungen im {selected_month_name}:</b>\n\n"
        "• <b>[TT.MM.] | [Stadt / Ort]:</b> [Exakter Titel der Veranstaltung]\n"
        "(wiederhole diese Zeile für jede Veranstaltung dieses Monats)\n\n"
        "👉 <b>Alle Details zu den Terminen und zur Anmeldung findest du bei uns auf der Website:</b>\n"
        "https://www.fes.de/landesbuero-sachsen/veranstaltungen-rueckblicke\n\n"
        "<i>Detaillierte Infos zu den jeweiligen Veranstaltungen folgen.</i>\n\n"
        "Wichtig: Gib NUR den fertigen Text ohne Einleitung oder Kommentare aus.\n\n"
        f"Veranstaltungsdaten:\n{events_dump}"
    )

    models_to_try = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    ]

    last_error = ""
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response.text:
                    clean_output = markdown_to_telegram_html(response.text.strip())
                    return clean_output, None
            except Exception as e:
                last_error = str(e)
                time.sleep(1.5)

    return None, last_error

def parse_detail_page(url: str) -> dict:
    """Liest die Detailseite ein."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            return None
        soup = BeautifulSoup(res.text, "html.parser")
    except Exception:
        return None

    for tag in soup.find_all(["header", "nav", "footer", "script", "style"]):
        tag.decompose()

    h1 = soup.find("h1")
    titel = clean_text(h1.get_text()) if h1 else "Veranstaltung der FES Sachsen"
    cleaned_text = soup.get_text(separator="\n")

    return {
        "title": titel,
        "url": url,
        "raw_text": cleaned_text
    }

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_events(max_pages: int = 3) -> list[dict]:
    """Sucht alle Termine über mehrere Seiten hinweg (gecached für 1 Stunde)."""
    current_url = OVERVIEW_URL
    all_detail_urls = []
    visited_pages = set()

    for page_idx in range(1, max_pages + 1):
        if not current_url or current_url in visited_pages:
            break
        visited_pages.add(current_url)

        try:
            res = requests.get(current_url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                break
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception:
            break

        for link in soup.find_all("a", href=re.compile(r"/veranstaltungsdetail/\d+")):
            full_link = urljoin(BASE_URL, link.get("href", "")).split("/anmelden")[0]
            if full_link not in all_detail_urls:
                all_detail_urls.append(full_link)

        next_target_page = page_idx + 1
        next_page_link = soup.find(
            "a",
            href=re.compile(rf"tx_fesdeevents_urleventlist.*pageIndex.*={next_target_page}", re.IGNORECASE)
        )
        if not next_page_link:
            next_page_link = soup.find("a", string=re.compile(r"(vor|weiter|>|nächste)", re.I))

        if next_page_link and next_page_link.get("href"):
            current_url = urljoin(BASE_URL, next_page_link.get("href"))
        else:
            break

    events = []
    for u in all_detail_urls:
        ev = parse_detail_page(u)
        if ev:
            events.append(ev)

    return events

def check_password() -> bool:
    """Gibt True zurück, wenn das Passwort korrekt eingegeben wurde."""
    if not APP_PASSWORD:
        st.error("⚠️ In den Streamlit-Secrets wurde noch kein 'APP_PASSWORD' hinterlegt!")
        st.info("Bitte unter 'Manage app' -> 'Settings' -> 'Secrets' die Zeile APP_PASSWORD = \"...\" eintragen.")
        return False

    if st.session_state.get("authenticated", False):
        return True

    st.title("🔒 FES Sachsen Ticker – Login")
    st.caption("Bitte Passwort eingeben, um auf das Redaktionstool zuzugreifen.")

    with st.form("login_form"):
        pwd_input = st.text_input("Passwort:", type="password")
        submit = st.form_submit_button("Anmelden", use_container_width=True)

        if submit:
            if pwd_input == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Falsches Passwort.")

    return False

# ==========================================
# 2. STREAMLIT BENUTZEROBERFLÄCHE
# ==========================================
st.set_page_config(page_title="FES Ticker Manager", layout="wide")

# 1. Passwort prüfen – bricht hier ab, falls noch nicht eingeloggt
if not check_password():
    st.stop()

# 2. Reguläre App für eingeloggte Personen
st.title("🏛️ FES Sachsen – Veranstaltungs-Ticker")

col_head1, col_head2, col_head3 = st.columns([3, 1, 1])
with col_head2:
    if st.button("🔄 Neu scannen", use_container_width=True):
        fetch_events.clear()
        st.session_state.clear()
        st.session_state.authenticated = True
        st.rerun()

with col_head3:
    if st.button("Abmelden", use_container_width=True):
        st.session_state.clear()
        st.session_state.authenticated = False
        st.rerun()

if "events" not in st.session_state:
    with st.spinner("Scanne Termine der FES Sachsen..."):
        st.session_state.events = fetch_events()

events = st.session_state.events

if not events:
    st.info("Keine Termine gefunden.")
else:
    st.success(f"{len(events)} Veranstaltungen gefunden.")

    tab_monthly, tab_details = st.tabs(["📅 Monatsübersicht (Kompakt)", "📌 Einzelbeiträge (Detail)"])

    # ----------------------------------------------------
    # TAB 1: MONATSÜBERSICHT
    # ----------------------------------------------------
    with tab_monthly:
        st.subheader("🗓️ Kompakte Monatsübersicht erstellen")
        st.caption("Analysiert alle Veranstaltungen semantisch per KI für den gewählten Monat.")

        months_map = {
            "01": "Januar", "02": "Februar", "03": "März", "04": "April",
            "05": "Mai", "06": "Juni", "07": "Juli", "08": "August",
            "09": "September", "10": "Oktober", "11": "November", "12": "Dezember"
        }

        current_m = datetime.now().strftime("%m")
        selected_month = st.selectbox(
            "Monat auswählen:",
            options=list(months_map.keys()),
            format_func=lambda m: months_map[m],
            index=int(current_m) - 1
        )

        month_key = f"monthly_summary_{selected_month}"
        if month_key not in st.session_state:
            st.session_state[month_key] = ""

        col_m1, col_m2 = st.columns([1, 1])

        with col_m1:
            st.caption("💬 **Telegram-Vorschau:**")
            if st.session_state[month_key]:
                st.markdown(st.session_state[month_key], unsafe_allow_html=True)
            else:
                st.info("Klicke rechts auf den Button, um die Übersicht für diesen Monat per KI zusammenzustellen.")

        with col_m2:
            st.caption("✏️ **Aktion & Bearbeitung:**")

            if not st.session_state[month_key]:
                if st.button(f"✨ Monatsübersicht für {months_map[selected_month]} mit KI erstellen", type="secondary", use_container_width=True):
                    with st.spinner("Gemini analysiert alle Termine und baut die chronologische Übersicht..."):
                        summary_text, err = generate_monthly_overview_with_gemini(
                            events, months_map[selected_month], selected_month
                        )
                        if summary_text:
                            st.session_state[month_key] = summary_text
                            st.rerun()
                        else:
                            st.error(f"Fehler: {err}")
            else:
                monthly_msg = st.text_area(
                    "Nachricht anpassen:",
                    height=300,
                    key=month_key,
                    label_visibility="collapsed"
                )

                c_m_btn1, c_m_btn2 = st.columns([1, 1])
                with c_m_btn1:
                    if st.button("🔄 Neu generieren", key=f"regen_{month_key}", use_container_width=True):
                        with st.spinner("Generiere neu..."):
                            summary_text, err = generate_monthly_overview_with_gemini(
                                events, months_map[selected_month], selected_month
                            )
                            if summary_text:
                                st.session_state[month_key] = summary_text
                                st.rerun()
                            else:
                                st.error("Server überlastet. Bitte kurz warten.")
                with c_m_btn2:
                    if st.button("🚀 Monatsübersicht in den Kanal posten", type="primary", use_container_width=True):
                        if send_telegram_post(monthly_msg):
                            st.success("✅ Monatsübersicht erfolgreich gesendet!")
                        else:
                            st.error("❌ Fehler beim Senden.")

    # ----------------------------------------------------
    # TAB 2: EINZELBEITRÄGE (DETAIL)
    # ----------------------------------------------------
    with tab_details:
        st.subheader("📌 Detaillierte Einzelbeiträge")
        st.caption("Für die gezielte Veröffentlichung ca. zwei Wochen vor der jeweiligen Veranstaltung.")
        st.divider()

        for idx, ev in enumerate(events):
            with st.expander(f"📌 {ev['title'][:75]}...", expanded=(idx == 0)):
                post_key = f"post_text_{idx}"
                insta_key = f"insta_text_{idx}"

                if post_key not in st.session_state:
                    st.session_state[post_key] = ""
                if insta_key not in st.session_state:
                    st.session_state[insta_key] = ""

                # Die beiden Unter-Reiter für Telegram und Instagram
                subtab_tg, subtab_ig = st.tabs(["💬 Telegram / WhatsApp (HTML)", "📸 Instagram (Caption & Emojis)"])

                # --- UNTER-REITER 1: TELEGRAM / WHATSAPP ---
                with subtab_tg:
                    col_l, col_r = st.columns([1, 1])

                    with col_l:
                        st.caption("💬 **Telegram-Vorschau & Bild:**")
                        uploaded_img = st.file_uploader(
                            "Optional: Grafik/Flyer hinzufügen",
                            type=["jpg", "jpeg", "png", "webp"],
                            key=f"uploader_tg_{idx}"
                        )
                        if uploaded_img:
                            st.image(uploaded_img, use_container_width=True)

                        if st.session_state[post_key]:
                            st.markdown(st.session_state[post_key], unsafe_allow_html=True)
                        else:
                            st.info("Noch kein Telegram-Text generiert.")

                    with col_r:
                        st.caption("✏️ **Aktion & Bearbeitung (Telegram):**")
                        if not st.session_state[post_key]:
                            if st.button("✨ Telegram-Post generieren", key=f"gen_{idx}", type="secondary", use_container_width=True):
                                with st.spinner("Gemini formuliert den Telegram-Post..."):
                                    post_text, err = generate_post_with_gemini(ev["raw_text"], ev["url"])
                                    if post_text:
                                        st.session_state[post_key] = post_text
                                        st.rerun()
                                    else:
                                        st.error(f"Server ausgelastet. Bitte gleich erneut versuchen ({err[:60]}...).")
                        else:
                            msg_input = st.text_area(
                                "Nachricht anpassen:",
                                height=260,
                                key=post_key,
                                label_visibility="collapsed"
                            )

                            c_btn1, c_btn2 = st.columns([1, 1])
                            with c_btn1:
                                if st.button("🔄 Neu generieren", key=f"regen_{idx}", use_container_width=True):
                                    with st.spinner("Gemini generiert neu..."):
                                        post_text, err = generate_post_with_gemini(ev["raw_text"], ev["url"])
                                        if post_text:
                                            st.session_state[post_key] = post_text
                                            st.rerun()
                                        else:
                                            st.error("Server ausgelastet. Bitte kurz warten.")
                            with c_btn2:
                                btn_text = "🚀 Mit Bild in Kanal posten" if uploaded_img else "🚀 Als Text in Kanal posten"
                                if st.button(btn_text, key=f"btn_{idx}", type="primary", use_container_width=True):
                                    if not msg_input.strip() or "Fehler bei KI" in msg_input:
                                        st.warning("⚠️ Bitte warte auf einen gültigen Textentwurf vor dem Senden.")
                                    else:
                                        if send_telegram_post(msg_input, uploaded_img):
                                            st.success("✅ Erfolgreich in den Kanal gesendet!")
                                        else:
                                            st.error("❌ Fehler beim Senden. Prüfe Bot-Rechte und Kanal-ID.")

                # --- UNTER-REITER 2: INSTAGRAM ---
                with subtab_ig:
                    col_ig_l, col_ig_r = st.columns([1, 1])

                    with col_ig_l:
                        st.caption("📸 **Instagram-Vorschau:**")
                        if st.session_state[insta_key]:
                            st.text_area(
                                "Vorschau (nur lesbar):",
                                value=st.session_state[insta_key],
                                height=360,
                                disabled=True,
                                label_visibility="collapsed"
                            )
                        else:
                            st.info("Noch keine Instagram-Caption generiert. Klicke rechts auf den Button.")

                    with col_ig_r:
                        st.caption("✏️ **Aktion & Bearbeitung (Instagram):**")
                        if not st.session_state[insta_key]:
                            if st.button("✨ Instagram-Caption generieren", key=f"gen_ig_{idx}", type="secondary", use_container_width=True):
                                with st.spinner("Gemini schreibt die Instagram-Caption..."):
                                    ig_text, err = generate_instagram_caption_with_gemini(ev["raw_text"], ev["url"])
                                    if ig_text:
                                        st.session_state[insta_key] = ig_text
                                        st.rerun()
                                    else:
                                        st.error(f"Server ausgelastet. Bitte gleich erneut versuchen ({err[:60]}...).")
                        else:
                            ig_input = st.text_area(
                                "Caption anpassen / kopieren:",
                                height=300,
                                key=insta_key,
                                label_visibility="collapsed"
                            )
                            if st.button("🔄 Caption neu generieren", key=f"regen_ig_{idx}", use_container_width=True):
                                with st.spinner("Gemini generiert neu..."):
                                    ig_text, err = generate_instagram_caption_with_gemini(ev["raw_text"], ev["url"])
                                    if ig_text:
                                        st.session_state[insta_key] = ig_text
                                        st.rerun()
                                    else:
                                        st.error("Server ausgelastet. Bitte kurz warten.")
