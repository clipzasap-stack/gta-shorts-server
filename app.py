import os, random, subprocess, asyncio, requests, textwrap
from flask import Flask, request, send_file, jsonify
import edge_tts
from gtts import gTTS

app = Flask(__name__)

def get_gta_clip_url():
    queries = [
        '("GTA 6" OR "GTA VI" OR "Grand Theft Auto VI") AND (fail OR fails OR bug OR glitch OR funny) AND mediatype:movies',
        '("GTA 6" OR "GTA VI" OR "Grand Theft Auto 6") AND mediatype:movies',
        '("GTA 5" OR "Grand Theft Auto V") AND (fail OR fails OR glitch) AND mediatype:movies'
    ]
    for q in queries:
        try:
            r = requests.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": q,
                    "fl[]": "identifier",
                    "rows": 30,
                    "page": 1,
                    "output": "json"
                },
                timeout=10
            )
            docs = r.json().get("response", {}).get("docs", [])
            random.shuffle(docs)
            for doc in docs[:10]:
                ident = doc["identifier"]
                meta = requests.get(f"https://archive.org/metadata/{ident}", timeout=10).json()
                for f in meta.get("files", []):
                    name = f.get("name", "")
                    size = int(f.get("size", 0) or 0)
                    if name.endswith(".mp4") and 2_000_000 < size < 25_000_000:
                        return f"https://archive.org/download/{ident}/{name}"
        except Exception:
            continue
    raise RuntimeError("Geen snelle GTA MP4 gevonden")

def get_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]).decode().strip()
    return float(out)

async def make_edge_tts(text, out_path):
    communicate = edge_tts.Communicate(text, "en-US-GuyNeural", rate="+10%")
    await asyncio.wait_for(communicate.save(out_path), timeout=15.0)

def generate_voiceover(extra_text, out_path):
    hook = "Imagine waiting all these years just for this to happen."
    clean_extra = (extra_text or "").strip().replace('"', '').replace("'", "")
    if clean_extra.lower().startswith("imagine waiting all these years"):
        full_text = clean_extra
    elif len(clean_extra) > 5:
        full_text = f"{hook} {clean_extra}"
    else:
        full_text = f"{hook} Watch how completely broken this physics glitch gets right before the crash!"
    try:
        asyncio.run(make_edge_tts(full_text, out_path))
    except Exception:
        pass
    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        gTTS(text=full_text, lang="en", tld="com").save(out_path)
    return full_text

def format_srt_time(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

def build_tv_srt(text, speech_dur, srt_path):
    words = text.split()
    chunks = [" ".join(words[i:i+7]) for i in range(0, len(words), 7)]
    if not chunks:
        chunks = ["Imagine waiting all these years just for this to happen."]
    step = speech_dur / len(chunks)
    lines = []
    for idx, chunk in enumerate(chunks):
        start = format_srt_time(idx * step)
        end = format_srt_time((idx + 1) * step)
        wrapped = "\n".join(textwrap.wrap(chunk, width=34))
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
        with requests.get(clip_url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open("raw.mp4", "wb") as out:
                for chunk in r.iter_content(chunk_size=65536):
                    out.write(chunk)

        full_text = generate_voiceover(raw_text, "voice.mp3")
        voice_dur = get_duration("voice.mp3")
        target_dur = 20.0
        vid_dur = get_duration("raw.mp4")

        start_sec = 0.0
        if vid_dur > target_dur + 15:
            start_sec = random.uniform(vid_dur * 0.20, vid_dur - target_dur - 5)

        build_tv_srt(full_text, min(voice_dur, target_dur), "subs.srt")

        vf = (
            "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=15:5[bg];"
            "[0:v]scale=720:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            "subtitles=subs.srt:force_style='FontName=DejaVu Sans,FontSize=11,Bold=0,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=38'[outv]"
        )
        af = "[0:a]volume=0.45[bg_a];[1:a]apad,volume=1.2[fg_a];[bg_a][fg_a]amix=inputs=2:duration=first[outa]"

        cmd = [
            "ffmpeg", "-y", "-threads", "1",
            "-ss", f"{start_sec:.2f}", "-t", f"{target_dur:.2f}", "-i", "raw.mp4",
            "-i", "voice.mp3",
            "-filter_complex", f"{vf};{af}",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-b:v", "1200k", "-maxrate", "1400k", "-bufsize", "2000k",
            "-c:a", "aac", "-b:a", "96k", "-t", f"{target_dur:.2f}", "final.mp4"
        ]
        subprocess.run(cmd, check=True, timeout=60)
        return send_file("final.mp4", mimetype="video/mp4")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
