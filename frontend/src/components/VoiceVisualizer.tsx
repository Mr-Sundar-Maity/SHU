import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { useShu } from '../context/ShuContext';
import {
  PEAK_HOLD_WINDOW_MS,
  computeRhythmicPulse,
  fillHologramWaveLoop,
  updatePerBarPeakHold,
  updateRollingPeakHistory,
  type PeakSample,
} from '../utils/waveformMath';

import { getHoloColorTheme } from '../utils/colorTheme';

interface VisualizerLiveRef {
  analyser: AnalyserNode | null;
  audioLevel: number;
  isUserSpeaking: boolean;
  colorTheme: string;
  reducedMotion: boolean;
}

const WAVE_POINTS = 96;
const BAR_COUNT = 48;

// Pre-allocated scratch helpers outside render loop (zero GC)
const _barDummy = new THREE.Object3D();

export const VoiceVisualizer: React.FC = () => {
  const {
    audioAnalyser,
    audioLevel,
    isUserSpeaking,
    recognizedVoiceSeq,
    triggerDataGridRipple,
    settings,
  } = useShu();
  const mountRef = useRef<HTMLDivElement | null>(null);
  const peakContainerRef = useRef<HTMLDivElement | null>(null);
  const peakLabelRef = useRef<HTMLSpanElement | null>(null);
  const peakMarkerRef = useRef<HTMLSpanElement | null>(null);
  const liveFillRef = useRef<HTMLSpanElement | null>(null);
  const [webglFallback, setWebglFallback] = useState(false);

  const lastHandledVoiceSeqRef = useRef(recognizedVoiceSeq);
  const recognitionBoostRef = useRef(0);

  const liveRef = useRef<VisualizerLiveRef>({
    analyser: audioAnalyser,
    audioLevel,
    isUserSpeaking,
    colorTheme: settings.colorTheme,
    reducedMotion: false,
  });

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    liveRef.current = {
      analyser: audioAnalyser,
      audioLevel,
      isUserSpeaking,
      colorTheme: settings.colorTheme,
      reducedMotion: Boolean(mq?.matches),
    };
  }, [audioAnalyser, audioLevel, isUserSpeaking, settings.colorTheme]);

  // Trigger full background data-grid ripple whenever a voice command is recognized
  useEffect(() => {
    if (recognizedVoiceSeq > lastHandledVoiceSeqRef.current) {
      lastHandledVoiceSeqRef.current = recognizedVoiceSeq;
      recognitionBoostRef.current = 1;
      triggerDataGridRipple();
    }
  }, [recognizedVoiceSeq, triggerDataGridRipple]);

  useEffect(() => {
    if (!isUserSpeaking) return;
    const container = mountRef.current;
    if (!container) return;

    const isSoftwareGl = (() => {
      try {
        const probe = document.createElement('canvas').getContext('webgl2');
        if (!probe) return true;
        const ext = probe.getExtension('WEBGL_debug_renderer_info');
        const param = ext ? ext.UNMASKED_RENDERER_WEBGL : probe.RENDERER;
        const gpu = String(probe.getParameter(param));
        probe.getExtension('WEBGL_lose_context')?.loseContext();
        return /SwiftShader|llvmpipe|softpipe|Software|Basic Render/i.test(gpu);
      } catch {
        return true;
      }
    })();

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: !isSoftwareGl,
        alpha: true,
        powerPreference: 'high-performance',
        preserveDrawingBuffer: true,
      });
    } catch {
      setWebglFallback(true);
      return;
    }

    const width = container.clientWidth || 440;
    const height = container.clientHeight || 320;
    renderer.setSize(width, height);
    renderer.setPixelRatio(isSoftwareGl ? 1 : Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(renderer.domElement);

    const onContextLost = (e: Event) => e.preventDefault();
    renderer.domElement.addEventListener('webglcontextlost', onContextLost);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 30);
    camera.position.set(0, 1.55, 4.45);
    camera.lookAt(0, 0, 0);

    const holoGroup = new THREE.Group();
    holoGroup.rotation.x = 0.14;
    scene.add(holoGroup);

    const initialTheme = getHoloColorTheme(liveRef.current.colorTheme);

    // 1. Primary 3D Waveform Ring (driven by Web Audio time-domain data)
    const primaryPositions = new Float32Array((WAVE_POINTS + 1) * 3);
    const primaryGeo = new THREE.BufferGeometry();
    primaryGeo.setAttribute('position', new THREE.BufferAttribute(primaryPositions, 3));
    const primaryMat = new THREE.LineBasicMaterial({
      color: initialTheme.secondaryHex,
      transparent: true,
      opacity: 0.95,
    });
    const primaryWave = new THREE.LineLoop(primaryGeo, primaryMat);
    holoGroup.add(primaryWave);

    // 2. Secondary Phase-Shifted Echo Ring
    const echoPositions = new Float32Array((WAVE_POINTS + 1) * 3);
    const echoGeo = new THREE.BufferGeometry();
    echoGeo.setAttribute('position', new THREE.BufferAttribute(echoPositions, 3));
    const echoMat = new THREE.LineBasicMaterial({
      color: initialTheme.primaryHex,
      transparent: true,
      opacity: 0.72,
    });
    const echoWave = new THREE.LineLoop(echoGeo, echoMat);
    echoWave.position.y = -0.1;
    holoGroup.add(echoWave);

    // 3. 3D Radial Spectrum Bars (InstancedMesh driven by Web Audio frequency bins)
    const barGeo = new THREE.BoxGeometry(0.032, 0.42, 0.032);
    const barMat = new THREE.MeshBasicMaterial({
      color: initialTheme.accentHex,
      transparent: true,
      opacity: 0.78,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const barsMesh = new THREE.InstancedMesh(barGeo, barMat, BAR_COUNT);
    barsMesh.frustumCulled = false;
    holoGroup.add(barsMesh);

    // 3b. 3D Peak-Hold Caps hovering at each bar's 2-second maximum amplitude
    const capGeo = new THREE.BoxGeometry(0.056, 0.02, 0.056);
    const capMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.92,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const peakCapsMesh = new THREE.InstancedMesh(capGeo, capMat, BAR_COUNT);
    peakCapsMesh.frustumCulled = false;
    holoGroup.add(peakCapsMesh);

    // 4. Holographic Scanline Interference Disc with Rhythmic Pulse
    const discGeo = new THREE.RingGeometry(0.85, 1.88, 64);
    const discMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uEnergy: { value: 0.3 },
        uPulse: { value: 0.5 },
        uMixA: { value: new THREE.Vector3(...initialTheme.shaderMixRgb) },
        uMixB: { value: new THREE.Vector3(...initialTheme.shaderAccentRgb) },
      },
      vertexShader: `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        uniform float uTime;
        uniform float uEnergy;
        uniform float uPulse;
        uniform vec3 uMixA;
        uniform vec3 uMixB;
        varying vec2 vUv;
        void main() {
          vec2 centered = vUv - 0.5;
          float r = length(centered) * 2.0;
          float rings = 0.5 + 0.5 * sin(r * 36.0 - uTime * 5.0);
          float pulseBand = exp(-pow((r - (0.42 + uPulse * 0.52)) * 9.0, 2.0));
          float edge = smoothstep(0.38, 0.96, r) * (1.0 - smoothstep(0.9, 1.0, r));
          float alpha = edge * (0.14 + uEnergy * 0.28 + pulseBand * (0.22 + uEnergy * 0.35)) * (0.55 + 0.45 * rings);
          vec3 col = mix(uMixA, uMixB, pulseBand * 0.7 + r * 0.3);
          gl_FragColor = vec4(col, alpha);
        }
      `,
      transparent: true,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const discMesh = new THREE.Mesh(discGeo, discMat);
    discMesh.rotation.x = -Math.PI / 2;
    holoGroup.add(discMesh);

    // 5. Rhythmic Amplitude Shockwave Ring (expands outward in sync with voice beats)
    const shockGeo = new THREE.RingGeometry(1.42, 1.5, 64);
    const shockMat = new THREE.MeshBasicMaterial({
      color: 0x67e8f9,
      transparent: true,
      opacity: 0.55,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const shockMesh = new THREE.Mesh(shockGeo, shockMat);
    shockMesh.rotation.x = -Math.PI / 2;
    holoGroup.add(shockMesh);

    const onResize = () => {
      const w = container.clientWidth || 440;
      const h = container.clientHeight || 320;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      renderer.render(scene, camera);
    };
    window.addEventListener('resize', onResize);

    let timeBuf: Uint8Array<ArrayBuffer> | null = null;
    let freqBuf: Uint8Array<ArrayBuffer> | null = null;
    let frameId = 0;
    let disposed = false;
    const startMs = performance.now();
    let prevMs = startMs;
    let smoothEnergy = 0.2;
    let pulsePhase = 0;
    let peakSamples: PeakSample[] = [];
    const barPeakScales = new Float32Array(BAR_COUNT);
    const barPeakTimes = new Float64Array(BAR_COUNT);
    let lastHudUpdateMs = 0;

    function afterDraw(cb: () => void) {
      const gl = renderer.getContext() as WebGL2RenderingContext;
      const sync = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
      gl.flush();
      const poll = () => {
        if (disposed) return;
        const status = sync && gl.getSyncParameter(sync, gl.SYNC_STATUS);
        if (status === gl.UNSIGNALED) {
          frameId = window.setTimeout(poll, 5);
        } else {
          if (sync) gl.deleteSync(sync);
          frameId = window.setTimeout(cb, 80);
        }
      };
      frameId = window.setTimeout(poll, 5);
    }

    function tick() {
      if (disposed) return;
      const nowMs = performance.now();
      const delta = Math.min((nowMs - prevMs) / 1000, 0.1);
      prevMs = nowMs;
      const elapsed = (nowMs - startMs) / 1000;

      const { analyser, audioLevel: level, colorTheme, reducedMotion } = liveRef.current;
      const activeTheme = getHoloColorTheme(colorTheme);
      primaryMat.color.setHex(activeTheme.secondaryHex);
      echoMat.color.setHex(activeTheme.primaryHex);
      barMat.color.setHex(activeTheme.accentHex);
      shockMat.color.setHex(activeTheme.accentHex);
      discMat.uniforms.uMixA.value.set(...activeTheme.shaderMixRgb);
      discMat.uniforms.uMixB.value.set(...activeTheme.shaderAccentRgb);

      if (analyser) {
        if (!timeBuf || timeBuf.length !== analyser.fftSize) {
          timeBuf = new Uint8Array(new ArrayBuffer(analyser.fftSize));
        }
        if (!freqBuf || freqBuf.length !== analyser.frequencyBinCount) {
          freqBuf = new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount));
        }
        analyser.getByteTimeDomainData(timeBuf);
        analyser.getByteFrequencyData(freqBuf);
      }

      recognitionBoostRef.current = Math.max(0, recognitionBoostRef.current - delta * 1.45);
      const recognitionBoost = recognitionBoostRef.current;
      const effectiveLevel = Math.min(1, Math.max(0.18, level) + recognitionBoost * 0.45);

      smoothEnergy = THREE.MathUtils.damp(smoothEnergy, effectiveLevel, 10, delta);

      // Accumulate rhythmic pulse phase proportionally to waveform amplitude
      if (!reducedMotion) {
        pulsePhase += delta * (3.0 + smoothEnergy * 6.5);
      }
      const pulse = computeRhythmicPulse(smoothEnergy, pulsePhase, reducedMotion);

      // Apply rhythmic breathing scale, levitation, and opacity sync
      holoGroup.scale.setScalar(pulse.scale + recognitionBoost * 0.08);
      holoGroup.position.y = pulse.lift;
      primaryMat.opacity = Math.min(1, pulse.opacity + recognitionBoost * 0.15);
      echoMat.opacity = Math.max(0.45, pulse.opacity * 0.78);
      barMat.opacity = Math.min(0.95, 0.55 + pulse.waveIntensity * 0.4);

      // Expanding rhythmic shockwave ring synchronized to amplitude beat & command recognition
      const shockScale = 0.88 + pulse.ringExpand * (0.45 + smoothEnergy * 0.35) + recognitionBoost * 0.25;
      shockMesh.scale.setScalar(shockScale);
      shockMat.opacity = Math.min(0.95, (1 - pulse.ringExpand) * (0.28 + smoothEnergy * 0.52) + recognitionBoost * 0.35);

      // Update primary & echo 3D waveform loops
      fillHologramWaveLoop(primaryPositions, WAVE_POINTS, 1.38, timeBuf, elapsed, smoothEnergy);
      (primaryGeo.getAttribute('position') as THREE.BufferAttribute).needsUpdate = true;

      fillHologramWaveLoop(echoPositions, WAVE_POINTS, 1.08, timeBuf, elapsed + 0.65, smoothEnergy * 0.78);
      (echoGeo.getAttribute('position') as THREE.BufferAttribute).needsUpdate = true;

      // Update 48 3D frequency pillars + 2-second peak-hold caps
      const binLen = freqBuf?.length ?? 0;
      const barRadius = 1.62 + (pulse.scale - 1) * 0.85;
      let frameMaxFreqNorm = 0;

      if (binLen > 0 && freqBuf) {
        for (let b = 0; b < binLen; b += 1) {
          const norm = freqBuf[b] / 255;
          if (norm > frameMaxFreqNorm) frameMaxFreqNorm = norm;
        }
      }

      for (let i = 0; i < BAR_COUNT; i += 1) {
        const ang = (i / BAR_COUNT) * Math.PI * 2;
        let binVal = 0.25 + 0.2 * Math.sin(elapsed * 4.2 + i * 0.45);
        if (binLen > 0 && freqBuf) {
          const binIdx = Math.floor((i / BAR_COUNT) * binLen);
          binVal = Math.max(0.12, freqBuf[binIdx] / 255);
        } else if (binVal > frameMaxFreqNorm) {
          frameMaxFreqNorm = binVal;
        }
        const scaleY = 0.22 + binVal * (0.9 + smoothEnergy * 1.45) * (0.9 + pulse.waveIntensity * 0.25);
        _barDummy.position.set(Math.cos(ang) * barRadius, 0, Math.sin(ang) * barRadius);
        _barDummy.rotation.set(0, -ang, 0);
        _barDummy.scale.set(1, scaleY, 1);
        _barDummy.updateMatrix();
        barsMesh.setMatrixAt(i, _barDummy.matrix);

        // 2s peak-hold cap floats at the maximum height reached in the last 2 seconds
        const peakBarScaleY = updatePerBarPeakHold(
          barPeakScales,
          barPeakTimes,
          i,
          scaleY,
          nowMs,
          delta,
          PEAK_HOLD_WINDOW_MS
        );
        _barDummy.position.set(
          Math.cos(ang) * barRadius,
          peakBarScaleY * 0.21 + 0.035,
          Math.sin(ang) * barRadius
        );
        _barDummy.rotation.set(0, -ang, 0);
        _barDummy.scale.set(1, 1, 1);
        _barDummy.updateMatrix();
        peakCapsMesh.setMatrixAt(i, _barDummy.matrix);
      }
      barsMesh.instanceMatrix.needsUpdate = true;
      peakCapsMesh.instanceMatrix.needsUpdate = true;

      // Update rolling 2-second maximum frequency amplitude telemetry (throttled DOM refs, zero 60Hz setState)
      const peakResult = updateRollingPeakHistory(
        peakSamples,
        frameMaxFreqNorm,
        nowMs,
        PEAK_HOLD_WINDOW_MS
      );
      peakSamples = peakResult.samples;

      if (nowMs - lastHudUpdateMs >= 80) {
        lastHudUpdateMs = nowMs;
        const livePct = Math.round(Math.max(0, Math.min(1, frameMaxFreqNorm)) * 100);
        const peakPct = Math.round(peakResult.peakAmplitude * 100);
        if (peakContainerRef.current) {
          peakContainerRef.current.setAttribute(
            'data-peak-amplitude',
            peakResult.peakAmplitude.toFixed(3)
          );
          peakContainerRef.current.setAttribute('data-peak-db', String(peakResult.peakDb));
        }
        if (peakLabelRef.current) {
          peakLabelRef.current.textContent = `Peak (2s): ${peakPct}% · ${peakResult.peakDb.toFixed(1)} dB`;
        }
        if (liveFillRef.current) {
          liveFillRef.current.style.transform = `scaleX(${(livePct / 100).toFixed(3)})`;
        }
        if (peakMarkerRef.current) {
          peakMarkerRef.current.style.left = `calc(${Math.min(98, Math.max(2, peakPct))}% - 1px)`;
        }
      }

      discMat.uniforms.uTime.value = elapsed;
      discMat.uniforms.uEnergy.value = smoothEnergy;
      discMat.uniforms.uPulse.value = pulse.ringExpand;

      if (!reducedMotion) {
        holoGroup.rotation.y += delta * (0.35 + smoothEnergy * 0.35);
        echoWave.rotation.y -= delta * 0.24;
      }

      renderer.render(scene, camera);

      if (isSoftwareGl) {
        afterDraw(tick);
      } else {
        frameId = requestAnimationFrame(tick);
      }
    }

    tick();

    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      clearTimeout(frameId);
      window.removeEventListener('resize', onResize);
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost);

      primaryGeo.dispose();
      primaryMat.dispose();
      echoGeo.dispose();
      echoMat.dispose();
      barGeo.dispose();
      barMat.dispose();
      capGeo.dispose();
      capMat.dispose();
      discGeo.dispose();
      discMat.dispose();
      shockGeo.dispose();
      shockMat.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [isUserSpeaking]);

  if (!isUserSpeaking) {
    return null;
  }

  return (
    <div
      data-testid="voice-visualizer-container"
      aria-label="Live 3D voice waveform hologram"
      className="pointer-events-none flex flex-col items-center justify-center"
    >
      <div className="relative h-60 w-80 sm:h-64 sm:w-[440px]">
        <div
          ref={mountRef}
          data-testid="voice-visualizer-canvas"
          className="h-full w-full"
        />
        {webglFallback && (
          <div className="absolute inset-0 flex items-center justify-center gap-1.5">
            {Array.from({ length: 16 }).map((_, idx) => (
              <span
                key={idx}
                className="w-1 rounded-full bg-teal-400/80"
                style={{
                  height: `${Math.round(16 + audioLevel * 54 * (0.4 + (idx % 4) * 0.2))}px`,
                }}
              />
            ))}
          </div>
        )}
      </div>
      <div className="mt-1 flex flex-col items-center gap-1 rounded-lg border border-sky-400/25 bg-slate-950/80 px-3 py-1.5 backdrop-blur-sm shadow-[0_4px_18px_rgba(2,6,23,0.75)]">
        <p className="font-mono text-[11px] tracking-wider text-teal-300">
          Voice waveform active
        </p>

        {/* 2-Second Peak-Hold Amplitude Meter & Readout */}
        <div
          ref={peakContainerRef}
          data-testid="voice-peak-hold"
          data-peak-amplitude="0.000"
          data-peak-db="-60"
          aria-label="2-second frequency peak-hold indicator"
          className="flex w-56 flex-col items-center gap-1"
        >
          <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-slate-900 border border-sky-400/30">
            <span
              ref={liveFillRef}
              className="absolute inset-y-0 left-0 w-full origin-left bg-gradient-to-r from-sky-400/85 to-teal-300"
              style={{ transform: 'scaleX(0.2)' }}
            />
            <span
              ref={peakMarkerRef}
              data-testid="voice-peak-hold-marker"
              className="absolute inset-y-0 w-[2px] bg-sky-100 shadow-[0_0_6px_rgba(186,230,253,0.95)] transition-[left] duration-75"
              style={{ left: 'calc(20% - 1px)' }}
            />
          </div>
          <span
            ref={peakLabelRef}
            className="font-mono text-[10px] text-sky-100 tabular-nums"
          >
            Peak (2s): 0% · -60.0 dB
          </span>
        </div>
      </div>
    </div>
  );
};
