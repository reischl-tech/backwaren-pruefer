import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, ImageOps
import json
import io
import pandas as pd

st.set_page_config(page_title="Backwaren Beleg-Prüfer", layout="centered")
st.title("🥨 Backwaren Monats-Abgleich (Gratis-Test)")
st.caption("Optimiert für Lieferscheine & mehrseitige Monats-Lieferübersichten")

api_key = st.sidebar.text_input("Kostenlosen Google Gemini API-Key eingeben", type="password")

def prepare_image_bytes(image, rotate_angle=0):
    image = ImageOps.exif_transpose(image)
    if rotate_angle != 0:
        image = image.rotate(rotate_angle, expand=True)
    
    max_size = 2400
    if max(image.size) > max_size:
        ratio = max_size / max(image.size)
        new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=90)
    return buffered.getvalue()

def analyze_bakery_month(ls_images, re_images_with_rot, key):
    client = genai.Client(api_key=key.strip())
    
    prompt_text = f"""
    Du bist ein spezialisierter Buchhaltungs-Prüfer für eine Bäckerei/Filiale.
    Du erhältst {len(ls_images)} Lieferschein-Seiten und {len(re_images_with_rot)} Seiten der Monats-Lieferübersicht.
    
    1. REGELN FÜR DIE LIEFERSCHEINE:
    - Lies oben links das Datum (z.B. '27.10.2026').
    - Lies die Tabelle mit 'ArtNr', 'Liefer-Menge', 'Bezeichnung' sowie den Spalten 'Retoure' und 'Nach-Lief.'.
    - HANDSCHRIFT & RETOUREN: Achte extrem genau auf handschriftliche Vermerke neben den Artikeln (z.B. 'zurück 5x verbrannt!', '-2', Zahlen in Spalte 'Retoure' oder 'Nach-Lief.' oder durchgestrichene Mengen).
    - Berechne pro Lieferschein-Zeile: Netto_Lieferung = Liefer-Menge - Retoure + Nach-Lief.
    - IGNORIERE komplett: Kontrollhäkchen neben den Zahlen, Unterschriften/Kürzel (z.B. 'B.B'), 'Zwischensumme' sowie alle Pfand-Zeilen ('PFAND FÜR KÖRBE', 'PFAND FÜR WÄGEN', 'PFAND FÜR BLECHE').
    - Summiere die Netto-Liefermengen pro ArtNr über alle Lieferschein-Seiten des Monats.
    
    2. REGELN FÜR DIE MONATS-LIEFERÜBERSICHT (ALLE SEITEN):
    - Links stehen die Tage des Monats und am Ende die Zeile 'Summe'.
    - Oben stehen ArtNr und Bezeichnung als Spalten. Darunter 'lief' (Lieferung) und 'ret' (Retoure).
    - IGNORIERE alle Pfand-Artikel auf der Lieferübersicht (ArtNr 9805, 9806, 9807, 9855, 9856, 9857 bzw. alles mit 'Pfand' im Namen)!
    - Lies für jeden Backwaren-Artikel die Monats-Summen aus der Zeile 'Summe' für 'lief' und 'ret' aus.
    - Berechne Netto_Rechnung = Summe(lief) - Summe(ret).
    
    3. ABGLEICH & FEHLERSUCHE:
    - Vergleiche pro Artikel die Gesamt-Netto-Menge aus den Lieferscheinen mit Netto_Rechnung.
    - Bei Abweichung: Vergleiche die Tagesdaten der Lieferscheine mit den einzelnen Tageszeilen in der Lieferübersicht, um das EXAKTE DATUM des Fehlers zu finden!
    
    STATUS-WERTE:
    - "OK": Lieferschein-Netto == Rechnungs-Netto (ohne unklare Handschrift).
    - "PRÜFEN": Zahlen stimmen überein, aber es gab handschriftliche Retouren/Notizen auf einem Lieferschein.
    - "ABWEICHUNG": Differenz zwischen Lieferscheinen und Lieferübersicht oder Artikel fehlt auf einer Seite.

    Antworte AUSSCHLIESSLICH mit gültigem JSON im folgenden Format (ohne Markdown-Codeblöcke):
    {{
        "positionen": [
            {{
                "art_nr": "6040",
                "artikel": "Käsebrezen Backstube",
                "ls_netto": 87,
                "re_lief": 87,
                "re_ret": 0,
                "re_netto": 87,
                "differenz": 0,
                "status": "OK",
                "bemerkung": ""
            }}
        ],
        "gesamtfazit": "Klare Zusammenfassung aller Abweichungen und handschriftlichen Vermerke im Monat"
    }}
    """

    contents = [prompt_text]

    for idx, img in enumerate(ls_images):
        contents.append(f"--- LIEFERSCHEIN SEITE {idx+1} ---")
        contents.append(types.Part.from_bytes(data=prepare_image_bytes(img, 0), mime_type="image/jpeg"))

    for idx, (img, rot) in enumerate(re_images_with_rot):
        contents.append(f"--- LIEFERÜBERSICHT SEITE {idx+1} ---")
        contents.append(types.Part.from_bytes(data=prepare_image_bytes(img, rot), mime_type="image/jpeg"))

    # Probiert zuerst das geforderte neue Modell, mit Fallback auf aktuelle Alternativen
    models_to_try = ["gemini-3.8-flash", "gemini-3.0-flash", "gemini-2.5-pro"]
    response = None
    last_error = None

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            break
        except Exception as e:
            last_error = e
            if "404" in str(e) or "NOT_FOUND" in str(e):
                continue
            raise e

    if response is None:
        raise last_error

    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`").removeprefix("json").strip()

    return json.loads(raw_text)

st.subheader("1. Alle Lieferscheine des Monats")
ls_files = st.file_uploader("Lieferschein-Fotos auswählen", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="ls")

st.subheader("2. Alle Seiten der Monats-Lieferübersicht (Seite 1, 2 & 3)")
re_files = st.file_uploader("Alle Seiten der Lieferübersicht auswählen", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="re")

re_rotations = []
if re_files:
    st.markdown("**Ausrichtung der Lieferübersicht-Seiten prüfen (Schrift muss waagerecht lesbar sein):**")
    cols = st.columns(len(re_files))
    for i, file in enumerate(re_files):
        img = ImageOps.exif_transpose(Image.open(file))
        with cols[i]:
            rot = st.selectbox(f"Seite {i+1} drehen", [0, 90, -90, 180], index=1, key=f"rot_{i}")
            preview = img.rotate(rot, expand=True) if rot != 0 else img
            st.image(preview, caption=f"Seite {i+1}", use_container_width=True)
            re_rotations.append((img, rot))

if ls_files and re_files:
    if st.button("🔍 Gesamten Monat jetzt prüfen", type="primary", use_container_width=True):
        if not api_key:
            st.error("Bitte links im Menü deinen kostenlosen Google Gemini API-Key eingeben.")
        else:
            with st.spinner("Gemini KI prüft alle Lieferscheine, Handschriften und die Lieferübersicht..."):
                try:
                    ls_imgs = [Image.open(f) for f in ls_files]
                    ergebnis = analyze_bakery_month(ls_imgs, re_rotations, api_key)
                    
                    st.subheader("📋 Ergebnis der Monatsprüfung")
                    st.info(ergebnis["gesamtfazit"])
                    
                    df = pd.DataFrame(ergebnis["positionen"])
                    
                    def highlight(val):
                        if val == 'ABWEICHUNG':
                            return 'background-color: #ffcccc; color: black; font-weight: bold'
                        elif val == 'PRÜFEN':
                            return 'background-color: #fff2cc; color: black; font-weight: bold'
                        return 'background-color: #ccffcc; color: black'

                    st.dataframe(df.style.map(highlight, subset=['status']), use_container_width=True)
                    
                    csv = df.to_csv(index=False, sep=";").encode('utf-8-sig')
                    st.download_button("📥 Ergebnis als Excel-Tabelle (CSV) speichern", data=csv, file_name="Backwaren_Monatsabgleich.csv", mime="text/csv")
                except Exception as e:
                    st.error(f"Fehler bei der Verarbeitung: {e}")
