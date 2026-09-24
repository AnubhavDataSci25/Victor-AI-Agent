/**
 * Victor 2.0 Client Application Controller
 * Handles WebSocket communication, Web Audio streaming, HUD telemetry,
 * real-time transcript streaming, and Particle Orb synchronization.
 */

const ws = new WebSocket(`ws://${window.location.host}/ws`);

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

// ==========================================================================
// REAL-TIME CHRONO TELEMETRY (CLOCK & DATE)
// ==========================================================================
function updateChronoTelemetry() {
    const now = new Date();
    
    // Time format: HH:MM:SS AM/PM
    if (hudClock) {
        hudClock.textContent = now.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });
    }

    // Date format: Day, Month Date, Year
    if (hudDate) {
        hudDate.textContent = now.toLocaleDateString('en-US', {
            weekday: 'long',
            month: 'long',
            day: 'numeric',
            year: 'numeric'
        });
    }
}
setInterval(updateChronoTelemetry, 1000);
updateChronoTelemetry();

// ==========================================================================
// AUDIO PIPELINE (16kHz PCM Input / 24kHz PCM Output)
// ==========================================================================
async function startAudioPipeline() {
    if (audioCtx) {
        if (audioCtx.state === 'suspended') {
            await audioCtx.resume();
        }
        return;
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

        // Capture Processor for streaming to backend
        scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
        scriptProcessor.onaudioprocess = (e) => {
            // Only stream during active conversation session
            if (currentState !== "ACTIVE" && currentState !== "LISTENING" && currentState !== "SPEAKING") return;

            // Acoustic echo suppression: drop mic packets while Victor's pre-auth SpeechSynthesis is speaking
            if (isVictorSpeaking) return;

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
            
            ws.send(JSON.stringify({
                type: "audio_input",
                data: btoa(binary)
            }));
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
        lastEntry.text += text;
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

    article.appendChild(header);
    article.appendChild(textP);

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
    if (globalStatusText) globalStatusText.textContent = s;
    if (orbStateText) orbStateText.textContent = s;
    
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

// Step 1: Input handling & typing numbers invisible with blinking cursor
if (pinHiddenInput) {
    pinHiddenInput.addEventListener('input', () => {
        if (isLockedOut || isVerifying) return;
        const clean = pinHiddenInput.value.replace(/\D/g, '').slice(0, TOTAL_SLOTS);
        pinHiddenInput.value = clean;
        enteredPin = clean;
        updateSlotVisuals();
    });

    pinHiddenInput.addEventListener('keydown', (e) => {
        if (isLockedOut || isVerifying) return;
        if (e.key === 'Enter' && enteredPin.length === TOTAL_SLOTS) {
            triggerVerification();
        }
    });
}

// Instant dismiss / key-capture on error state:
window.addEventListener('keydown', (e) => {
    if (isLockedOut) return;
    if (verdictTile && verdictTile.classList.contains('verdict-error')) {
        if (autoResetTimer) {
            clearTimeout(autoResetTimer);
            autoResetTimer = null;
        }
        resetPINBoard(true);
        if (/^[0-9]$/.test(e.key)) {
            enteredPin = e.key;
            if (pinHiddenInput) {
                pinHiddenInput.value = e.key;
            }
            updateSlotVisuals();
        }
    }
});

// Focus / instant reset on click
if (pinAuthCard) {
    pinAuthCard.addEventListener('click', (e) => {
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
        if (!isLockedOut) {
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
ws.onmessage = (event) => {
    try {
        const message = JSON.parse(event.data);

        if (message.type === "session_state") {
            currentState = message.state;
            console.log(`[Victor Session State] ${currentState}`);
            updateUIState(currentState);

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
                micMutedUntil = 0;
                if (authOverlay) {
                    authOverlay.style.display = "none";
                }
                startAudioPipeline().catch(err => console.warn("Audio pipeline init:", err));
                if (audioCtx && audioCtx.state === 'suspended') {
                    audioCtx.resume();
                }
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
            micMutedUntil = 0;
            if (audioCtx && audioCtx.state === 'suspended') {
                audioCtx.resume();
            }

        } else if (message.type === "tool_execution") {
            appendTranscriptEntry("tool", `🔧 Executing tool: ${message.tool} (${message.status})`);

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
        }
    } catch (e) {
        console.error("Error parsing WebSocket message:", e);
    }
};

// Lock Terminal button
if (lockBtn) {
    lockBtn.addEventListener('click', () => {
        ws.send(JSON.stringify({ type: "lock_request" }));
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