import os, random, subprocess, asyncio, requests, textwrap
from flask import Flask, request, send_file, jsonify
import edge_tts
from gtts import gTTS

app = Flask(__name__)

def get_gta_clip_url():
    queries = [
        'subject:"Grand Theft Auto V" AND mediatype:movies',
        'title:"GTA 5" AND gameplay AND mediatype:movies',
        'title:"GTA V" AND stunts AND mediatype:movies'
    ]
    r = requests.get(
        "https://archive.org/advancedsearch.php",
        params={
            "q": random.choice(queries),
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
            if name.endswith(".mp4") and 3_000_000 < size < 60_000_000:
                return f"https://archive.org/download/{ident}/{name}"
    raise RuntimeError("Geen geschikte GTA gameplay MP4 gevonden")

def get_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]).decode().strip()
    return float(out)

async def make_edge_tts(text, out_path):
    communicate = edge_tts.Communicate(text, "en-US-GuyNeural", rate="+15%")
    await communicate.save(out_path)

def generate_voiceover(text, out_path):
    clean_text = (text or "").strip().replace('"', '').replace("'", "")
    if len(clean_text) < 10:
        clean_text = "No way! Watch what happens when this driver tries the craziest stunt in Los Santos without hitting the brakes!"
    try:
        asyncio.run(make_edge_tts(clean_text, out_path))
    except Exception:
        pass
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        gTTS(text=clean_text, lang="en", tld="com").save(out_path)
    return clean_text

def format_srt_time(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

def build_srt(text, total_dur, srt_path):
    words = text.split()
    chunks = [" ".join(words[i:i+4]).upper() for i in range(0, len(words), 4)]
    if not chunks:
        chunks = ["CRAZY GTA STUNT!"]
    step = total_dur / len(chunks)
    lines = []
    for idx, chunk in enumerate(chunks):
        start = format_srt_time(idx * step)
        end = format_srt_time((idx + 1) * step)
        wrapped = "\n".join(textwrap.wrap(chunk, width=18))
        lines.append(f"{idx+1}\n{start} --> {end}\n{wrapped}\n")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

@app.route("/render", methods=["POST"])
def render_short():
    try:
        data = request.get_json(force=True, silent=True) or {}
        raw_text = data.get("voiceover_text", "")

        for f in ["raw.mp4", "voice.mp3", "subs.srt", "final.mp4"]:
            if os.path.exists(f):
                os.remove(f)

        clip_url = get_gta_clip_url()
        with requests.get(clip_url, stream=True, timeout=35) as r:
            r.raise_for_status()
            with open("raw.mp4", "wb") as out:
                for chunk in r.iter_content(chunk_size=65536):
                    out.write(chunk)

        clean_text = generate_voiceover(raw_text, "voice.mp3")
        voice_dur = max(12.0, min(get_duration("voice.mp3") + 1.0, 45.0))
        vid_dur = get_duration("raw.mp4")

        # Spring naar een spannend stuk midden in de video in plaats van het saaie intro
        start_sec = 0.0
        if vid_dur > voice_dur + 15:
            start_sec = random.uniform(vid_dur * 0.25, vid_dur - voice_dur - 5)

        build_srt(clean_text, voice_dur, "subs.srt")

        vf = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=15:5[bg];"
            "[0:v]scale=720:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            "subtitles=subs.srt:force_style='FontName=DejaVu Sans,FontSize=18,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=10'[outv]"
        )
        # Mix originele game-audio (35%) met AI-stem (100%)
        af = "[0:a]volume=0.35[bg_a];[1:a]volume=1.2[fg_a];[bg_a][fg_a]amix=inputs=2:duration=shortest[outa]"

        cmd = [
            "ffmpeg", "-y", "-threads", "1",
            "-ss", f"{start_sec:.2f}", "-t", f"{voice_dur:.2f}", "-i", "raw.mp4",
            "-i", "voice.mp3",
            "-filter_complex", f"{vf};{af}",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "27",
            "-c:a", "aac", "-t", f"{voice_dur:.2f}", "final.mp4"
        ]
        subprocess.run(cmd, check=True)
        return send_file("final.mp4", mimetype="video/mp4")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
