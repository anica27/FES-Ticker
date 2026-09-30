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

ai_client = genai.Client(api_key=GEMINI_API_KEY.strip())

BASE_URL = "https://www.fes.de"
OVERVIEW_URL = "https://www.fes.de/landesbuero-sachsen/veranstaltungen-rueckblicke"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()

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
    """Erstellt den ausführlichen Einzelpost mit Du-Form und FES-Markierung."""
    prompt = (
        "Du bist Redakteur für den Telegram-Kanal der Friedrich-Ebert-Stiftung Sachsen.\n"
        "Erstelle aus dem folgenden Veranstaltungstext eine fertige Telegram-Nachricht.\n\n"
        "Stil-Vorgaben:\n"
        "- Verwende durchgehend eine direkte, nahbare Ansprache im 'Du' (z. B. 'Diskutiere mit', 'stelle deine Fragen').\n"
        "- Nutze Telegram-HTML mit Tags (<b>fett</b>, <i>kursiv</i>) für Titel und Abschnitte. Verwende KEINE Markdown-Sternchen!\n\n"
        "Nutze exakt folgendes Schema:\n\n"
        "🔴 <b>Friedrich-Ebert-Stiftung Sachsen</b>\n"
        "🗣️ <b>[Format, z. B. Bürgergespräch / Fachgespräch / Tagung / Buchlesung]</b>:\n"
        "<b>„[TITEL DER VERANSTALTUNG]“</b>\n\n"
        "[1 bis maximal 2 Sätze Hook / Leitfrage, die Lust aufs Mitdiskutieren machen, mit Du-Ansprache]\n\n"
        "<b>Mit dabei:</b>\n"
        "- Nenne die Diskutierenden, Referierenden bzw. Autor:innen mit Institution (Format: • Name – Institution).\n"
        "- Falls keine Personen genannt sind, diesen Block komplett weglassen.\n\n"
        "<b>Moderation:</b> [Name, falls vorhanden, sonst Zeile weglassen]\n\n"
        "🗓️ [Wochentag, Datum | Uhrzeit – zwingend dem Block 'Termin' entnehmen]\n"
        "📍 [Veranstaltungsort mit vollständiger Adresse]\n"
        "📝 [Anmeldeschluss: Wochentag, Datum – NUR falls Frist vorhanden, sonst komplett weglassen]\n"
        f"🔗 {url}\n\n"
        f"{url}\n\n"
        "Wichtig: Gib NUR den finalen Nachrichtentext aus, keine Erklärungen davor oder danach.\n\n"
        f"Webseitentext:\n{raw_text[:14000]}"
    )

    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
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
                    return response.text.strip(), None
            except Exception as e:
                last_error = str(e)
                time.sleep(1.5)

    return None, last_error

def generate_monthly_overview_with_gemini(all_events: list, selected_month_name: str, selected_month_num: str):
    """Filtert und strukturiert alle Termine eines Monats in einem einzigen KI-Aufruf."""
    events_dump = ""
    for idx, ev in enumerate(all_events, 1):
        events_dump += f"\n--- VERANSTALTUNG {idx} ---\nLink: {ev['url']}\nText:\n{ev['raw_text'][:2500]}\n"

    prompt = (
        f"Du bist Redakteur für den Telegram-Kanal der Friedrich-Ebert-Stiftung Sachsen.\n"
        f"Erstelle eine prägnante Monatsübersicht aller Veranstaltungen für den Monat {selected_month_name}.\n\n"
        "Aufgaben:\n"
        f"1. Finde alle Veranstaltungen, die im Monat {selected_month_name} (Monat {selected_month_num}) stattfinden.\n"
        "2. Identifiziere für jede Veranstaltung das exakte Datum (Tag.Monat.), die Stadt/den konkreten Veranstaltungsort und den echten Haupttitel.\n"
        "3. Sortiere die Liste chronologisch nach Datum aufsteigend.\n"
        "4. Ignoriere Termine aus anderen Monaten vollständig.\n"
        "5. Verwende AUSSCHLIESSLICH Telegram-HTML (<b>fett</b>, <i>kursiv</i>) und KEIN Markdown (keine Sternchen oder Unterstriche)!\n\n"
        "Nutze exakt folgendes Ausgabe-Format:\n\n"
        "🔴 <b>Friedrich-Ebert-Stiftung Sachsen</b>\n"
        f"🗓️ <b>Unsere Veranstaltungen im {selected_month_name}:</b>\n\n"
        "• <b>[TT.MM.] | [Stadt / Ort]:</b> [Exakter Titel der Veranstaltung]\n"
        "(wiederhole diese Zeile für jede Veranstaltung dieses Monats)\n\n"
        "👉 <b>Alle Details zu den Terminen und zur Anmeldung findest du bei uns auf der Website:</b>\n"
        "https://www.fes.de/landesbuero-sachsen/veranstaltungen-rueckblicke\n\n"
        "<i>Detaillierte Infos zu den jeweiligen Veranstaltungen folgen.</i>\n\n"
        "Wichtig: Gib NUR den fertigen Text ohne Einleitung oder Kommentare aus.\n\n"
        f"Veranstaltungsdaten:\n{events_dump}"
    )

    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
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
                    return response.text.strip(), None
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

def fetch_events(max_pages: int = 3) -> list[dict]:
    """Sucht alle Termine über mehrere Seiten hinweg."""
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

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
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

# 1. Passwort prüfen – bricht hier ab, falls noch nicht eingeloggt
if not check_password():
    st.stop()

# 2. Reguläre App für eingeloggte Personen
st.set_page_config(page_title="FES Ticker Manager", layout="wide")
st.title("🏛️ FES Sachsen – Veranstaltungs-Ticker")

col_logout1, col_logout2 = st.columns([5, 1])
with col_logout2:
    if st.button("Abmelden", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

col1, col2 = st.columns([3, 1])
with col2:
    if st.button("🔄 Website neu scannen", use_container_width=True):
        st.session_state.clear()
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
                    value=st.session_state[month_key],
                    height=300,
                    key=f"area_{month_key}",
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
                col_l, col_r = st.columns([1, 1])

                post_key = f"post_text_{idx}"
                if post_key not in st.session_state:
                    st.session_state[post_key] = ""

                with col_l:
                    st.caption("💬 **Telegram-Vorschau & Bild:**")
                    
                    uploaded_img = st.file_uploader(
                        "Optional: Grafik/Flyer hinzufügen",
                        type=["jpg", "jpeg", "png", "webp"],
                        key=f"uploader_{idx}"
                    )
                    if uploaded_img:
                        st.image(uploaded_img, use_container_width=True)

                    if st.session_state[post_key]:
                        st.code(st.session_state[post_key], language=None)
                    else:
                        st.info("Noch kein Text generiert. Klicke rechts auf den Button.")

                with col_r:
                    st.caption("✏️ **Aktion & Bearbeitung:**")

                    if not st.session_state[post_key]:
                        if st.button("✨ Post mit KI generieren", key=f"gen_{idx}", type="secondary", use_container_width=True):
                            with st.spinner("Gemini formuliert den Beitrag..."):
                                post_text, err = generate_post_with_gemini(ev["raw_text"], ev["url"])
                                if post_text:
                                    st.session_state[post_key] = post_text
                                    st.rerun()
                                else:
                                    st.error(f"Server ausgelastet. Bitte gleich erneut versuchen ({err[:60]}...).")
                    else:
                        msg_input = st.text_area(
                            "Nachricht anpassen:",
                            value=st.session_state[post_key],
                            height=260,
                            key=f"box_{idx}",
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
