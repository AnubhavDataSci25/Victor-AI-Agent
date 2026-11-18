/**
 * Victor Client Application Controller
 * Handles WebSocket communication, Web Audio streaming, HUD telemetry,
 * real-time transcript streaming, and Particle Orb synchronization.
 */

let ws = null;
let wsReconnectTimer = null;

// DOM Elements
const authOverlay = document.getElementById('auth-overlay');
const pinStage = document.getElementById('pinStage');
const pinHiddenInput = document.getElementById('pinHiddenInput');
const pinOrbitRing = document.getElementById('pinOrbitRing');
const verdictTile = document.getElementById('verdictTile');
const pinVerifyBtn = document.getElementById('pinVerifyBtn');
const pinStatusText = document.getElementById('pinStatusText');
const pinSubtext = document.getElementById('pinSubtext');
const lockBtn = document.getElementById('lockTerminalBtn');
const clearTranscriptBtn = document.getElementById('clearTranscriptBtn');

// Telemetry Elements
const hudClock = document.getElementById('hudClock');
const hudDate = document.getElementById('hudDate');
const globalStatusText = document.getElementById('globalStatusText');
const globalStatusPill = document.getElementById('globalStatusPill');
const orbStateText = document.getElementById('orbStateText');
const orbStateBadge = document.getElementById('orbStateBadge');
const eqBars = document.querySelectorAll('.eq-bar');

// Transcript Elements
const transcriptStream = document.getElementById('transcriptStream');
const transcriptEmpty = document.getElementById('transcriptEmpty');
const transcriptCount = document.getElementById('transcriptCount');

let currentState = "LOCKED";
let transcriptEntries = [];

// Web Audio API Globals
let audioCtx = null;
let scriptProcessor = null;
let micAnalyser = null;
let speakerAnalyser = null;
let nextPlayTime = 0;
let isSpeaking = false;
let isVictorSpeaking = false;
let micMutedUntil = 0;
let mediaStream = null;
let activeAudioSources = [];
let firstCommandRecognizer = null;
let currentUtterance = null; // Preserved in outer scope to prevent V8 GC bug with SpeechSynthesis
let stateWatchdogTimer = null;

// ==========================================================================
// REAL-TIME CHRONO TELEMETRY (CLOCK & DATE)
// ==========================================================================
let isMicMuted = false;

function updateChronoTelemetry() {
    const now = new Date();

    if (hudClock) {
        hudClock.textContent = now.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });
    }

    if (hudDate) {
        hudDate.textContent = now.toLocaleDateString('en-US', {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
    }

    const greetingTitle = document.getElementById('greetingTitle');
    if (greetingTitle) {
        const hr = now.getHours();
        const period = hr < 12 ? 'Good Morning' : (hr < 17 ? 'Good Afternoon' : 'Good Evening');
        greetingTitle.innerHTML = `${period}, <span class="greeting-name">Anubhav</span> 👋`;
    }
}
setInterval(updateChronoTelemetry, 1000);
updateChronoTelemetry();

// ==========================================================================
// AUDIO PIPELINE (16kHz PCM Input / 24kHz PCM Output)
// ==========================================================================
async function startAudioPipeline() {
    const hasLiveMic = mediaStream && mediaStream.getAudioTracks().some(t => t.readyState === 'live');
    if (audioCtx && hasLiveMic) {
        if (audioCtx.state === 'suspended') {
            await audioCtx.resume();
        }
        return;
    }
    if (audioCtx && !hasLiveMic) {
        try { await audioCtx.close(); } catch (_) {}
        audioCtx = null;
    }
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        if (audioCtx.state === 'suspended') {
            await audioCtx.resume();
        }
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: { ideal: true },
                noiseSuppression: { ideal: true },
                autoGainControl: { ideal: true },
                channelCount: 1,
                sampleRate: 16000
            }
        });
        const source = audioCtx.createMediaStreamSource(mediaStream);
        
        // Microphone Analyser Node
        micAnalyser = audioCtx.createAnalyser();
        micAnalyser.fftSize = 512;
        micAnalyser.smoothingTimeConstant = 0.82;
        source.connect(micAnalyser);

        // Speaker Analyser Node
        speakerAnalyser = audioCtx.createAnalyser();
        speakerAnalyser.fftSize = 512;
        speakerAnalyser.smoothingTimeConstant = 0.82;
        speakerAnalyser.connect(audioCtx.destination);

        // Capture Processor for streaming to backend (2048 samples = 128ms low-latency frames)
        scriptProcessor = audioCtx.createScriptProcessor(2048, 1, 1);
        let silentFramesCount = 0;
        let hasSpokenInBurst = false;
        let lastAudioSentAt = Date.now();
        const SILENCE_THRESHOLD = 0.0015;

        scriptProcessor.onaudioprocess = (e) => {
            // Stream during active conversational states; suppress during execution, thinking, or finalizing
            if (currentState !== "ACTIVE" && currentState !== "LISTENING" && currentState !== "WAITING_FOR_CONTINUATION" && currentState !== "SPEECH_ACTIVE" && currentState !== "SPEAKING") return;
            if (currentState === "EXECUTING" || currentState === "THINKING" || currentState === "FINALIZING") return;

            // Acoustic echo suppression & user mute: drop mic packets while muted or Victor is speaking
            if (isMicMuted || isVictorSpeaking || Date.now() < micMutedUntil) return;

            const inputData = e.inputBuffer.getChannelData(0);

            const pcm16 = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
                let s = Math.max(-1, Math.min(1, inputData[i]));
                pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            
            let binary = '';
            const bytes = new Uint8Array(pcm16.buffer);
            for (let i = 0; i < bytes.byteLength; i++) {
                binary += String.fromCharCode(bytes[i]);
            }
            
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    type: "audio_input",
                    data: btoa(binary)
                }));
            }
        };
        
        const dummyGain = audioCtx.createGain();
        dummyGain.gain.value = 0;
        
        source.connect(scriptProcessor);
        scriptProcessor.connect(dummyGain);
        dummyGain.connect(audioCtx.destination);

        // Start animation frame loop reading frequencies into the Orb and Equalizer
        trackAudioEnergy();
        console.log("[Victor Audio] Hardware audio pipeline initialized (16kHz PCM, Echo-cancelled).");
    } catch (err) {
        console.error("Microphone access denied or error:", err);
    }
}

function stopAllAudioPlayback() {
    for (const src of activeAudioSources) {
        try { src.stop(); } catch (_) {}
    }
    activeAudioSources = [];
    if (audioCtx) {
        nextPlayTime = audioCtx.currentTime;
    } else {
        nextPlayTime = 0;
    }
    isSpeaking = false;
}

function stopAudioPipeline() {
    stopFirstCommandListener();
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    stopAllAudioPlayback();

    if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
    }
    scriptProcessor = null;
    micAnalyser = null;
    speakerAnalyser = null;
    nextPlayTime = 0;
    isSpeaking = false;
    isVictorSpeaking = false;
    micMutedUntil = 0;
    
    console.log("[Victor Audio] Hardware pipeline torn down securely.");
}

function trackAudioEnergy() {
    requestAnimationFrame(trackAudioEnergy);

    let energy = 0.0;
    let low = 0.0;
    let mid = 0.0;
    let high = 0.0;

    const targetAnalyser = (isSpeaking && speakerAnalyser) ? speakerAnalyser : micAnalyser;
    if (targetAnalyser) {
        const freqData = new Uint8Array(targetAnalyser.frequencyBinCount);
        targetAnalyser.getByteFrequencyData(freqData);

        const getBand = (start, end) => {
            let sum = 0;
            const count = Math.max(1, end - start);
            for (let i = start; i < end; i++) sum += freqData[i];
            return (sum / count) / 255.0;
        };

        low = getBand(2, 18);
        mid = getBand(18, 92);
        high = getBand(92, 220);
        energy = (low * 0.5 + mid * 0.35 + high * 0.15);

        // Animate Equalizer Bars in HUD
        if (eqBars && eqBars.length > 0) {
            const step = Math.floor(freqData.length / eqBars.length);
            for (let i = 0; i < eqBars.length; i++) {
                const val = (freqData[i * step] / 255.0);
                const h = Math.max(4, Math.min(20, Math.round(val * 22)));
                eqBars[i].style.height = `${h}px`;
                eqBars[i].style.opacity = Math.max(0.3, val * 1.2);
            }
        }
    }

    if (window.VictorOrbInstance) {
        window.VictorOrbInstance.setAudioEnergy(energy, low, mid, high);
    }
}

// --- AUDIO PLAYBACK (24kHz PCM) ---
function playAudioChunk(base64Data) {
    if (!audioCtx || !speakerAnalyser) return;
    
    if (stateWatchdogTimer) {
        clearTimeout(stateWatchdogTimer);
        stateWatchdogTimer = null;
    }

    // Silence browser speech synthesis if Gemini Live audio is streaming
    if ('speechSynthesis' in window && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
        try { window.speechSynthesis.cancel(); } catch (_) {}
        currentUtterance = null;
    }

    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    
    const int16Array = new Int16Array(bytes.buffer);
    const audioBuffer = audioCtx.createBuffer(1, int16Array.length, 24000);
    const channelData = audioBuffer.getChannelData(0);
    for (let i = 0; i < int16Array.length; i++) {
        channelData[i] = int16Array[i] / 32768.0;
    }
    
    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(speakerAnalyser);
    activeAudioSources.push(source);
    
    if (nextPlayTime < audioCtx.currentTime) {
        nextPlayTime = audioCtx.currentTime + 0.05; 
    }
    source.start(nextPlayTime);
    nextPlayTime += audioBuffer.duration;

    isSpeaking = true;
    isVictorSpeaking = true;

    // Safety watchdog: auto-clear speaking lock if source.onended drops
    const chunkWatchdogMs = Math.ceil((audioBuffer.duration + 0.8) * 1000);
    setTimeout(() => {
        const idx = activeAudioSources.indexOf(source);
        if (idx !== -1) activeAudioSources.splice(idx, 1);
        if (activeAudioSources.length === 0) {
            isSpeaking = false;
            isVictorSpeaking = false;
        }
    }, chunkWatchdogMs);

    source.onended = () => {
        const idx = activeAudioSources.indexOf(source);
        if (idx !== -1) activeAudioSources.splice(idx, 1);
        if (activeAudioSources.length === 0 || audioCtx.currentTime >= nextPlayTime - 0.02) {
            isSpeaking = false;
            isVictorSpeaking = false;
            micMutedUntil = Date.now() + 500; // Room reverb decay
        }
    };
}

// ==========================================================================
// TRANSCRIPT STREAM MANAGEMENT
// ==========================================================================
function appendTranscriptEntry(role, text) {
    if (!text || !text.trim()) return;
    if (transcriptEmpty) transcriptEmpty.style.display = 'none';

    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });

    // If previous entry was from the same role within 2 seconds, concatenate for streaming sentences
    const lastEntry = transcriptEntries[transcriptEntries.length - 1];
    if (lastEntry && lastEntry.role === role && (Date.now() - lastEntry.timestamp < 2500)) {
        const needsSpace = lastEntry.text.length > 0 && !/\s$/.test(lastEntry.text) && !/^\s/.test(text) && !/^[.,!?;:]/.test(text);
        lastEntry.text += (needsSpace ? " " : "") + text;
        lastEntry.timestamp = Date.now();
        const lastEl = transcriptStream.querySelector(`.transcript-entry:last-child .entry-text`);
        if (lastEl) {
            lastEl.textContent = lastEntry.text;
            transcriptStream.scrollTop = transcriptStream.scrollHeight;
            return;
        }
    }

    const entry = {
        role: role,
        text: text,
        time: timeStr,
        timestamp: Date.now()
    };
    transcriptEntries.push(entry);

    const article = document.createElement('article');
    article.className = `transcript-entry transcript-entry--${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'entry-avatar';
    avatar.textContent = role === 'user' ? 'A' : (role === 'tool' ? '</>' : 'V');

    const body = document.createElement('div');
    body.className = 'entry-body';

    const header = document.createElement('div');
    header.className = 'entry-header';

    const roleSpan = document.createElement('span');
    roleSpan.className = 'entry-role';
    roleSpan.textContent = role === 'user' ? 'YOU' : (role === 'tool' ? 'SYSTEM ACTION' : 'VICTOR');

    const timeSpan = document.createElement('span');
    timeSpan.className = 'entry-time';
    timeSpan.textContent = timeStr;

    header.appendChild(roleSpan);
    header.appendChild(timeSpan);

    const textP = document.createElement('p');
    textP.className = 'entry-text';
    textP.textContent = text;

    body.appendChild(header);
    body.appendChild(textP);

    article.appendChild(avatar);
    article.appendChild(body);

    transcriptStream.appendChild(article);
    transcriptStream.scrollTop = transcriptStream.scrollHeight;

    if (transcriptCount) {
        transcriptCount.textContent = `${transcriptEntries.length} ${transcriptEntries.length === 1 ? 'event' : 'events'}`;
    }
}

if (clearTranscriptBtn) {
    clearTranscriptBtn.addEventListener('click', () => {
        transcriptEntries = [];
        transcriptStream.innerHTML = '';
        if (transcriptEmpty) {
            transcriptEmpty.style.display = 'flex';
            transcriptStream.appendChild(transcriptEmpty);
        }
        if (transcriptCount) transcriptCount.textContent = 'standby';
    });
}

// ==========================================================================
// STATE & WEBSOCKET MANAGEMENT
// ==========================================================================
function applyAtmosphericMood(mood) {
    if (!document.body) return;
    if (mood === "processing") {
        document.body.classList.remove('state-error');
        document.body.classList.add('state-processing');
    } else if (mood === "error") {
        document.body.classList.remove('state-processing');
        document.body.classList.add('state-error');
    } else {
        document.body.classList.remove('state-processing');
        document.body.classList.remove('state-error');
    }
}

function initOrbMoodSync() {
    if (window.VictorOrbInstance) {
        window.VictorOrbInstance.onMoodChange = (mood) => {
            applyAtmosphericMood(mood);
            if (mood === "normal") {
                if (currentState !== "ERROR" && currentState !== "OFFLINE") {
                    if (orbStateText && orbStateText.textContent === "ERROR") {
                        orbStateText.textContent = currentState || "LISTENING";
                    }
                    if (globalStatusText && globalStatusText.textContent === "ERROR") {
                        globalStatusText.textContent = currentState || "ACTIVE";
                    }
                }
            }
        };
        applyAtmosphericMood(window.VictorOrbInstance.getMood());
    } else {
        setTimeout(initOrbMoodSync, 100);
    }
}
initOrbMoodSync();

function updateUIState(stateName) {
    const s = String(stateName || "").toUpperCase();

    // Safety watchdog: clear any prior pending state watchdog
    if (stateWatchdogTimer) {
        clearTimeout(stateWatchdogTimer);
        stateWatchdogTimer = null;
    }

    // Auto-sync currentState with active conversational states so audio recording is never blocked
    if (s === "ACTIVE" || s === "LISTENING" || s === "SPEAKING") {
        if (currentState !== "LOCKED" && currentState !== "CLOSED" && currentState !== "OFFLINE" && currentState !== "BIOMETRIC_PENDING") {
            currentState = s;
        }
    } else if (s === "THINKING" || s === "PROCESSING" || s === "EXECUTING" || s === "FINALIZING") {
        // If Victor remains in THINKING/EXECUTING/FINALIZING for > 20s without response, auto-restore LISTENING
        stateWatchdogTimer = setTimeout(() => {
            console.warn(`[Victor Watchdog] State '${s}' timed out after 20s. Restoring to LISTENING.`);
            if (currentState !== "LOCKED" && currentState !== "CLOSED" && currentState !== "OFFLINE" && currentState !== "BIOMETRIC_PENDING") {
                currentState = "LISTENING";
                updateUIState("LISTENING");
            }
        }, 20000);
    }
    if (globalStatusText) {
        if (s === "ACTIVE" || s === "LISTENING" || s === "SPEAKING") {
            globalStatusText.textContent = "System: Online";
        } else if (s === "THINKING" || s === "PROCESSING" || s === "EXECUTING") {
            globalStatusText.textContent = `System: ${s.charAt(0) + s.slice(1).toLowerCase()}`;
        } else {
            globalStatusText.textContent = s;
        }
    }
    if (orbStateText) {
        if (s === "ACTIVE" || s === "LISTENING") {
            orbStateText.textContent = isMicMuted ? "Mic Muted" : "Live & Listening";
        } else if (s === "WAITING_FOR_CONTINUATION") {
            orbStateText.textContent = "Live & Listening";
        } else if (s === "FINALIZING") {
            orbStateText.textContent = "Finalizing...";
        } else if (s === "TRANSCRIBING") {
            orbStateText.textContent = "Transcribing...";
        } else if (s === "SPEAKING") {
            orbStateText.textContent = "Speaking";
        } else if (s === "THINKING" || s === "PROCESSING" || s === "EXECUTING") {
            orbStateText.textContent = s.charAt(0) + s.slice(1).toLowerCase() + "...";
        } else {
            orbStateText.textContent = s;
        }
    }

    const micLabel = document.getElementById('micControlLabel');
    if (micLabel) {
        if (isMicMuted) {
            micLabel.textContent = "Microphone Muted";
        } else if (s === "SPEAKING") {
            micLabel.textContent = "Speaking...";
        } else if (s === "THINKING" || s === "PROCESSING" || s === "EXECUTING") {
            micLabel.textContent = "Processing...";
        } else if (s === "ACTIVE" || s === "LISTENING") {
            micLabel.textContent = "Listening...";
        } else {
            micLabel.textContent = "Tap to Speak";
        }
    }
    
    if (window.VictorOrbInstance) {
        window.VictorOrbInstance.setState(s);
        applyAtmosphericMood(window.VictorOrbInstance.getMood());
    } else {
        if (s.includes("THINK") || s.includes("PROCESS") || s.includes("EXEC")) {
            applyAtmosphericMood("processing");
        } else if (s.includes("ERR") || s.includes("FAIL")) {
            applyAtmosphericMood("error");
        } else {
            applyAtmosphericMood("normal");
        }
    }
}

// ==========================================================================
// 6-DIGIT 3D PIN VERIFICATION & SECURITY CONTROLLER
// ==========================================================================
let enteredPin = "";
let isVerifying = false;
let isLockedOut = false;
let autoResetTimer = null;
let lockoutIntervalId = null;

const HARDCODED_PIN = "081225";
const TOTAL_SLOTS = 6;
const MAX_ATTEMPTS = 3;
const LOCKOUT_DURATION_MS = 10 * 60 * 1000; // 10 minutes (600,000 ms)

const STORAGE_KEY_FAILED_ATTEMPTS = "victor_pin_failed_attempts";
const STORAGE_KEY_LOCKOUT_UNTIL = "victor_pin_lockout_until";

let failedAttempts = parseInt(localStorage.getItem(STORAGE_KEY_FAILED_ATTEMPTS) || "0", 10);
if (isNaN(failedAttempts) || failedAttempts < 0) failedAttempts = 0;

const pinSlots = document.querySelectorAll('.pin-slot-anchor');
const checkIcon = verdictTile ? verdictTile.querySelector('.check-icon') : null;
const crossIcon = verdictTile ? verdictTile.querySelector('.cross-icon') : null;
const lockIcon = verdictTile ? verdictTile.querySelector('.lock-icon') : null;
const pinAuthCard = document.querySelector('.pin-auth-card');

function clearLockoutState() {
    localStorage.removeItem(STORAGE_KEY_LOCKOUT_UNTIL);
    localStorage.removeItem(STORAGE_KEY_FAILED_ATTEMPTS);
    failedAttempts = 0;
    isLockedOut = false;
    if (lockoutIntervalId) {
        clearInterval(lockoutIntervalId);
        lockoutIntervalId = null;
    }
    if (pinAuthCard) pinAuthCard.classList.remove('is-locked');
    if (pinSubtext) pinSubtext.textContent = "ENTER 6-DIGIT AUTHORIZATION PIN";
    if (pinHiddenInput) pinHiddenInput.disabled = false;
}

function enterLockoutMode(lockoutUntil) {
    isLockedOut = true;
    isVerifying = false;
    if (autoResetTimer) {
        clearTimeout(autoResetTimer);
        autoResetTimer = null;
    }

    localStorage.setItem(STORAGE_KEY_LOCKOUT_UNTIL, lockoutUntil.toString());
    localStorage.setItem(STORAGE_KEY_FAILED_ATTEMPTS, MAX_ATTEMPTS.toString());
    failedAttempts = MAX_ATTEMPTS;

    if (pinHiddenInput) {
        pinHiddenInput.value = "";
        pinHiddenInput.blur();
        pinHiddenInput.disabled = true;
    }
    if (pinVerifyBtn) pinVerifyBtn.classList.remove('is-visible');

    if (pinAuthCard) pinAuthCard.classList.add('is-locked');
    if (pinOrbitRing) {
        pinOrbitRing.classList.remove('is-spinning', 'is-orbiting');
        pinOrbitRing.classList.add('is-screwing-down');
    }

    if (verdictTile) {
        verdictTile.classList.remove('verdict-success', 'verdict-error');
        verdictTile.classList.add('is-visible', 'verdict-locked');
    }
    if (checkIcon) checkIcon.classList.add('hidden');
    if (crossIcon) crossIcon.classList.add('hidden');
    if (lockIcon) lockIcon.classList.remove('hidden');

    if (pinSubtext) {
        pinSubtext.innerHTML = '<span style="color: var(--accent-rose); font-weight: 600; letter-spacing: 2px;">SECURITY PROTOCOL ACTIVE // TERMINAL LOCKED</span>';
    }

    function updateCountdown() {
        const now = Date.now();
        const diffMs = lockoutUntil - now;

        if (diffMs <= 0) {
            clearLockoutState();
            resetPINBoard(false);
            if (pinStatusText) {
                pinStatusText.innerHTML = '<span style="color: var(--accent-emerald); font-weight: 600; letter-spacing: 1.5px;">LOCKOUT EXPIRED // ENTER PIN TO RETRY</span>';
            }
            return;
        }

        const totalSec = Math.ceil(diffMs / 1000);
        const mins = Math.floor(totalSec / 60);
        const secs = totalSec % 60;
        const formattedTime = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

        if (pinStatusText) {
            pinStatusText.innerHTML = `
                <div style="color: var(--accent-rose); font-weight: 600; letter-spacing: 2px; font-size: 0.82rem;">
                    MAX ATTEMPTS EXCEEDED (3/3 WRONG)
                </div>
                <div class="lockout-countdown">
                    ${formattedTime}
                </div>
                <div style="font-size: 0.72rem; color: var(--text-secondary); letter-spacing: 1px; margin-top: 4px;">
                    Terminal locked for 10 minutes. Cooldown in progress.
                </div>
            `;
        }
    }

    updateCountdown();
    if (lockoutIntervalId) clearInterval(lockoutIntervalId);
    lockoutIntervalId = setInterval(updateCountdown, 1000);
}

function checkLockoutState() {
    const lockoutUntilStr = localStorage.getItem(STORAGE_KEY_LOCKOUT_UNTIL);
    if (lockoutUntilStr) {
        const lockoutUntil = parseInt(lockoutUntilStr, 10);
        if (Date.now() < lockoutUntil) {
            enterLockoutMode(lockoutUntil);
            return true;
        } else {
            clearLockoutState();
        }
    }
    return false;
}

function updateSlotVisuals() {
    if (isLockedOut) return;
    pinSlots.forEach((slot, idx) => {
        if (idx < enteredPin.length) {
            slot.classList.add('is-flipped');
            slot.classList.remove('is-active');
        } else if (idx === enteredPin.length && !isVerifying) {
            slot.classList.remove('is-flipped');
            slot.classList.add('is-active');
        } else {
            slot.classList.remove('is-flipped');
            slot.classList.remove('is-active');
        }
    });

    if (enteredPin.length === TOTAL_SLOTS && !isVerifying) {
        if (pinVerifyBtn) pinVerifyBtn.classList.add('is-visible');
    } else {
        if (pinVerifyBtn) pinVerifyBtn.classList.remove('is-visible');
    }
}

async function triggerVerification() {
    if (isLockedOut || isVerifying || enteredPin.length !== TOTAL_SLOTS) return;
    isVerifying = true;

    if (pinHiddenInput) pinHiddenInput.blur();
    if (pinVerifyBtn) pinVerifyBtn.classList.remove('is-visible');
    if (pinStatusText) {
        pinStatusText.innerHTML = '<span style="color: var(--accent-cyan); letter-spacing: 2px;">SYNCHRONIZING ORBIT...</span>';
    }

    // Step 4: Dynamically curl/reposition into circular orbit
    if (pinOrbitRing) {
        pinOrbitRing.classList.add('is-orbiting');
    }

    // Step 5: Continuous Spin & Flip (2 seconds)
    await new Promise(resolve => setTimeout(resolve, 50));
    if (pinOrbitRing) {
        pinOrbitRing.classList.add('is-spinning');
    }
    if (pinStatusText) {
        pinStatusText.innerHTML = '<span style="color: var(--accent-cyan); letter-spacing: 2px;">NEURAL HASH VERIFICATION...</span>';
    }

    // Wait exactly 2000ms for the orbit spin and flip to complete
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Step 6: The Verdict (Screw Down)
    if (pinOrbitRing) {
        pinOrbitRing.classList.remove('is-spinning');
        pinOrbitRing.classList.add('is-screwing-down');
    }

    if (verdictTile) {
        verdictTile.classList.add('is-visible');
    }

    // Step 7: Success / Error Logic
    const isCorrect = (enteredPin === HARDCODED_PIN);

    if (isCorrect) {
        clearLockoutState();

        if (verdictTile) {
            verdictTile.classList.add('verdict-success');
        }
        if (checkIcon) checkIcon.classList.remove('hidden');
        if (crossIcon) crossIcon.classList.add('hidden');
        if (lockIcon) lockIcon.classList.add('hidden');
        if (pinStatusText) {
            pinStatusText.innerHTML = '<span style="color: var(--accent-emerald); font-weight: 600; letter-spacing: 2px;">VERIFIED // ACCESS GRANTED</span>';
        }

        // Initialize audio pipeline in background so mic prompt never stalls auth
        startAudioPipeline().catch(err => console.warn("Audio pipeline init:", err));

        // Authenticate with Victor backend session manager
        ws.send(JSON.stringify({
            type: "auth_request",
            credential: enteredPin
        }));

        // Move to Victor UI after short display of checkmark
        setTimeout(() => {
            if (authOverlay) {
                authOverlay.style.opacity = '0';
                setTimeout(() => {
                    authOverlay.style.display = 'none';
                    resetPINBoard(false);
                }, 400);
            }
        }, 900);

    } else {
        // Increment failed attempts
        failedAttempts++;
        localStorage.setItem(STORAGE_KEY_FAILED_ATTEMPTS, failedAttempts.toString());

        if (failedAttempts >= MAX_ATTEMPTS) {
            // Lock the website for straight 10 minutes
            const lockoutUntil = Date.now() + LOCKOUT_DURATION_MS;
            enterLockoutMode(lockoutUntil);
        } else {
            // Retries remaining (Attempt 1 or 2 failed)
            const remaining = MAX_ATTEMPTS - failedAttempts;

            if (verdictTile) {
                verdictTile.classList.add('verdict-error');
            }
            if (crossIcon) crossIcon.classList.remove('hidden');
            if (checkIcon) checkIcon.classList.add('hidden');
            if (lockIcon) lockIcon.classList.add('hidden');

            if (pinStatusText) {
                pinStatusText.innerHTML = `
                    <span style="color: var(--accent-rose); font-weight: 600; letter-spacing: 2px;">INCORRECT PIN // ${remaining} ${remaining === 1 ? 'ATTEMPT' : 'ATTEMPTS'} REMAINING</span>
                    <br><span style="font-size: 0.72rem; color: var(--text-secondary); letter-spacing: 1px; margin-top: 4px; display: inline-block;">Keypad resetting...</span>
                `;
            }

            // Automatically reset keypad after 1.3s so the user can immediately re-enter PIN without refreshing
            autoResetTimer = setTimeout(() => {
                resetPINBoard(true);
            }, 1300);
        }
    }
}

function resetPINBoard(showRemainingAttempts = true) {
    if (isLockedOut) return;
    if (autoResetTimer) {
        clearTimeout(autoResetTimer);
        autoResetTimer = null;
    }

    enteredPin = "";
    if (pinHiddenInput) {
        pinHiddenInput.value = "";
        pinHiddenInput.disabled = false;
    }
    isVerifying = false;

    if (pinOrbitRing) {
        pinOrbitRing.classList.remove('is-orbiting', 'is-spinning', 'is-screwing-down');
    }

    if (verdictTile) {
        verdictTile.classList.remove('is-visible', 'verdict-success', 'verdict-error', 'verdict-locked');
        if (checkIcon) checkIcon.classList.add('hidden');
        if (crossIcon) crossIcon.classList.add('hidden');
        if (lockIcon) lockIcon.classList.add('hidden');
    }

    if (pinVerifyBtn) {
        pinVerifyBtn.classList.remove('is-visible');
    }

    if (pinStatusText) {
        if (showRemainingAttempts && failedAttempts > 0 && failedAttempts < MAX_ATTEMPTS) {
            const remaining = MAX_ATTEMPTS - failedAttempts;
            pinStatusText.innerHTML = `<span style="color: var(--accent-amber); font-size: 0.76rem; letter-spacing: 1.5px; font-weight: 500;">ATTEMPT ${failedAttempts + 1} OF ${MAX_ATTEMPTS} // ${remaining} ${remaining === 1 ? 'RETRY' : 'RETRIES'} REMAINING</span>`;
        } else if (!showRemainingAttempts) {
            pinStatusText.innerHTML = "";
        }
    }

    updateSlotVisuals();

    if (authOverlay && authOverlay.style.display !== 'none') {
        setTimeout(() => {
            if (pinHiddenInput && !isLockedOut) pinHiddenInput.focus();
        }, 60);
    }
}

// Step 1: Global direct keyboard capture for PIN Gateway
window.addEventListener('keydown', (e) => {
    // If auth overlay is hidden, do nothing
    if (!authOverlay || authOverlay.style.display === 'none') return;
    if (isLockedOut || isVerifying) return;

    // Reset from error state on any keypress
    if (verdictTile && verdictTile.classList.contains('verdict-error')) {
        if (autoResetTimer) {
            clearTimeout(autoResetTimer);
            autoResetTimer = null;
        }
        resetPINBoard(true);
    }

    // Handle Backspace & Delete
    if (e.key === 'Backspace' || e.key === 'Delete') {
        e.preventDefault();
        if (enteredPin.length > 0) {
            enteredPin = enteredPin.slice(0, -1);
            if (pinHiddenInput) pinHiddenInput.value = enteredPin;
            updateSlotVisuals();
        }
        return;
    }

    // Handle Enter
    if (e.key === 'Enter') {
        if (enteredPin.length === TOTAL_SLOTS) {
            e.preventDefault();
            triggerVerification();
        }
        return;
    }

    // Detect numeric key: 0-9 or Numpad 0-9
    let digit = null;
    if (/^[0-9]$/.test(e.key)) {
        digit = e.key;
    } else if (e.code && /^Numpad[0-9]$/.test(e.code)) {
        digit = e.code.slice(6);
    }

    if (digit !== null) {
        e.preventDefault();
        if (enteredPin.length < TOTAL_SLOTS) {
            enteredPin += digit;
            if (pinHiddenInput) pinHiddenInput.value = enteredPin;
            updateSlotVisuals();

            // Auto-trigger verification when 6th digit entered
            if (enteredPin.length === TOTAL_SLOTS) {
                setTimeout(() => {
                    if (enteredPin.length === TOTAL_SLOTS && !isVerifying && !isLockedOut) {
                        triggerVerification();
                    }
                }, 80);
            }
        }
        return;
    }
});

// Virtual keyboard, paste & autofill fallback for pinHiddenInput
if (pinHiddenInput) {
    pinHiddenInput.addEventListener('input', () => {
        if (isLockedOut || isVerifying) return;
        const clean = pinHiddenInput.value.replace(/\D/g, '').slice(0, TOTAL_SLOTS);
        if (clean !== enteredPin) {
            enteredPin = clean;
            pinHiddenInput.value = clean;
            updateSlotVisuals();
            if (enteredPin.length === TOTAL_SLOTS) {
                setTimeout(() => {
                    if (enteredPin.length === TOTAL_SLOTS && !isVerifying && !isLockedOut) {
                        triggerVerification();
                    }
                }, 80);
            }
        }
    });

    pinHiddenInput.addEventListener('keydown', (e) => {
        if (isLockedOut || isVerifying) return;
        if (e.key === 'Enter' && enteredPin.length === TOTAL_SLOTS) {
            triggerVerification();
        }
    });
}

// Click anywhere on auth overlay or card to auto-focus pinHiddenInput
if (authOverlay) {
    authOverlay.addEventListener('click', (e) => {
        if (isLockedOut) return;
        if (verdictTile && verdictTile.classList.contains('verdict-error')) {
            if (autoResetTimer) {
                clearTimeout(autoResetTimer);
                autoResetTimer = null;
            }
            resetPINBoard(true);
        } else if (!isVerifying && pinHiddenInput) {
            pinHiddenInput.focus();
        }
    });
}

// Step 3: Button trigger
if (pinVerifyBtn) {
    pinVerifyBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!isLockedOut && !isVerifying && enteredPin.length === TOTAL_SLOTS) {
            triggerVerification();
        }
    });
}

// Step 8: Reset on clicking verdict icon
if (verdictTile) {
    verdictTile.addEventListener('click', (e) => {
        e.stopPropagation();
        if (isLockedOut) {
            clearLockoutState();
            resetPINBoard(true);
            if (pinStatusText) {
                pinStatusText.innerHTML = '<span style="color: var(--accent-cyan); font-weight: 500; letter-spacing: 1.5px;">LOCKOUT RESET // ENTER 6-DIGIT PIN</span>';
            }
        } else {
            resetPINBoard(true);
        }
    });
}

// Check initial lockout state and auto-focus
if (!checkLockoutState()) {
    if (failedAttempts > 0 && failedAttempts < MAX_ATTEMPTS) {
        const remaining = MAX_ATTEMPTS - failedAttempts;
        if (pinStatusText) {
            pinStatusText.innerHTML = `<span style="color: var(--accent-amber); font-size: 0.76rem; letter-spacing: 1.5px; font-weight: 500;">ATTEMPT ${failedAttempts + 1} OF ${MAX_ATTEMPTS} // ${remaining} ${remaining === 1 ? 'RETRY' : 'RETRIES'} REMAINING</span>`;
        }
    }
    setTimeout(() => {
        if (pinHiddenInput && authOverlay && authOverlay.style.display !== 'none') {
            pinHiddenInput.focus();
        }
    }, 300);
}

// ==========================================================================
// FIRST COMMAND LISTENER (PRE-AUTHENTICATION VOICE CAPTURE)
// ==========================================================================
function startFirstCommandListener() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        console.warn("[Victor Speech] Web Speech API not supported in this browser.");
        return;
    }
    if (firstCommandRecognizer) {
        try { firstCommandRecognizer.stop(); } catch (_) {}
    }

    try {
        firstCommandRecognizer = new SpeechRecognition();
        firstCommandRecognizer.continuous = true;
        firstCommandRecognizer.interimResults = false;
        firstCommandRecognizer.lang = 'en-US';

        firstCommandRecognizer.onresult = (event) => {
            if (currentState !== "BIOMETRIC_PENDING") return;
            const lastIndex = event.results.length - 1;
            const transcript = event.results[lastIndex][0].transcript.trim();
            if (transcript.length > 0) {
                console.log("[Victor First Command Detected]:", transcript);
                stopFirstCommandListener();
                appendTranscriptEntry("user", transcript);
                ws.send(JSON.stringify({
                    type: "user_command",
                    text: transcript
                }));
            }
        };

        firstCommandRecognizer.onerror = (err) => {
            console.warn("[Victor First Command Recognizer Error]:", err);
        };

        firstCommandRecognizer.onend = () => {
            if (currentState === "BIOMETRIC_PENDING" && firstCommandRecognizer) {
                try { firstCommandRecognizer.start(); } catch (_) {}
            }
        };

        firstCommandRecognizer.start();
        console.log("[Victor First Command Listener] Waiting for first spoken command from Anubhav Sir...");
    } catch (err) {
        console.error("Failed to start first command recognizer:", err);
    }
}

function stopFirstCommandListener() {
    if (firstCommandRecognizer) {
        const rec = firstCommandRecognizer;
        firstCommandRecognizer = null;
        try { rec.abort(); } catch (_) {}
    }
}

// ==========================================================================
// STATE & WEBSOCKET MANAGEMENT
// ==========================================================================
function handleWebSocketMessage(event) {
    try {
        const message = JSON.parse(event.data);

        if (message.type === "session_state") {
            currentState = message.state;
            console.log(`[Victor Session State] ${currentState}`);
            updateUIState(currentState);

            if (currentState !== "BIOMETRIC_PENDING") {
                stopFirstCommandListener();
            }

            if (currentState === "LOCKED" || currentState === "CLOSED" || currentState === "OFFLINE") {
                stopFirstCommandListener();
                try { window.speechSynthesis.cancel(); } catch (_) {}
                isVictorSpeaking = false;
                currentUtterance = null;
                micMutedUntil = 0;
                if (authOverlay) {
                    authOverlay.style.display = "flex";
                    authOverlay.style.opacity = "1";
                }
                resetPINBoard();
                stopAudioPipeline();
            } else if (currentState === "BIOMETRIC_PENDING") {
                if (authOverlay) {
                    authOverlay.style.opacity = "0";
                    setTimeout(() => {
                        authOverlay.style.display = "none";
                    }, 400);
                }
                startAudioPipeline().catch(err => console.warn("Audio pipeline init:", err));
                startFirstCommandListener();
            } else if (currentState === "ACTIVE") {
                stopFirstCommandListener();
                try { window.speechSynthesis.cancel(); } catch (_) {}
                isVictorSpeaking = false;
                currentUtterance = null;
                micMutedUntil = Math.max(micMutedUntil || 0, Date.now() + 600); // Prevent speaker echo bleed
                if (authOverlay) {
                    authOverlay.style.display = "none";
                }
                startAudioPipeline().catch(err => console.warn("Audio pipeline init:", err));
                if (audioCtx && audioCtx.state === 'suspended') {
                    audioCtx.resume();
                }
            }

        } else if (message.type === "turn_state") {
            if (message.state === "WAITING_FOR_CONTINUATION") {
                if (orbStateText && !isMicMuted) orbStateText.textContent = message.label || "Live & Listening";
                if (window.VictorOrbInstance) window.VictorOrbInstance.setState("listening");
            } else if (message.state === "FINALIZING") {
                if (orbStateText) orbStateText.textContent = message.label || "Finalizing...";
                if (window.VictorOrbInstance) window.VictorOrbInstance.setState("thinking");
            } else if (message.orb_state) {
                updateUIState(message.orb_state);
            }

        } else if (message.type === "orb_state") {
            if (message.state === "ERROR") {
                currentState = "ERROR";
            }
            updateUIState(message.state);

        } else if (message.type === "cooldown_timer") {
            const remaining = Number(message.remaining || 0);
            if (remaining > 0) {
                if (globalStatusText) globalStatusText.textContent = `COOLDOWN (${remaining}s)`;
                if (orbStateText) orbStateText.textContent = `RETRY IN ${remaining}s`;
            } else {
                if (globalStatusText && globalStatusText.textContent.includes("COOLDOWN")) {
                    globalStatusText.textContent = currentState || "ACTIVE";
                }
                if (orbStateText && orbStateText.textContent.includes("RETRY")) {
                    orbStateText.textContent = currentState || "LISTENING";
                }
            }

        } else if (message.type === "transcript") {

            appendTranscriptEntry(message.role, message.text);

        } else if (message.type === "speak") {
            if (isSpeaking || activeAudioSources.length > 0) {
                console.log("[Victor Audio] Suppressed speak TTS because Gemini Live audio is active.");
                return;
            }
            if ('speechSynthesis' in window && message.text) {
                try { window.speechSynthesis.cancel(); } catch (_) {}
                isVictorSpeaking = true;
                currentUtterance = new SpeechSynthesisUtterance(message.text);
                currentUtterance.rate = 1.0;
                currentUtterance.pitch = 1.0;
                currentUtterance.onstart = () => {
                    isVictorSpeaking = true;
                };
                currentUtterance.onend = () => {
                    isVictorSpeaking = false;
                    currentUtterance = null;
                };
                currentUtterance.onerror = () => {
                    isVictorSpeaking = false;
                    currentUtterance = null;
                };
                window.speechSynthesis.speak(currentUtterance);
            }

        } else if (message.type === "greeting_complete") {
            console.log("[Victor Audio] Greeting complete, mic unmuting cleanly for Gemini Live.");
            try { window.speechSynthesis.cancel(); } catch (_) {}
            isVictorSpeaking = false;
            currentUtterance = null;
            micMutedUntil = Date.now() + 600; // Small grace period for speaker reverb decay
            if (audioCtx && audioCtx.state === 'suspended') {
                audioCtx.resume();
            }

        } else if (message.type === "tool_execution") {
            const toolName = message.tool || "tool";
            const status = (message.status || "").toLowerCase();
            if (status === "failed") {
                const errMsg = message.error ? `: ${message.error}` : "";
                appendTranscriptEntry("tool", `⚠️ Tool '${toolName}' failed${errMsg}`);
            } else if (status === "completed") {
                appendTranscriptEntry("tool", `✅ Tool '${toolName}' completed.`);
            } else {
                appendTranscriptEntry("tool", `🔧 Executing tool: ${toolName}...`);
            }

        } else if (message.type === "audio_interrupted") {
            console.log("[Victor Audio] User speech interruption detected.");
            stopAllAudioPlayback();

        } else if (message.type === "auth_result") {
            if (!message.success) {
                if (pinStatusText) {
                    pinStatusText.innerHTML = `<span style="color: var(--accent-rose);">${message.message || "Authentication failed."}</span>`;
                }
                if (authOverlay) {
                    authOverlay.style.display = "flex";
                    authOverlay.style.opacity = "1";
                }
                resetPINBoard();
                stopAudioPipeline();
            }

        } else if (message.type === "audio_output") {
            playAudioChunk(message.data);

        } else if (message.type === "phone_status") {
            updatePhoneStatus(message);

        } else if (message.type === "phone_pairing_data") {
            updatePairingModalData(message);

        } else if (message.type === "phone_incoming_call") {
            if (message.status === "RINGING") {
                showIncomingCallBanner(message.caller_name, message.caller_number, message.call_type);
            } else {
                hideIncomingCallBanner();
            }

        } else if (message.type === "phone_alert") {
            console.log(`[Victor Phone Alert] ${message.source}: ${message.text}`);
        } else if (message.type === "reminder_notification") {
            console.log(`[Victor Reminder] ${message.message}`);
        } else if (message.type === "camera_state") {
            console.log(`[Victor Camera] Hardware State: ${message.state}`);
            if (message.state === "OPEN") {
                appendTranscriptEntry("system", "📷 Camera initialized and active.");
            } else if (message.state === "ANALYZING") {
                appendTranscriptEntry("system", "🔍 Live visual analysis active.");
            } else if (message.state === "RECORDING") {
                appendTranscriptEntry("system", "🎥 Camera video recording in progress...");
            } else if (message.state === "CLOSED") {
                appendTranscriptEntry("system", "📷 Camera closed and hardware released.");
            }
        } else if (message.type === "camera_analysis_update") {
            if (message.text) {
                appendTranscriptEntry("assistant", `👁️ Visual Analysis: ${message.text}`);
            }
        } else if (message.type === "dashboard_navigate") {
            const dest = message.destination || message.section;
            const tab = message.tab;
            const action = message.action || (message.filters && message.filters.action);

            if (dest === "__BACK__" || action === "back") {
                navigateHistoryBack();
            } else if (dest === "finance") {
                openModuleView("finance");
                if (window.FinanceDashboard) {
                    if (tab) window.FinanceDashboard.switchTab(tab);
                    if (message.filters) window.FinanceDashboard.handleNavigation(tab, message.filters);
                }
            } else if (dest === "documents") {
                openModuleView("documents");
                if (window.DocumentDashboard) {
                    const targetTab = tab === "study" ? "notes" : (tab || "library");
                    window.DocumentDashboard.switchTab(targetTab);
                    if (message.payload || message.summary) {
                        window.DocumentDashboard.handleNavigation(targetTab, message.payload || message);
                    }
                }
            } else if (dest === "dashboard" || dest === "home") {
                openModuleView("dashboard");
            } else if (dest && (MODULE_DEFINITIONS[dest] || dest === "settings")) {
                openModuleView(dest);
            }
        } else if (message.type === "finance_update") {
            if (window.FinanceDashboard) {
                window.FinanceDashboard.handleUpdate(message);
            }
        } else if (message.type === "document_update" || message.type === "rag_update") {
            if (window.DocumentDashboard) {
                window.DocumentDashboard.handleUpdate(message);
            }
        } else if (message.type === "phone_alert") {
            addHudNotification(`Phone (${message.source || 'Alert'})`, message.title ? `${message.title}: ${message.text || ''}` : (message.text || 'New notification'));
        } else if (message.type === "reminder_notification") {
            addHudNotification('Reminder', message.message || 'Scheduled reminder triggered');
        }
    } catch (e) {
        console.error("Error parsing WebSocket message:", e);
    }
}

function setupWebSocket() {
    if (ws) {
        try {
            ws.onclose = null;
            ws.onerror = null;
            ws.onmessage = null;
            ws.close();
        } catch (_) {}
    }

    try {
        ws = new WebSocket(`ws://${window.location.host}/ws`);
        ws.onmessage = handleWebSocketMessage;
        ws.onopen = () => {
            console.log("[Victor WS] Connected to backend.");
            if (wsReconnectTimer) {
                clearTimeout(wsReconnectTimer);
                wsReconnectTimer = null;
            }
        };
        ws.onclose = (event) => {
            console.warn("[Victor WS] Connection closed. Auto-reconnecting in 2s...", event);
            if (!wsReconnectTimer) {
                wsReconnectTimer = setTimeout(() => {
                    wsReconnectTimer = null;
                    setupWebSocket();
                }, 2000);
            }
        };
        ws.onerror = (err) => {
            console.error("[Victor WS] WebSocket error:", err);
        };
    } catch (wsErr) {
        console.error("[Victor WS] Failed to create WebSocket:", wsErr);
    }
}

// Initialize persistent WebSocket
setupWebSocket();

// Periodic Client Audio & Session Health Watchdog (every 4s)
setInterval(() => {
    if (audioCtx) {
        // Auto-resume AudioContext if suspended while Victor is in active listening states
        if (audioCtx.state === 'suspended' && (currentState === "ACTIVE" || currentState === "LISTENING")) {
            console.log("[Victor Health Watchdog] Auto-resuming suspended AudioContext.");
            audioCtx.resume().catch(() => {});
        }
        // Auto-clear stuck isVictorSpeaking lock if all audio sources finished
        if (isVictorSpeaking && activeAudioSources.length === 0) {
            console.warn("[Victor Health Watchdog] Auto-clearing orphaned isVictorSpeaking lock.");
            isVictorSpeaking = false;
            isSpeaking = false;
        }
    }
}, 4000);

// Lock Terminal button
if (lockBtn) {
    lockBtn.addEventListener('click', () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "lock_request" }));
        }
    });
}

// ==========================================================================
// COMMAND TEXT INPUT HANDLING
// ==========================================================================
const commandForm = document.getElementById("commandForm");
const commandTextInput = document.getElementById("commandTextInput");

if (commandForm && commandTextInput) {
    commandForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = commandTextInput.value.trim();
        if (!text) return;

        // Check if session is locked
        if (currentState === "LOCKED" || currentState === "CLOSED" || currentState === "OFFLINE") {
            if (pinStatusText) {
                pinStatusText.innerHTML = `<span style="color: var(--accent-amber);">Please unlock Victor with your PIN first.</span>`;
            }
            if (authOverlay) {
                authOverlay.style.display = "flex";
                authOverlay.style.opacity = "1";
            }
            return;
        }

        // If in BIOMETRIC_PENDING, stop speech listener to avoid conflicting triggers
        if (currentState === "BIOMETRIC_PENDING") {
            stopFirstCommandListener();
        }

        // Display user command in transcript
        appendTranscriptEntry("user", text);

        // Send command to backend over unified WebSocket channel
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: "user_command",
                text: text,
            }));
        }

        // Clear input
        commandTextInput.value = "";
    });
}

// ==========================================================================
// PHONE COMPANION CONTROLLER
// ==========================================================================
const phoneStatusBtn = document.getElementById("phoneStatusBtn");
const phoneStatusDot = document.getElementById("phoneStatusDot");
const phoneStatusLabel = document.getElementById("phoneStatusLabel");

const incomingCallBanner = document.getElementById("incomingCallBanner");
const callTypeBadge = document.getElementById("callTypeBadge");
const callerNameDisplay = document.getElementById("callerNameDisplay");
const callerNumberDisplay = document.getElementById("callerNumberDisplay");
const btnAnswerCall = document.getElementById("btnAnswerCall");
const btnRejectCall = document.getElementById("btnRejectCall");

const phonePairingModal = document.getElementById("phonePairingModal");
const btnClosePhoneModal = document.getElementById("btnClosePhoneModal");
const modalPhoneStatus = document.getElementById("modalPhoneStatus");
const modalPhoneDevice = document.getElementById("modalPhoneDevice");
const modalPhoneBattery = document.getElementById("modalPhoneBattery");
const pairingServerAddress = document.getElementById("pairingServerAddress");
const pairingPinDisplay = document.getElementById("pairingPinDisplay");
const btnGeneratePairingCode = document.getElementById("btnGeneratePairingCode");
const btnUnpairPhone = document.getElementById("btnUnpairPhone");

function updatePhoneStatus(data) {
    const status = data.status || "UNPAIRED";
    const deviceName = data.device_name || "Android Phone";

    if (phoneStatusDot) {
        phoneStatusDot.classList.remove("is-online", "is-offline");
        if (status === "ONLINE") {
            phoneStatusDot.classList.add("is-online");
        } else if (status === "OFFLINE") {
            phoneStatusDot.classList.add("is-offline");
        }
    }

    if (phoneStatusLabel) {
        if (status === "ONLINE") {
            phoneStatusLabel.textContent = `PHONE: ${deviceName.toUpperCase()}`;
        } else if (status === "OFFLINE") {
            phoneStatusLabel.textContent = `PHONE: OFFLINE`;
        } else {
            phoneStatusLabel.textContent = `PHONE: NOT PAIRED`;
        }
    }

    if (modalPhoneStatus) modalPhoneStatus.textContent = status;
    if (modalPhoneDevice) modalPhoneDevice.textContent = data.paired ? deviceName : "None";
    if (modalPhoneBattery) {
        if (data.battery_level !== null && data.battery_level !== undefined) {
            modalPhoneBattery.textContent = `${data.battery_level}%${data.is_charging ? " (Charging)" : ""}`;
        } else {
            modalPhoneBattery.textContent = "--";
        }
    }
}

function updatePairingModalData(data) {
    if (pairingServerAddress) {
        pairingServerAddress.textContent = `ws://${data.ip}:${data.port}/ws/phone`;
    }
    if (pairingPinDisplay) {
        pairingPinDisplay.textContent = data.pin || "------";
    }
}

function showIncomingCallBanner(callerName, callerNumber, callType) {
    if (!incomingCallBanner) return;
    if (callerNameDisplay) callerNameDisplay.textContent = callerName || "Unknown Caller";
    if (callerNumberDisplay) callerNumberDisplay.textContent = callerNumber || "";
    if (callTypeBadge) {
        callTypeBadge.textContent = callType === "whatsapp" ? "INCOMING WHATSAPP CALL" : "INCOMING PHONE CALL";
    }
    incomingCallBanner.classList.remove("hidden");
}

function hideIncomingCallBanner() {
    if (incomingCallBanner) {
        incomingCallBanner.classList.add("hidden");
    }
}

if (phoneStatusBtn) {
    phoneStatusBtn.addEventListener("click", () => {
        if (phonePairingModal) {
            phonePairingModal.classList.remove("hidden");
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "phone_pair_init" }));
            }
        }
    });
}

if (btnClosePhoneModal) {
    btnClosePhoneModal.addEventListener("click", () => {
        if (phonePairingModal) phonePairingModal.classList.add("hidden");
    });
}

if (phonePairingModal) {
    phonePairingModal.addEventListener("click", (e) => {
        if (e.target === phonePairingModal) phonePairingModal.classList.add("hidden");
    });
}

if (btnGeneratePairingCode) {
    btnGeneratePairingCode.addEventListener("click", () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "phone_pair_init" }));
        }
    });
}

if (btnUnpairPhone) {
    btnUnpairPhone.addEventListener("click", () => {
        if (confirm("Revoke companion phone pairing? The phone will no longer be able to connect.")) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "phone_unpair" }));
            }
        }
    });
}

if (btnAnswerCall) {
    btnAnswerCall.addEventListener("click", () => {
        hideIncomingCallBanner();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "phone_answer_call" }));
        }
    });
}

if (btnRejectCall) {
    btnRejectCall.addEventListener("click", () => {
        hideIncomingCallBanner();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "phone_reject_call" }));
        }
    });
}


// ==========================================================================
// NEURAL AGENTIC HUD CONTROLLER (HEALTH, SIDEBAR, MODULES, QUICK ACTIONS)
// ==========================================================================

function sendVictorCommand(text, prefillOnly = false) {
    const inputEl = document.getElementById('commandTextInput');
    if (prefillOnly && inputEl) {
        inputEl.value = text;
        inputEl.focus();
        return;
    }
    if (!text || !text.trim()) return;
    if (ws && ws.readyState === WebSocket.OPEN) {
        appendTranscriptEntry("user", text.trim());
        ws.send(JSON.stringify({ type: "user_command", text: text.trim() }));
    }
}

// 1. Live System Health Polling (/api/system-health)
async function refreshSystemHealth() {
    try {
        const res = await fetch('/api/system-health', { cache: 'no-store' });
        if (!res.ok) return;
        const data = await res.json();

        const cpuBar = document.getElementById('cpuBar');
        const cpuVal = document.getElementById('cpuVal');
        const ramBar = document.getElementById('ramBar');
        const ramVal = document.getElementById('ramVal');
        const gpuBar = document.getElementById('gpuBar');
        const gpuVal = document.getElementById('gpuVal');
        const vramBar = document.getElementById('vramBar');
        const vramVal = document.getElementById('vramVal');
        const diskBar = document.getElementById('diskBar');
        const diskVal = document.getElementById('diskVal');
        const netBadge = document.getElementById('netStatusBadge');
        const modelEl = document.getElementById('activeModelName');
        const gpuDeviceLabel = document.getElementById('gpuDeviceLabel');
        const gpuTempFooter = document.getElementById('gpuTempFooter');
        const gpuStatusBadge = document.getElementById('gpuStatusBadge');
        const vadStatusLabel = document.getElementById('vadStatusLabel');
        const sttStatusLabel = document.getElementById('sttStatusLabel');

        const cpuPct = Math.round(Number(data.cpu_pct || 0));
        const ramPct = Math.round(Number(data.ram_pct || 0));
        const diskPct = Math.round(Number(data.disk_pct || 0));

        if (cpuBar) cpuBar.style.width = `${cpuPct}%`;
        if (cpuVal) cpuVal.textContent = `${cpuPct}%`;
        if (ramBar) ramBar.style.width = `${ramPct}%`;
        if (ramVal) ramVal.textContent = `${ramPct}%`;
        if (diskBar) diskBar.style.width = `${diskPct}%`;
        if (diskVal) diskVal.textContent = `${diskPct}%`;

        // GPU & VRAM Live Telemetry
        if (data.gpu_available) {
            const gpuPct = Math.round(Number(data.gpu_pct || 0));
            const vramPct = Math.round(Number(data.gpu_vram_pct || 0));
            const vramUsed = Math.round(Number(data.gpu_vram_used_mb || 0));
            const vramTotal = Math.round(Number(data.gpu_vram_total_mb || 2048));

            if (gpuBar) gpuBar.style.width = `${Math.min(100, gpuPct)}%`;
            if (gpuVal) gpuVal.textContent = `${gpuPct}%`;
            if (vramBar) vramBar.style.width = `${Math.min(100, vramPct)}%`;
            if (vramVal) vramVal.textContent = `${vramUsed} / ${vramTotal} MB`;

            if (gpuDeviceLabel) {
                const shortName = (data.gpu_name || 'CUDA').replace('NVIDIA ', '').replace('GeForce ', '');
                gpuDeviceLabel.textContent = `${shortName} ACTIVE`;
            }
            if (gpuTempFooter) {
                const tempStr = data.gpu_temp_c ? ` • ${Math.round(data.gpu_temp_c)}°C` : '';
                gpuTempFooter.textContent = `GPU: ${gpuPct}%${tempStr}`;
            }
            if (gpuStatusBadge) {
                gpuStatusBadge.textContent = 'CUDA READY';
                gpuStatusBadge.style.borderColor = 'rgba(0, 217, 255, 0.4)';
            }
            if (vadStatusLabel) vadStatusLabel.textContent = data.vad_device ? `(${data.vad_device})` : '(Neural CUDA)';
            if (sttStatusLabel) sttStatusLabel.textContent = data.stt_device ? `(${data.stt_device})` : '(GPU Fallback)';
        } else {
            if (gpuBar) gpuBar.style.width = '0%';
            if (gpuVal) gpuVal.textContent = 'OFF';
            if (vramBar) vramBar.style.width = '0%';
            if (vramVal) vramVal.textContent = 'CPU Mode';
            if (gpuDeviceLabel) gpuDeviceLabel.textContent = 'CPU MODE';
            if (gpuTempFooter) gpuTempFooter.textContent = 'GPU: Offline';
            if (gpuStatusBadge) gpuStatusBadge.textContent = 'CPU ONLY';
            if (vadStatusLabel) vadStatusLabel.textContent = '(CPU VAD)';
            if (sttStatusLabel) sttStatusLabel.textContent = '(CPU Fallback)';
        }
        if (netBadge) {
            netBadge.textContent = data.network_online ? 'ONLINE' : 'LOCAL';
            netBadge.style.color = data.network_online ? 'var(--accent-emerald)' : 'var(--accent-amber)';
        }
        if (modelEl && data.model) {
            modelEl.textContent = data.model;
        }
    } catch (_) {
        // Silent fallback when server restarts
    }
}
refreshSystemHealth();
setInterval(refreshSystemHealth, 10000);

// 2. Microphone Mute / Interaction Control
function toggleMicrophoneMute() {
    isMicMuted = !isMicMuted;
    const micBtn = document.getElementById('micControlBtn');
    const topMicBtn = document.getElementById('topbarMicBtn');
    const sttPill = document.getElementById('sttPipelinePill');
    const sttLabel = document.getElementById('sttStatusLabel');

    if (micBtn) micBtn.classList.toggle('is-muted', isMicMuted);
    if (topMicBtn) topMicBtn.classList.toggle('is-muted', isMicMuted);
    if (sttPill) sttPill.classList.toggle('is-muted', isMicMuted);
    if (sttLabel) sttLabel.textContent = isMicMuted ? '(Mic Muted)' : '(STT Active)';

    if (!isMicMuted && (!audioCtx || audioCtx.state === 'suspended')) {
        startAudioPipeline().catch(() => {});
    }
    updateUIState(currentState);
}

const micControlBtn = document.getElementById('micControlBtn');
const topbarMicBtn = document.getElementById('topbarMicBtn');
if (micControlBtn) micControlBtn.addEventListener('click', toggleMicrophoneMute);
if (topbarMicBtn) topbarMicBtn.addEventListener('click', toggleMicrophoneMute);

// 3. Sidebar Collapse & Module Drawer Navigation
const hudSidebar = document.getElementById('hudSidebar');
const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
if (sidebarToggleBtn && hudSidebar) {
    sidebarToggleBtn.addEventListener('click', () => {
        hudSidebar.classList.toggle('is-collapsed');
    });
}

const MODULE_DEFINITIONS = {
    computer: {
        title: 'Computer Control',
        actions: [
            { title: 'Take Screenshot', desc: 'Capture current desktop screen', cmd: 'Take a screenshot', prefill: false },
            { title: 'Adjust Volume', desc: 'Set system master audio level', cmd: 'Set volume to ', prefill: true },
            { title: 'Adjust Brightness', desc: 'Change display brightness level', cmd: 'Set brightness to ', prefill: true },
            { title: 'Open Windows Settings', desc: 'Launch system settings panel', cmd: 'Open Windows settings', prefill: false },
        ]
    },
    browser: {
        title: 'Web & Browser Automation',
        actions: [
            { title: 'Open Website', desc: 'Navigate Playwright browser to URL', cmd: 'Open website ', prefill: true },
            { title: 'Open YouTube', desc: 'Launch YouTube in browser', cmd: 'Open YouTube', prefill: false },
            { title: 'Open ChatGPT / Claude / Gemini', desc: 'Launch AI web assistants', cmd: 'Open Gemini in browser', prefill: false },
            { title: 'Current Affairs & News', desc: 'Get latest real-time news updates', cmd: 'Give me latest tech news', prefill: false },
        ]
    },
    applications: {
        title: 'Applications & Google Services',
        actions: [
            { title: 'Open Application', desc: 'Launch any installed desktop app', cmd: 'Open ', prefill: true },
            { title: 'Google Keep Notes', desc: 'Create or search Keep notes', cmd: 'Create a Google Keep note ', prefill: true },
            { title: 'Google Calendar', desc: 'Schedule or inspect calendar events', cmd: 'Open Google Calendar', prefill: false },
            { title: 'Google Meet', desc: 'Create or join a Meet call', cmd: 'Create an instant Google Meet', prefill: false },
        ]
    },
    system: {
        title: 'System Monitor & Telemetry',
        actions: [
            { title: 'Full Performance Check', desc: 'Query CPU, RAM, and battery health', cmd: 'Check my system performance and battery', prefill: false },
            { title: 'Network & Wi-Fi Status', desc: 'Inspect active SSID and internet', cmd: 'Check Wi-Fi and network status', prefill: false },
            { title: 'Bluetooth Status', desc: 'Check Bluetooth hardware status', cmd: 'Check Bluetooth status', prefill: false },
            { title: 'Check Phone Status', desc: 'Inspect paired Android companion', cmd: 'Check my phone status and battery', prefill: false },
        ]
    },
    memory: {
        title: 'Memory & Context',
        actions: [
            { title: 'Recall Memory', desc: 'Search long-term remembered facts', cmd: 'What do you remember about ', prefill: true },
            { title: 'Remember Preference', desc: 'Store a personal preference', cmd: 'Remember that ', prefill: true },
            { title: 'List Reminders', desc: 'View upcoming tasks & deadlines', cmd: 'List my upcoming reminders', prefill: false },
            { title: 'Create Reminder', desc: 'Schedule a dated task or birthday', cmd: 'Remind me to ', prefill: true },
        ]
    },
    screen: {
        title: 'Screen & Visual Intelligence',
        actions: [
            { title: 'Analyze Screen', desc: 'Understand what is currently visible', cmd: 'Analyze what is on my screen right now', prefill: false },
            { title: 'Open Camera', desc: 'Activate live camera feed', cmd: 'Open camera', prefill: false },
            { title: 'Scan QR / Barcode', desc: 'Decode QR from screen or camera', cmd: 'Scan QR code on screen', prefill: false },
            { title: 'Visual Copy Text', desc: 'Extract text from screen to clipboard', cmd: 'Copy text from my screen', prefill: false },
        ]
    },
    automations: {
        title: 'Automations & Phone Companion',
        actions: [
            { title: 'Read Phone Notifications', desc: 'Summarize WhatsApp & SMS alerts', cmd: 'Read my recent phone notifications', prefill: false },
            { title: 'Call Phone Contact', desc: 'Dial contact via Android companion', cmd: 'Call ', prefill: true },
            { title: 'Check Unread Emails', desc: 'Fetch unread inbox summary', cmd: 'Check my unread emails', prefill: false },
            { title: 'Play Music', desc: 'Stream music via playback engine', cmd: 'Play music ', prefill: true },
        ]
    },
    agents: {
        title: 'Agents (Multi-Agent Workflows)',
        actions: [
            { title: 'Start New Project Plan', desc: 'Launch multi-agent research & spec', cmd: 'Start a multi-agent project to build ', prefill: true },
            { title: 'Check Pipeline Status', desc: 'Inspect active multi-agent workflow', cmd: 'Check multi-agent project status', prefill: false },
            { title: 'Download Project Artifact', desc: 'Save generated README/spec to Downloads', cmd: 'Download multi-agent artifact', prefill: false },
        ]
    },
    tools: {
        title: 'Registered Capabilities (104 Tools)',
        actions: [
            { title: 'Weather & Forecast', desc: 'Live weather via public API', cmd: 'What is the weather today?', prefill: false },
            { title: 'Stock Market Quote', desc: 'Real-time stock ticker lookup', cmd: 'Tell me about NVIDIA stock', prefill: false },
            { title: 'Search Local Files', desc: 'Find files across your workspace', cmd: 'Search files for ', prefill: true },
            { title: 'Coding & Shell Agent', desc: 'Write or run code safely', cmd: 'Write a Python script to ', prefill: true },
        ]
    },
    labs: {
        title: 'Victor Labs (Experimental)',
        actions: [
            { title: 'Live Camera Analysis', desc: 'Continuous visual scene monitoring', cmd: 'Start live camera analysis', prefill: false },
            { title: 'YouTube on Phone', desc: 'Cast video search to Android phone', cmd: 'Open YouTube on my phone for ', prefill: true },
            { title: 'Pair Android Phone', desc: 'Open Phone Companion pairing modal', cmd: '__OPEN_PHONE_MODAL__', prefill: false },
        ]
    },
    settings: {
        title: 'Settings & Security',
        actions: [
            { title: 'Phone Companion Pairing', desc: 'Manage paired Android device & PIN', cmd: '__OPEN_PHONE_MODAL__', prefill: false },
            { title: 'Lock Terminal', desc: 'Lock Victor session immediately', cmd: '__LOCK_TERMINAL__', prefill: false },
            { title: 'Toggle Microphone', desc: 'Mute or unmute live voice input', cmd: '__TOGGLE_MIC__', prefill: false },
            { title: 'Windows Settings', desc: 'Open OS Display/Sound/Network settings', cmd: 'Open Windows settings', prefill: false },
        ]
    },
    finance: {
        title: 'Personal Finance & Bills',
        actions: [
            { title: 'Show Monthly Expenses', desc: 'Display spending overview & breakdown', cmd: 'Victor, show my monthly expenses', prefill: false },
            { title: 'Upcoming Bills', desc: 'Inspect pending due dates and bills', cmd: 'List my upcoming bills', prefill: false },
            { title: 'Budget Status', desc: 'Check budget utilization & alerts', cmd: 'Check my monthly budget status', prefill: false },
            { title: 'Active Subscriptions', desc: 'Review recurring subscriptions and costs', cmd: 'List my active subscriptions', prefill: false },
        ]
    }
};

const moduleDrawer = document.getElementById('moduleDrawer');
const moduleDrawerTitle = document.getElementById('moduleDrawerTitle');
const moduleCardsGrid = document.getElementById('moduleCardsGrid');
const moduleCloseBtn = document.getElementById('moduleCloseBtn');

let currentDashboardView = 'dashboard';
const dashboardNavHistory = [];

function navigateHistoryBack() {
    const prev = dashboardNavHistory.pop() || 'dashboard';
    openModuleView(prev, true);
}

function openModuleView(viewKey, isBackAction = false) {
    if (!isBackAction && currentDashboardView !== viewKey) {
        dashboardNavHistory.push(currentDashboardView);
        if (dashboardNavHistory.length > 30) dashboardNavHistory.shift();
    }
    currentDashboardView = viewKey;

    document.querySelectorAll('.sidebar-item, .topnav-item').forEach(btn => {
        btn.classList.toggle('is-active', btn.dataset.view === viewKey);
    });

    const grid = document.querySelector('.hud-command-grid');
    const quickActions = document.querySelector('.quick-actions-bar');
    const headerStrip = document.querySelector('.workspace-header-strip');

    if (viewKey === 'finance') {
        if (moduleDrawer) moduleDrawer.classList.add('hidden');
        if (grid) grid.classList.add('hidden');
        if (quickActions) quickActions.classList.add('hidden');
        if (headerStrip) headerStrip.classList.add('hidden');
        if (window.DocumentDashboard) window.DocumentDashboard.hide(false);
        if (window.FinanceDashboard) {
            window.FinanceDashboard.show();
        }
        return;
    } else if (viewKey === 'documents') {
        if (moduleDrawer) moduleDrawer.classList.add('hidden');
        if (grid) grid.classList.add('hidden');
        if (quickActions) quickActions.classList.add('hidden');
        if (headerStrip) headerStrip.classList.add('hidden');
        if (window.FinanceDashboard) window.FinanceDashboard.hide(false);
        if (window.DocumentDashboard) {
            window.DocumentDashboard.show();
        }
        return;
    } else {
        if (window.FinanceDashboard) {
            window.FinanceDashboard.hide(false);
        }
        if (window.DocumentDashboard) {
            window.DocumentDashboard.hide(false);
        }
        if (grid) grid.classList.remove('hidden');
        if (quickActions) quickActions.classList.remove('hidden');
        if (headerStrip) headerStrip.classList.remove('hidden');
    }

    if (viewKey === 'dashboard' || !MODULE_DEFINITIONS[viewKey]) {
        if (moduleDrawer) moduleDrawer.classList.add('hidden');
        return;
    }

    const def = MODULE_DEFINITIONS[viewKey];
    if (moduleDrawerTitle) moduleDrawerTitle.textContent = def.title;
    if (moduleCardsGrid) {
        moduleCardsGrid.innerHTML = '';
        def.actions.forEach(item => {
            const tile = document.createElement('button');
            tile.type = 'button';
            tile.className = 'module-action-tile';
            tile.innerHTML = `<div class="module-action-tile-title">${item.title}</div><div class="module-action-tile-desc">${item.desc}</div>`;
            tile.addEventListener('click', () => {
                if (item.cmd === '__OPEN_PHONE_MODAL__') {
                    if (phoneStatusBtn) phoneStatusBtn.click();
                } else if (item.cmd === '__LOCK_TERMINAL__') {
                    if (lockBtn) lockBtn.click();
                } else if (item.cmd === '__TOGGLE_MIC__') {
                    toggleMicrophoneMute();
                } else {
                    if (moduleDrawer) moduleDrawer.classList.add('hidden');
                    document.querySelectorAll('.sidebar-item, .topnav-item').forEach(b => b.classList.toggle('is-active', b.dataset.view === 'dashboard'));
                    sendVictorCommand(item.cmd, item.prefill);
                }
            });
            moduleCardsGrid.appendChild(tile);
        });
    }
    if (moduleDrawer) moduleDrawer.classList.remove('hidden');
}

document.querySelectorAll('.sidebar-item, .topnav-item').forEach(btn => {
    btn.addEventListener('click', () => openModuleView(btn.dataset.view));
});

if (moduleCloseBtn) {
    moduleCloseBtn.addEventListener('click', () => openModuleView('dashboard'));
}

const userProfileBtn = document.getElementById('userProfileBtn');
if (userProfileBtn) {
    userProfileBtn.addEventListener('click', () => openModuleView('settings'));
}

// Global Escape Key Listener for dismissible overlays and drawers
window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (phonePairingModal && !phonePairingModal.classList.contains('hidden')) {
            phonePairingModal.classList.add('hidden');
            return;
        }
        if (notificationsPopover && !notificationsPopover.classList.contains('hidden')) {
            notificationsPopover.classList.add('hidden');
            return;
        }
        const openFinModal = document.querySelector('.fin-modal-overlay:not(.hidden)');
        if (openFinModal) {
            openFinModal.classList.add('hidden');
            return;
        }
        const openDocModal = document.querySelector('.doc-modal-overlay:not(.hidden)');
        if (openDocModal) {
            openDocModal.classList.add('hidden');
            return;
        }
        if (moduleDrawer && !moduleDrawer.classList.contains('hidden')) {
            openModuleView('dashboard');
            return;
        }
    }
});

// 4. Bottom Quick Actions Integration
const QUICK_ACTION_MAP = {
    open_app:       { cmd: 'Open ', prefill: true },
    control_system: { cmd: 'Check my system performance and battery', prefill: false },
    browse_web:     { cmd: 'Open website ', prefill: true },
    analyze_screen: { cmd: 'Analyze what is on my screen right now', prefill: false },
    run_code:       { cmd: 'Run Python code: ', prefill: true },
    create_file:    { cmd: 'Create a file named ', prefill: true },
    automation:     { cmd: 'Read my recent phone notifications', prefill: false },
};

document.querySelectorAll('.quick-action-card').forEach(card => {
    card.addEventListener('click', () => {
        const spec = QUICK_ACTION_MAP[card.dataset.action];
        if (spec) sendVictorCommand(spec.cmd, spec.prefill);
    });
});

// 5. Notifications Popover
const notificationsBtn = document.getElementById('notificationsBtn');
const notificationsPopover = document.getElementById('notificationsPopover');
const notifPopoverList = document.getElementById('notifPopoverList');
const notifBadge = document.getElementById('notifBadge');
const clearNotifPopoverBtn = document.getElementById('clearNotifPopoverBtn');
let hudNotifications = [];

function addHudNotification(title, body) {
    hudNotifications.unshift({ title, body, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
    if (hudNotifications.length > 20) hudNotifications.pop();
    renderHudNotifications();
}

function renderHudNotifications() {
    if (notifBadge) {
        if (hudNotifications.length > 0) {
            notifBadge.textContent = String(hudNotifications.length);
            notifBadge.classList.remove('hidden');
        } else {
            notifBadge.classList.add('hidden');
        }
    }
    if (!notifPopoverList) return;
    if (hudNotifications.length === 0) {
        notifPopoverList.innerHTML = '<div class="notif-empty">No recent alerts.</div>';
        return;
    }
    notifPopoverList.innerHTML = '';
    hudNotifications.forEach(n => {
        const el = document.createElement('div');
        el.className = 'notif-item';
        const titleEl = document.createElement('div');
        titleEl.className = 'notif-item-title';
        titleEl.textContent = `${n.title} · ${n.time}`;
        const bodyEl = document.createElement('div');
        bodyEl.className = 'notif-item-body';
        bodyEl.textContent = n.body;
        el.appendChild(titleEl);
        el.appendChild(bodyEl);
        notifPopoverList.appendChild(el);
    });
}

if (notificationsBtn && notificationsPopover) {
    notificationsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        notificationsPopover.classList.toggle('hidden');
    });
    document.addEventListener('click', (e) => {
        if (!notificationsPopover.contains(e.target) && e.target !== notificationsBtn) {
            notificationsPopover.classList.add('hidden');
        }
    });
}
if (clearNotifPopoverBtn) {
    clearNotifPopoverBtn.addEventListener('click', () => {
        hudNotifications = [];
        renderHudNotifications();
    });
}


