# LumaKit on LumaBot

This is the reproducible factory and developer setup for the open-source
LumaBot agent. It targets a Raspberry Pi 5 with 2 GB RAM and a hosted LLM.

Tested on:

- Debian 13 (Trixie), ARM64
- Python 3.13
- LumaKit upstream base `a439e264429ca49ac81f307d193606f68e852b58`
- whisper.cpp `4523d0ce373ee4b2176b3251fff29fd4864fcf38`
- edge-tts `7.2.8`
- xAI with LumaKit's default `grok-4` model

## Deployment profile

Use the main LumaKit repository with the LumaBot compatibility changes. Do
not create a separate "LumaKit Light" repository.

Install the core package and, when Telegram voice is wanted, only the
`speech` extra. Do not install Ollama, Playwright, Chromium, the `browser`
extra, the `desktop` extra, or the `all` extra.

Expected layout:

```text
/home/lumabot21/
├── lumabot/
└── lumakit/
```

## LumaBot hardware daemon and agent tools

Clone both repositories into the layout above. In the LumaBot checkout,
create its virtual environment and install only its Pi hardware dependencies.
Do not install Playwright or Ollama.

Install and start the supplied hardware service:

```bash
cd /home/lumabot21/lumabot
sudo cp lumabot.service /etc/systemd/system/lumabot.service
sudo systemctl daemon-reload
sudo systemctl enable --now lumabot.service
curl -fsS http://127.0.0.1:8971/status
```

The unit enables the Adafruit Motor Bonnet and X1200 battery gauge. Verify the
robot is raised on a stand before testing movement. The present mapping is
Motor 1 = left (software-inverted) and Motor 4 = right.

The LumaKit `lumabot_status`, `lumabot_drive`, `lumabot_sequence`, and
`lumabot_stop` tools call this service through `LUMABOT_URL`. Movement tools
are owner-only. Natural-language intent and the final acknowledgement remain
part of LumaKit's normal LLM tool-result cycle; there is no phrase parser.

Enable focused robot control for an individual conversation:

```text
Telegram: /lumabot on
CLI:      /lumabot on
Web:      click the LumaBot toggle in the top bar
```

This replaces the full agent prompt and 98-tool catalog with a compact robot
prompt and only the four LumaBot tools. The setting follows that saved
conversation and `/lumabot off` restores full LumaKit. “Park” currently stops
scheduled movement and coasts both motors. Autonomous patrol remains
unavailable until the distance sensor is connected and verified.

After updating either checkout:

```bash
sudo systemctl restart lumabot.service
sudo systemctl restart lumakit.service
sudo systemctl is-active lumabot.service lumakit.service
```

## Factory installation

Clone LumaKit and create an isolated environment:

```bash
cd /home/lumabot21
git clone https://github.com/patmakesapps/LumaKit.git lumakit
cd lumakit
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

For a developer image, install the test runner and run the shipped tests:

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

Confirm that optional desktop and browser packages were not installed:

```bash
.venv/bin/python -m pip show playwright
.venv/bin/python -m pip show pyautogui
```

Both commands should report that the package was not found.

## Two-way Telegram voice

The tested low-memory voice stack is:

- Incoming voice notes: local `whisper.cpp` with the English-only
  `tiny.en` model.
- Outgoing voice replies: Edge TTS using `en-US-AvaNeural`.

Whisper runs only while a voice note is being transcribed; it is not a
resident model server. Edge TTS also does not remain loaded, but it does
require an internet connection to synthesize each reply.

Install only the speech extra and native build tools:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake ffmpeg
cd /home/lumabot21/lumakit
.venv/bin/python -m pip install -e '.[speech]'
```

Build the tested whisper.cpp revision with two jobs to control build-time
memory:

```bash
mkdir -p .vendor
git clone https://github.com/ggml-org/whisper.cpp.git .vendor/whisper.cpp
git -C .vendor/whisper.cpp checkout 4523d0ce373ee4b2176b3251fff29fd4864fcf38
cmake -S .vendor/whisper.cpp \
  -B .vendor/whisper.cpp/build \
  -DCMAKE_BUILD_TYPE=Release
cmake --build .vendor/whisper.cpp/build -j2
.vendor/whisper.cpp/models/download-ggml-model.sh tiny.en
```

Add these non-secret settings to `/home/lumabot21/.lumakit/config.env`:

```dotenv
LUMIKIT_WHISPER_DIR="/home/lumabot21/lumakit/.vendor/whisper.cpp"
LUMIKIT_WHISPER_BIN="/home/lumabot21/lumakit/.vendor/whisper.cpp/build/bin/whisper-cli"
LUMIKIT_WHISPER_MODEL="/home/lumabot21/lumakit/.vendor/whisper.cpp/models/ggml-tiny.en.bin"
LUMIKIT_EDGE_TTS_PYTHON="/home/lumabot21/lumakit/.venv/bin/python"
LUMIKIT_TTS_VOICE="en-US-AvaNeural"
LUMIKIT_TTS_FORMAT="mp3"
```

After LumaKit is running, the owner can enable replies and choose the voice
from Telegram:

```text
/voice on
/voice set ava
/voice status
```

Voice notes are still transcribed when outgoing voice replies are off.
The initial round-trip test synthesized a short MP3 in 1.77 seconds and
transcribed it in 2.12 seconds, with a measured peak child-process RSS of
about 175 MB. The `tiny.en` model file is about 75 MB on disk.

## Python 3.13 ARM compatibility

The original upstream pin `tree-sitter-languages==1.10.2` has no compatible
Python 3.13 ARM64 distribution. The tested LumaBot branch replaces it with:

```text
tree-sitter==0.26.0
tree-sitter-language-pack==1.13.2
```

The parser uses the modern `Query` and `QueryCursor` API. Keep this
compatibility change when updating from upstream until upstream adopts an
equivalent fix.

## Developer configuration

Never put real credentials in the repository. Store them in:

```text
/home/lumabot21/.lumakit/config.env
```

The minimal hosted-xAI and Telegram configuration is:

```dotenv
LLM_PROVIDER="xai"
LLM_API_KEY="replace-with-developer-key"
TELEGRAM_BOT_TOKEN="replace-with-bot-token"
TELEGRAM_ALLOWED_IDS="replace-with-owner-chat-id"
```

The first Telegram ID is the owner. Keep LumaKit safe mode enabled. Do not
send API keys or bot tokens through Telegram messages.

Protect the configuration:

```bash
chmod 600 /home/lumabot21/.lumakit/config.env
```

On a shipped device, collect these values through a local first-run setup
page rather than asking the developer to edit a file.

## Provider validation

Start LumaKit temporarily:

```bash
cd /home/lumabot21/lumakit
.venv/bin/lumakit serve
```

Confirm that startup reports:

```text
Web UI: http://localhost:7865
Telegram: enabled
Telegram bridge running. 1 authorized user(s).
```

Send the bot a short message and confirm that it replies through the hosted
provider. Stop the foreground process with `Ctrl+C` before installing the
service.

## Always-on service

Generate a unit tied to the LumaKit virtual environment and private config:

```bash
cd /home/lumabot21/lumakit
.venv/bin/lumakit service install --force \
  --env-file /home/lumabot21/.lumakit/config.env
```

Before installation, verify that `lumakit.service` contains:

```text
ExecStart=/home/lumabot21/lumakit/.venv/bin/python -m lumakit serve
```

Install and start it:

```bash
sudo cp lumakit.service /etc/systemd/system/lumakit.service
sudo systemctl daemon-reload
sudo systemctl enable --now lumakit.service
```

Validate the service:

```bash
.venv/bin/lumakit status
sudo systemctl status lumakit.service
sudo journalctl -u lumakit.service -n 50 --no-pager
```

Expected status includes `running`, `telegram: configured`, and the selected
hosted model.

## Resource check

Record the steady-state process and system memory:

```bash
pid=$(systemctl show -p MainPID --value lumakit.service)
ps -o pid,rss,vsz,%mem,etime,cmd -p "$pid"
free -h
swapon --show
```

On the initial 2 GB LumaBot, LumaKit used about 69 MB RSS while idle with
the voice stack configured. Whisper is transient, so it does not increase
idle RSS. Recheck idle and transcription-time memory after camera support
and `lumabotd` are running together.

## Updating another LumaBot

Before an update, stop the service and confirm the worktree is clean:

```bash
sudo systemctl stop lumakit.service
cd /home/lumabot21/lumakit
git status
git fetch origin
```

Integrate upstream changes without dropping the LumaBot compatibility patch,
then reinstall and retest:

```bash
.venv/bin/python -m pip install -e '.[speech]'
.venv/bin/python -m pytest -q
sudo systemctl restart lumakit.service
.venv/bin/lumakit status
```

Do not use an unreviewed update directly on a moving robot.

## Recovery and secret rotation

If startup fails:

```bash
sudo journalctl -u lumakit.service -n 100 --no-pager
sudo systemctl restart lumakit.service
```

If a developer key, Telegram bot token, robot, or SD card is compromised,
revoke the affected credential at the provider, replace it in `config.env`,
restore mode `600`, and restart LumaKit.

Factory reset must remove developer credentials, Telegram ownership, Wi-Fi
credentials, conversation history, and device-specific runtime data before
the robot changes owners.
