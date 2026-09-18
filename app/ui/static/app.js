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
let mediaStream = null;
let activeAudioSources = [];

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
    if (audioCtx) return;
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
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
            if (currentState !== "ACTIVE" && currentState !== "LISTENING" && currentState !== "SPEAKING") return;

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
    source.onended = () => {
        const idx = activeAudioSources.indexOf(source);
        if (idx !== -1) activeAudioSources.splice(idx, 1);
        if (activeAudioSources.length === 0 || audioCtx.currentTime >= nextPlayTime - 0.02) {
            isSpeaking = false;
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
function updateUIState(stateName) {
    if (globalStatusText) globalStatusText.textContent = stateName;
    if (orbStateText) orbStateText.textContent = stateName;
    
    if (window.VictorOrbInstance) {
        window.VictorOrbInstance.setState(stateName);
    }
}

// ==========================================================================
// 6-DIGIT 3D PIN VERIFICATION CONTROLLER
// ==========================================================================
let enteredPin = "";
let isVerifying = false;
const HARDCODED_PIN = "081225";
const TOTAL_SLOTS = 6;
const pinSlots = document.querySelectorAll('.pin-slot-anchor');
const checkIcon = verdictTile ? verdictTile.querySelector('.check-icon') : null;
const crossIcon = verdictTile ? verdictTile.querySelector('.cross-icon') : null;

function updateSlotVisuals() {
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
    if (isVerifying || enteredPin.length !== TOTAL_SLOTS) return;
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
    // Entire circle spins 1.25 turns (450 deg) over exactly 2s while individual slots flip top-to-bottom
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
    // 6 slots screw down (shrink and collapse) into the center of the orbit, merging into one tile
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
        // Success: Center tile becomes green verified checkmark
        if (verdictTile) {
            verdictTile.classList.add('verdict-success');
        }
        if (checkIcon) checkIcon.classList.remove('hidden');
        if (crossIcon) crossIcon.classList.add('hidden');
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
                    resetPINBoard();
                }, 400);
            }
        }, 900);

    } else {
        // Error: Center tile becomes red error cross with Verification Failed text
        if (verdictTile) {
            verdictTile.classList.add('verdict-error');
        }
        if (crossIcon) crossIcon.classList.remove('hidden');
        if (checkIcon) checkIcon.classList.add('hidden');
        if (pinStatusText) {
            pinStatusText.innerHTML = '<span style="color: var(--accent-rose); font-weight: 600; letter-spacing: 2px;">VERIFICATION FAILED</span><br><span style="font-size: 0.72rem; color: var(--text-secondary); letter-spacing: 1px; margin-top: 4px; display: inline-block;">Click tile to retry</span>';
        }
    }
}

function resetPINBoard() {
    enteredPin = "";
    if (pinHiddenInput) pinHiddenInput.value = "";
    isVerifying = false;

    if (pinOrbitRing) {
        pinOrbitRing.classList.remove('is-orbiting', 'is-spinning', 'is-screwing-down');
    }

    if (verdictTile) {
        verdictTile.classList.remove('is-visible', 'verdict-success', 'verdict-error');
        if (checkIcon) checkIcon.classList.add('hidden');
        if (crossIcon) crossIcon.classList.add('hidden');
    }

    if (pinVerifyBtn) {
        pinVerifyBtn.classList.remove('is-visible');
    }

    if (pinStatusText) {
        pinStatusText.innerHTML = "";
    }

    updateSlotVisuals();

    if (authOverlay && authOverlay.style.display !== 'none') {
        setTimeout(() => {
            if (pinHiddenInput) pinHiddenInput.focus();
        }, 60);
    }
}

// Step 1: Input handling & typing numbers invisible with blinking cursor
if (pinHiddenInput) {
    pinHiddenInput.addEventListener('input', () => {
        if (isVerifying) return;
        const clean = pinHiddenInput.value.replace(/\D/g, '').slice(0, TOTAL_SLOTS);
        pinHiddenInput.value = clean;
        enteredPin = clean;
        updateSlotVisuals();
    });

    pinHiddenInput.addEventListener('keydown', (e) => {
        if (isVerifying) return;
        if (e.key === 'Enter' && enteredPin.length === TOTAL_SLOTS) {
            triggerVerification();
        }
    });
}

// Focus on click
if (pinStage) {
    pinStage.addEventListener('click', () => {
        if (verdictTile && verdictTile.classList.contains('verdict-error')) {
            resetPINBoard();
        } else if (!isVerifying && pinHiddenInput) {
            pinHiddenInput.focus();
        }
    });
}

// Step 3: Button trigger
if (pinVerifyBtn) {
    pinVerifyBtn.addEventListener('click', () => {
        if (!isVerifying && enteredPin.length === TOTAL_SLOTS) {
            triggerVerification();
        }
    });
}

// Step 8: Reset on clicking verdict icon
if (verdictTile) {
    verdictTile.addEventListener('click', (e) => {
        e.stopPropagation();
        resetPINBoard();
    });
}

// Auto-focus input on page load
setTimeout(() => {
    if (pinHiddenInput && authOverlay && authOverlay.style.display !== 'none') {
        pinHiddenInput.focus();
    }
}, 300);

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
                if (authOverlay) {
                    authOverlay.style.display = "flex";
                    authOverlay.style.opacity = "1";
                }
                resetPINBoard();
                stopAudioPipeline();
            } else if (currentState === "ACTIVE") {
                if (authOverlay) {
                    authOverlay.style.opacity = "0";
                    setTimeout(() => {
                        authOverlay.style.display = "none";
                    }, 400);
                }
            }

        } else if (message.type === "orb_state") {
            updateUIState(message.state);

        } else if (message.type === "transcript") {
            appendTranscriptEntry(message.role, message.text);

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
            }

        } else if (message.type === "audio_output") {
            playAudioChunk(message.data);
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