# Synthesise the benchmark call: one WAV per voice, 16 kHz mono, lines separated by 1.2 s of silence.
# Writes bench/stt/audio/<voice>.wav and bench/stt/audio/reference.json.
Add-Type -AssemblyName System.Speech
$dir = Join-Path $PSScriptRoot "audio"
New-Item -ItemType Directory -Force $dir | Out-Null

$lines = @(
  "So basically we have three people who spend most of their morning typing incoming orders from email into Exact.",
  "What's your hourly rate?",
  "We're also talking to Flowbase, they said it would be about forty cents per document.",
  "Honestly the last IT company we worked with went way over budget.",
  "Is our data going to leave the Netherlands?",
  "Right now we use Zapier for some of it but it keeps breaking.",
  "Look, the thing is we grew from twenty to sixty people in two years and the admin side never caught up, so every Monday somebody spends the whole day reconciling invoices between the webshop and the accounting package, and when that person is on holiday it just piles up and our customers start calling us about missing orders, which honestly is embarrassing.",
  "I'd need to discuss this with my co-owner first.",
  "Sorry, what's your hourly rate again? I still don't get how you price this."
)

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($voice in @("Microsoft David Desktop", "Microsoft Zira Desktop", "Microsoft Hazel Desktop")) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice($voice)
  $name = ($voice -split " ")[1].ToLower()
  $s.SetOutputToWaveFile((Join-Path $dir "$name.wav"), $format)
  $p = New-Object System.Speech.Synthesis.PromptBuilder
  foreach ($l in $lines) { $p.AppendText($l); $p.AppendBreak([TimeSpan]::FromMilliseconds(1200)) }
  $s.Speak($p)
  $s.Dispose()
}
$lines | ConvertTo-Json | Out-File -Encoding utf8 (Join-Path $dir "reference.json")
