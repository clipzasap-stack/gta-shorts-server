import os, random, subprocess, asyncio, requests
from flask import Flask, request, send_file
import edge_tts

app = Flask(__name__)

def get_random_gta_video():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GTA-Bot/1.0"}
    r = requests.get("https://www.reddit.com/r/gtaonline/top.json?t=week&limit=25", headers=headers, timeout=15)
    posts = r.json().get("data", {}).get("children", [])
    videos = [
        "https://www.reddit.com" + p["data"]["permalink"]
        for p in posts
        if p["data"].get("is_video") and not p["data"].get("over_18")
    ]
    return random.choice(videos)

async def make_tts(text, out_path):
    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural", rate="+10%")
    await communicate.save(out_path)

@app.route("/render", methods=["POST"])
def render_short():
    data = request.get_json(force=True)
    voiceover_text = data.get("voiceover_text", "Watch this insane GTA stunt!")
    video_page_url = get_random_gta_video()

    for f in ["raw.mp4", "voice.mp3", "final.mp4"]:
        if os.path.exists(f):
            os.remove(f)

    subprocess.run(["yt-dlp", "-f", "best[ext=mp4]/best", "-o", "raw.mp4", video_page_url], check=True)
    asyncio.run(make_tts(voiceover_text, "voice.mp3"))

    vf = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];"
        "[0:v]scale=1080:-2[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,eq=contrast=1.05:saturation=1.1[outv]"
    )
    cmd = [
        "ffmpeg", "-y", "-i", "raw.mp4", "-i", "voice.mp3",
        "-filter_complex", vf,
        "-map", "[outv]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-c:a", "aac", "-shortest", "-t", "58", "final.mp4"
    ]
    subprocess.run(cmd, check=True)
    return send_file("final.mp4", mimetype="video/mp4")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
