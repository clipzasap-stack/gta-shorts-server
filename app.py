import os, random, subprocess, asyncio, requests
from flask import Flask, request, send_file, jsonify
import edge_tts
from gtts import gTTS

app = Flask(__name__)

def get_gta_clip_url():
    r = requests.get(
        "https://archive.org/advancedsearch.php",
        params={
            "q": 'title:"Grand Theft Auto" AND mediatype:movies',
            "fl[]": "identifier",
            "rows": 40,
            "page": 1,
            "output": "json"
        },
        timeout=15
    )
    docs = r.json().get("response", {}).get("docs", [])
    random.shuffle(docs)
    for doc in docs:
        ident = doc["identifier"]
        meta = requests.get(f"https://archive.org/metadata/{ident}", timeout=15).json()
        for f in meta.get("files", []):
            name = f.get("name", "")
            size = int(f.get("size", 0) or 0)
            if name.endswith(".mp4") and 1_000_000 < size < 40_000_000:
                return f"https://archive.org/download/{ident}/{name}"
    raise RuntimeError("Geen geschikte GTA MP4-clip gevonden")

async def make_edge_tts(text, out_path):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(out_path)

def generate_voiceover(text, out_path):
    clean_text = (text or "").strip()
    if len(clean_text) < 3:
        clean_text = "No way! Look at this insane Grand Theft Auto stunt!"
    try:
        asyncio.run(make_edge_tts(clean_text, out_path))
    except Exception:
        pass
    # Fallback naar gTTS als edge-tts een leeg/corrupt bestand oplevert
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        tts = gTTS(text=clean_text, lang="en", tld="com")
        tts.save(out_path)

@app.route("/render", methods=["POST"])
def render_short():
    try:
        data = request.get_json(force=True, silent=True) or {}
        voiceover_text = data.get("voiceover_text", "")

        for f in ["raw.mp4", "voice.mp3", "final.mp4"]:
            if os.path.exists(f):
                os.remove(f)

        clip_url = get_gta_clip_url()
        with requests.get(clip_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open("raw.mp4", "wb") as out:
                for chunk in r.iter_content(chunk_size=65536):
                    out.write(chunk)

        generate_voiceover(voiceover_text, "voice.mp3")

        vf = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=15:5[bg];"
            "[0:v]scale=720:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
        )
        cmd = [
            "ffmpeg", "-y", "-threads", "1",
            "-ss", "0", "-t", "25", "-i", "raw.mp4",
            "-i", "voice.mp3",
            "-filter_complex", vf,
            "-map", "[outv]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-shortest", "final.mp4"
        ]
        subprocess.run(cmd, check=True)
        return send_file("final.mp4", mimetype="video/mp4")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
