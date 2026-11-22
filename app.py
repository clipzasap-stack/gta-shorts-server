import os, random, subprocess, asyncio, requests
from flask import Flask, request, send_file, jsonify
import edge_tts

app = Flask(__name__)

def get_gta_clip_url():
    r = requests.get(
        "https://archive.org/advancedsearch.php",
        params={
            "q": "GTA V gameplay OR GTA 5 stunts AND mediatype:movies",
            "fl[]": "identifier",
            "rows": 30,
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
    raise RuntimeError("Geen geschikte MP4-clip gevonden")

async def make_tts(text, out_path):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(out_path)

@app.route("/render", methods=["POST"])
def render_short():
    try:
        data = request.get_json(force=True)
        voiceover_text = data.get("voiceover_text", "Watch this insane GTA stunt!")

        for f in ["raw.mp4", "voice.mp3", "final.mp4"]:
            if os.path.exists(f):
                os.remove(f)

        clip_url = get_gta_clip_url()
        with requests.get(clip_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open("raw.mp4", "wb") as out:
                for chunk in r.iter_content(chunk_size=65536):
                    out.write(chunk)

        asyncio.run(make_tts(voiceover_text, "voice.mp3"))

        # 720x1280 (9:16) met 1 thread zodat het binnen Render's gratis 512MB RAM blijft
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
