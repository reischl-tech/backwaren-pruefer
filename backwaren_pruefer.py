import streamlit as st
from openai import OpenAI
from PIL import Image, ImageOps
import base64
import json
import io
import pandas as pd

st.set_page_config(page_title="Backwaren Beleg-Prüfer", layout="centered")
st.title("🥨 Backwaren Monats-Abgleich")
st.caption("Optimiert für Lieferscheine & mehrseitige Monats-Lieferübersichten")

api_key = st.sidebar.text_input("OpenAI API-Key eingeben", type="password")

def prepare_image(image, rotate_angle=0):
    image = ImageOps.exif_transpose(image)
    if rotate_angle != 0:
        image = image.rotate(rotate_angle, expand=True)
    
    max_size = 2400
    if max(image.size) > max_size:
        ratio = max_size / max(image.size)
        new_size = (int(image.size * ratio), int(image.size * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
        
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG", quality=90)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def analyze_bakery_month(ls_images, re_images_with_rot, key):
    client = OpenAI(api_key=key)
    
    content_list = [
        {
            "type": "text",
            "text": f"""
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

            Antworte AUSSCHLIESSLICH im folgenden JSON-Format:
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
        }
    ]

    for idx, img in enumerate(ls_images):
        content_list.append({"type": "text", "text": f"--- LIEFERSCHEIN SEITE {idx+1} ---"})
        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{prepare_image(img, 0)}", "detail": "high"}})

    for idx, (img, rot) in enumerate(re_images_with_rot):
        content_list.append({"type": "text", "text": f"--- LIEFERÜBERSICHT SEITE {idx+1} ---"})
        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{prepare_image(img, rot)}", "detail": "high"}})

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": content_list}],
        max_tokens=4000
    )
    return json.loads(response.choices.message.content)

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
            st.error("Bitte links im Menü deinen OpenAI API-Key eingeben.")
        else:
            with st.spinner("Prüfe alle Lieferscheine, Handschriften und die 3 Seiten der Lieferübersicht..."):
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
