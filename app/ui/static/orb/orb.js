/**
 * Victor Particle Orb (Three.js WebGL)
 * 
 * Ported directly from orb.html with advanced GLSL curl-flow turbulence,
 * multi-band audio reactivity (low, mid, high frequencies), state profiles,
 * and an enhanced dense, volumetric non-hollow glowing interior core.
 */

(function () {
    "use strict";

    const vertexShader = `
        attribute float aSeed;
        attribute float aRadius;
        attribute float aSize;
        attribute float aCrest;
        attribute float aHalo;

        uniform float uTime;
        uniform float uEnergy;
        uniform float uBrightness;
        uniform float uSpeed;
        uniform float uNoise;
        uniform float uPulse;
        uniform float uAudio;
        uniform float uLow;
        uniform float uMid;
        uniform float uHigh;
        uniform float uHalo;
        uniform float uDirection;
        uniform float uConnection;
        uniform float uConnectionPulse;
        uniform float uHeartbeatPulse;
        uniform float uSpeaking;
        uniform float uListening;

        varying float vFlow;
        varying float vDepth;
        varying float vLimb;
        varying float vConnectionPulse;
        varying float vVocalBeat;
        varying float vListenBeat;
        varying float vRadius;
        varying float vCrest;
        varying float vBrightness;
        varying float vAlpha;
        varying float vHalo;

        float hash(float n) { return fract(sin(n) * 43758.5453123); }

        vec3 curlFlow(vec3 p, float t) {
            float x = sin(p.y * 4.7 + t) - cos(p.z * 3.9 - t * 0.83);
            float y = sin(p.z * 4.1 - t * 0.71) - cos(p.x * 4.3 + t);
            float z = sin(p.x * 3.7 + t * 0.64) - cos(p.y * 4.9 - t * 0.77);
            return normalize(vec3(x, y, z));
        }

        void main() {
            float time = uTime * (0.32 + uSpeed * 0.68);
            float breathing = sin(uTime * (0.38 + uPulse * 0.12)) * (0.010 + uPulse * 0.022);
            float speech = (uAudio * 0.68 + uLow * 0.72) * (0.018 + uPulse * 0.048);
            vec3 p = position;
            vec3 flow = curlFlow(p * (1.8 + aSeed * 0.8), time + aSeed * 6.283);
            vec3 tangent = normalize(vec3(-p.y, p.x, sin(p.z * 4.0 + time)) + vec3(0.001));
            float shellWeight = smoothstep(0.40, 0.95, aRadius);

            // Volumetric turbulence & flow
            p += flow * (0.006 + (uNoise + uMid * 0.46) * 0.035) * (0.45 + aRadius * 0.6) * sin(time * 1.2 + aSeed * 13.0);
            p += tangent * (uSpeed + uMid * 0.68) * (0.004 + aRadius * 0.012);
            p += normalize(p) * sin(time * 2.2 + aSeed * 19.0) * uEnergy * (0.004 + shellWeight * 0.013);

            float reconnectionLift = uConnectionPulse * shellWeight * (0.004 + aSeed * 0.014) * sin(aSeed * 40.0 + time * 2.8);
            float heartbeatLift = uHeartbeatPulse * (0.003 + aSeed * 0.006);
            float vocalBeat = uSpeaking * (0.5 + 0.5 * sin(uTime * 5.8 + aSeed * 10.0)) * (0.30 + uAudio * 0.70);
            float vocalLift = vocalBeat * (0.004 + shellWeight * 0.008);
            float listenBeat = uListening * (0.5 + 0.5 * sin(uTime * 1.45 + aSeed * 2.2)) * (0.55 + uAudio * 0.45);
            float listenDrift = listenBeat * (0.002 + shellWeight * 0.003);

            p += normalize(p) * (reconnectionLift + heartbeatLift + vocalLift - listenDrift);
            p += flow * (vocalBeat * 0.006 + listenBeat * (0.002 + shellWeight * 0.003));
            p.x += uDirection * (0.010 + shellWeight * 0.014 + uEnergy * 0.022) * sin(time + aSeed * 9.0);
            p *= 1.0 + breathing + speech - listenBeat * 0.004;

            vec4 modelPosition = modelMatrix * vec4(p, 1.0);
            vec4 mvPosition = viewMatrix * modelPosition;
            float perspectiveSize = 1.0 / max(0.42, -mvPosition.z);
            float size = mix(2.2, 5.2, aSize) * (0.88 + shellWeight * 0.62 + uEnergy * 0.38 + uAudio * 0.28 + vocalBeat * 0.18 + listenBeat * 0.08);
            if (aHalo > 0.5) size *= 3.8 + uHalo * 5.0;
            gl_PointSize = size * perspectiveSize * (aHalo > 0.5 ? 4.0 : 2.3);
            gl_Position = projectionMatrix * mvPosition;

            vRadius = aRadius;
            vCrest = max(aCrest, step(0.994 - uHigh * (0.12 * (1.0 - uListening * 0.90)), fract(aSeed * 23.17 + sin(time * 0.7) * 0.5)));
            vBrightness = uBrightness * (0.82 + uConnection * 0.18);
            vHalo = aHalo;

            // NON-HOLLOW CORE: Interior particles are given high, vibrant opacity with zero hollow perception
            vAlpha = mix(0.72, 1.0, shellWeight) * (0.88 + uEnergy * 0.42);
            vAlpha *= mix(0.65, 1.0, smoothstep(0.0, 0.35, aRadius));

            vFlow = pow(max(0.0, sin(atan(p.z, p.x) * 6.0 + p.y * 7.4 - time * 1.72 + flow.y * 2.5)), 5.0);
            vDepth = smoothstep(-0.85, 0.95, p.z);
            vLimb = 1.0 - pow(abs(normalize(p).z), 1.85);
            vConnectionPulse = uConnectionPulse * (0.35 + shellWeight * 0.65);
            vVocalBeat = vocalBeat * (0.35 + shellWeight * 0.65);
            vListenBeat = listenBeat * (0.35 + shellWeight * 0.65);
        }
    `;

    const fragmentShader = `
        precision highp float;

        uniform float uWarning;
        varying float vFlow;
        varying float vDepth;
        varying float vLimb;
        varying float vConnectionPulse;
        varying float vVocalBeat;
        varying float vListenBeat;
        uniform float uAudio;
        uniform float uHalo;
        uniform float uConnection;
        uniform float uConnectionPulse;
        uniform float uHeartbeatPulse;
        uniform float uSpeaking;
        uniform float uListening;

        varying float vRadius;
        varying float vCrest;
        varying float vBrightness;
        varying float vAlpha;
        varying float vHalo;

        void main() {
            vec2 point = gl_PointCoord - 0.5;
            float distanceToCenter = length(point);
            float particle = 1.0 - smoothstep(0.18, 0.5, distanceToCenter);
            float softParticle = exp(-distanceToCenter * distanceToCenter * (vHalo > 0.5 ? 4.2 : 18.0));
            float edge = smoothstep(0.38, 0.96, vRadius);

            // Vibrant, luminous non-hollow plasma interior core
            vec3 core = vec3(0.08, 0.42, 0.85);
            vec3 deepBlue = vec3(0.12, 0.52, 0.95);
            vec3 electric = vec3(0.0, 0.72, 1.0);
            vec3 cyan = vec3(0.48, 0.92, 1.0);
            vec3 warning = vec3(1.0, 0.16, 0.38);

            vec3 color = mix(core, deepBlue, smoothstep(0.05, 0.60, vRadius));
            color = mix(color, electric, 0.22 + edge * (0.42 + vBrightness * 0.35));
            color = mix(color, cyan, vCrest * edge * 0.68 + vFlow * edge * 0.18);
            color = mix(color, warning, uWarning * (0.35 + 0.65 * edge));
            color += electric * vFlow * edge * (0.34 + vBrightness * 0.35);
            color += cyan * vCrest * (0.22 + edge * 0.25 + uAudio * 0.30);

            vec3 mutedConnection = vec3(0.42, 0.55, 0.72);
            float connectionSignal = smoothstep(0.18, 0.92, uConnection);
            color = mix(color * mutedConnection, color, connectionSignal);
            color += cyan * vConnectionPulse * (0.20 + edge * 0.40);
            color += electric * uHeartbeatPulse * (0.10 + edge * 0.18);

            vec3 speakingCyan = vec3(0.28, 0.96, 1.0);
            color = mix(color, speakingCyan, uSpeaking * (0.15 + vVocalBeat * 0.20));
            color += speakingCyan * vVocalBeat * (0.16 + edge * 0.25);

            vec3 listeningIndigo = vec3(0.18, 0.25, 0.78);
            color = mix(color, listeningIndigo, uListening * (0.22 + edge * 0.16));
            color += listeningIndigo * vListenBeat * (0.08 + edge * 0.12);

            float depthFade = mix(0.40, 1.0, vDepth);
            float limbFade = mix(0.22, 1.0, vLimb);
            float alpha = (vHalo > 0.5 ? softParticle * uHalo * 0.055 : particle * vAlpha * depthFade * limbFade) * (0.80 + vBrightness * 0.75);
            if (alpha < 0.005) discard;

            gl_FragColor = vec4(color * alpha * (0.75 + vBrightness * 0.78), alpha);
        }
    `;

    const PROFILES = {
        idle:           { energy: 0.36, brightness: 0.72, speed: 0.12, noise: 0.16, pulse: 0.26, halo: 0.42, warning: 0, direction: 0.0 },
        wake:           { energy: 1.0,  brightness: 1.0,  speed: 1.6,  noise: 0.82, pulse: 1.25, halo: 0.96, warning: 0, direction: 0.42 },
        listening:      { energy: 0.65, brightness: 0.75, speed: 0.48, noise: 0.44, pulse: 0.82, halo: 0.60, warning: 0, direction: 0.1 },
        thinking:       { energy: 0.82, brightness: 0.80, speed: 0.75, noise: 0.58, pulse: 0.60, halo: 0.72, warning: 0, direction: -0.10 },
        processing:     { energy: 0.88, brightness: 0.86, speed: 1.10, noise: 0.76, pulse: 0.72, halo: 0.82, warning: 0, direction: 0.24 },
        executing:      { energy: 0.95, brightness: 0.94, speed: 1.35, noise: 0.68, pulse: 0.78, halo: 0.86, warning: 0, direction: 0.82 },
        speaking:       { energy: 0.82, brightness: 0.92, speed: 0.62, noise: 0.50, pulse: 1.22, halo: 0.84, warning: 0, direction: 0.05 },
        authentication: { energy: 0.45, brightness: 0.60, speed: 0.24, noise: 0.20, pulse: 0.68, halo: 0.48, warning: 0, direction: 0.0 },
        error:          { energy: 0.52, brightness: 0.72, speed: 0.80, noise: 0.94, pulse: 0.98, halo: 0.70, warning: 1, direction: -0.35 },
        offline:        { energy: 0.08, brightness: 0.16, speed: 0.03, noise: 0.05, pulse: 0.08, halo: 0.06, warning: 0, direction: 0.0 },
        locked:         { energy: 0.18, brightness: 0.35, speed: 0.06, noise: 0.08, pulse: 0.14, halo: 0.18, warning: 0, direction: 0.0 },
    };

    function chooseParticleCount() {
        const cores = navigator.hardwareConcurrency || 6;
        const pixelRatio = window.devicePixelRatio || 1;
        if (Math.min(window.innerWidth, window.innerHeight) < 700) return 32000;
        if (cores >= 10 && pixelRatio <= 1.5) return 100000;
        if (cores >= 6) return 72000;
        return 45000;
    }

    function createParticleGeometry(count) {
        const positions = new Float32Array(count * 3);
        const seeds = new Float32Array(count);
        const radii = new Float32Array(count);
        const sizes = new Float32Array(count);
        const crests = new Float32Array(count);
        const halos = new Float32Array(count);

        for (let i = 0; i < count; i++) {
            const u = Math.random();
            const v = Math.random();
            const theta = 2 * Math.PI * u;
            const phi = Math.acos(2 * v - 1);
            const isShell = Math.random() < 0.48;
            
            // NON-HOLLOW CORE DISTRIBUTION:
            // 48% particles form the outer filament shell (0.72 - 0.98)
            // 52% particles densely fill the interior sphere volume from center 0.0 to 0.72!
            let radius;
            if (isShell) {
                radius = 0.72 + Math.pow(Math.random(), 0.65) * 0.26;
            } else {
                // Sphere volume packing (cube root makes density uniform through volume)
                radius = Math.pow(Math.random(), 0.42) * 0.74;
            }

            const sinPhi = Math.sin(phi);
            const isHalo = Math.random() < 0.007;
            const haloRadius = isHalo ? 1.04 + Math.random() * 0.15 : radius;

            positions[i * 3] = haloRadius * sinPhi * Math.cos(theta);
            positions[i * 3 + 1] = haloRadius * Math.cos(phi);
            positions[i * 3 + 2] = haloRadius * sinPhi * Math.sin(theta);

            seeds[i] = Math.random();
            radii[i] = Math.min(1.0, haloRadius);
            sizes[i] = 0.20 + Math.random() * 0.80;
            crests[i] = Math.random() > 0.982 ? 1.0 : 0.0;
            halos[i] = isHalo ? 1.0 : 0.0;
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
        geometry.setAttribute("aRadius", new THREE.BufferAttribute(radii, 1));
        geometry.setAttribute("aSize", new THREE.BufferAttribute(sizes, 1));
        geometry.setAttribute("aCrest", new THREE.BufferAttribute(crests, 1));
        geometry.setAttribute("aHalo", new THREE.BufferAttribute(halos, 1));
        return geometry;
    }

    class VictorOrbController {
        constructor(containerId = "orb-container") {
            this.container = document.getElementById(containerId);
            if (!this.container) return;

            this.quality = chooseParticleCount();
            this.state = {
                current: "locked",
                audioTarget: 0,
                audio: 0,
                lowTarget: 0,
                midTarget: 0,
                highTarget: 0,
                low: 0,
                mid: 0,
                high: 0,
                connection: 0.95,
                connectionTarget: 0.95,
                connectionPulse: 0,
                heartbeatPulse: 0,
                heartbeatNextAt: 0,
                speaking: 0,
                listening: 0,
                errorTimer: null,
            };

            this.target = Object.assign({}, PROFILES.locked);
            this.visual = Object.assign({}, PROFILES.locked);

            this.initThree();
        }

        initThree() {
            this.renderer = new THREE.WebGLRenderer({
                antialias: false,
                alpha: true,
                powerPreference: "high-performance"
            });
            this.renderer.setClearColor(0x000000, 0); // Transparent background for HUD layout
            this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
            this.renderer.outputColorSpace = THREE.SRGBColorSpace;
            this.container.innerHTML = "";
            this.container.appendChild(this.renderer.domElement);

            this.scene = new THREE.Scene();
            this.camera = new THREE.PerspectiveCamera(34, 1, 0.1, 10);
            this.camera.position.set(0, 0, 3.85);

            this.geometry = createParticleGeometry(this.quality);
            this.material = new THREE.ShaderMaterial({
                vertexShader: vertexShader,
                fragmentShader: fragmentShader,
                transparent: true,
                depthWrite: false,
                depthTest: true,
                blending: THREE.AdditiveBlending,
                uniforms: {
                    uTime: { value: 0 },
                    uEnergy: { value: this.visual.energy },
                    uBrightness: { value: this.visual.brightness },
                    uSpeed: { value: this.visual.speed },
                    uNoise: { value: this.visual.noise },
                    uPulse: { value: this.visual.pulse },
                    uAudio: { value: 0 },
                    uLow: { value: 0 },
                    uMid: { value: 0 },
                    uHigh: { value: 0 },
                    uHalo: { value: this.visual.halo },
                    uWarning: { value: 0 },
                    uDirection: { value: 0 },
                    uConnection: { value: this.state.connection },
                    uConnectionPulse: { value: 0 },
                    uHeartbeatPulse: { value: 0 },
                    uSpeaking: { value: 0 },
                    uListening: { value: 0 },
                },
            });

            this.points = new THREE.Points(this.geometry, this.material);
            this.scene.add(this.points);

            this.clock = new THREE.Clock();
            this.resize();
            window.addEventListener("resize", () => this.resize());

            this.tick = this.tick.bind(this);
            this.tick();
        }

        resize() {
            if (!this.container || !this.renderer) return;
            const width = this.container.clientWidth || 500;
            const height = this.container.clientHeight || 500;
            const side = Math.min(width, height);
            this.renderer.setSize(side, side, false);
            this.camera.aspect = 1;
            this.camera.updateProjectionMatrix();
        }

        normalizeState(stateName) {
            if (!stateName) return "idle";
            const s = String(stateName).trim().toLowerCase().replace(/[\s-]+/g, "_");
            const map = {
                locked: "locked",
                closed: "offline",
                offline: "offline",
                authenticating: "authentication",
                auth_success: "wake",
                connecting: "processing",
                active: "listening",
                idle: "idle",
                listening: "listening",
                thinking: "thinking",
                processing: "processing",
                executing: "executing",
                speaking: "speaking",
                error: "error",
            };
            return map[s] || "listening";
        }

        setState(stateName) {
            const normalized = this.normalizeState(stateName);
            if (this.state.current === "error" && normalized !== "error") return;
            this.state.current = PROFILES[normalized] ? normalized : "idle";
            Object.assign(this.target, PROFILES[this.state.current]);

            if (this.state.current === "wake") {
                setTimeout(() => {
                    if (this.state.current === "wake") this.setState("listening");
                }, 650);
            }
        }

        triggerError() {
            if (this.state.errorTimer !== null) clearTimeout(this.state.errorTimer);
            const prev = this.state.current;
            this.state.current = "error";
            Object.assign(this.target, PROFILES.error);
            this.state.errorTimer = setTimeout(() => {
                this.state.errorTimer = null;
                this.setState(prev);
            }, 4000);
        }

        setAudioEnergy(energy, low = null, mid = null, high = null) {
            const val = THREE.MathUtils.clamp(energy, 0, 1);
            this.state.audioTarget = val;
            if (low !== null) this.state.lowTarget = THREE.MathUtils.clamp(low, 0, 1);
            else this.state.lowTarget = val * 0.85;

            if (mid !== null) this.state.midTarget = THREE.MathUtils.clamp(mid, 0, 1);
            else this.state.midTarget = val * 0.70;

            if (high !== null) this.state.highTarget = THREE.MathUtils.clamp(high, 0, 1);
            else this.state.highTarget = val * 0.50;
        }

        tick() {
            requestAnimationFrame(this.tick);
            const elapsed = this.clock.getElapsedTime();
            const mixRate = 0.048;

            // Interpolate target visual profiles
            this.visual.energy += (this.target.energy - this.visual.energy) * mixRate;
            this.visual.brightness += (this.target.brightness - this.visual.brightness) * mixRate;
            this.visual.speed += (this.target.speed - this.visual.speed) * mixRate;
            this.visual.noise += (this.target.noise - this.visual.noise) * mixRate;
            this.visual.pulse += (this.target.pulse - this.visual.pulse) * mixRate;
            this.visual.halo += (this.target.halo - this.visual.halo) * mixRate;
            this.visual.warning += (this.target.warning - this.visual.warning) * mixRate;
            this.visual.direction += (this.target.direction - this.visual.direction) * mixRate;

            // Audio smoothing
            this.state.audio += (this.state.audioTarget - this.state.audio) * 0.16;
            this.state.low += (this.state.lowTarget - this.state.low) * 0.13;
            this.state.mid += (this.state.midTarget - this.state.mid) * 0.13;
            this.state.high += (this.state.highTarget - this.state.high) * 0.13;

            // Connection heartbeat
            this.state.connection += (this.state.connectionTarget - this.state.connection) * 0.055;
            this.state.connectionPulse += (0 - this.state.connectionPulse) * 0.055;
            if (this.state.connection > 0.85) {
                if (this.state.heartbeatNextAt === 0) {
                    this.state.heartbeatNextAt = performance.now() + 6000 + Math.random() * 3000;
                }
                if (performance.now() >= this.state.heartbeatNextAt) {
                    this.state.heartbeatPulse = 1.0;
                    this.state.heartbeatNextAt = performance.now() + 6000 + Math.random() * 3000;
                }
            }
            this.state.heartbeatPulse += (0 - this.state.heartbeatPulse) * 0.035;

            // State specific blends
            const isSpeaking = this.state.current === "speaking" ? 1.0 : 0.0;
            this.state.speaking += (isSpeaking - this.state.speaking) * 0.08;

            const isListening = this.state.current === "listening" ? 1.0 : 0.0;
            this.state.listening += (isListening - this.state.listening) * 0.08;

            // Uniform assignments
            const u = this.material.uniforms;
            u.uTime.value = elapsed;
            u.uEnergy.value = this.visual.energy + this.state.low * 0.24 + this.state.mid * 0.12;
            u.uBrightness.value = this.visual.brightness + this.state.audio * 0.28 + this.state.high * 0.14;
            u.uSpeed.value = this.visual.speed + this.state.mid * 0.48;
            u.uNoise.value = this.visual.noise + this.state.mid * 0.28;
            u.uPulse.value = this.visual.pulse + this.state.low * 0.55;
            u.uAudio.value = this.state.audio;
            u.uLow.value = this.state.low;
            u.uMid.value = this.state.mid;
            u.uHigh.value = this.state.high;
            u.uHalo.value = this.visual.halo + this.state.audio * 0.22;
            u.uWarning.value = this.visual.warning;
            u.uDirection.value = this.visual.direction;
            u.uConnection.value = this.state.connection;
            u.uConnectionPulse.value = this.state.connectionPulse;
            u.uHeartbeatPulse.value = this.state.heartbeatPulse;
            u.uSpeaking.value = this.state.speaking;
            u.uListening.value = this.state.listening;

            u.uEnergy.value += this.state.heartbeatPulse * 0.05 + this.state.speaking * this.state.audio * 0.06;
            u.uSpeed.value += this.state.speaking * (0.10 + this.state.audio * 0.25);
            u.uBrightness.value += this.state.heartbeatPulse * 0.08;
            u.uHalo.value += this.state.heartbeatPulse * 0.07;

            this.points.rotation.y = elapsed * (0.018 + this.visual.speed * 0.028);
            this.points.rotation.x = Math.sin(elapsed * 0.12) * 0.045;

            this.renderer.render(this.scene, this.camera);
        }
    }

    // Attach to global window
    window.VictorOrb = VictorOrbController;
    window.addEventListener("DOMContentLoaded", () => {
        window.VictorOrbInstance = new VictorOrbController("orb-container");
    });
})();