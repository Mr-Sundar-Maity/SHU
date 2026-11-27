import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { useShu } from '../context/ShuContext';
import type { AssistantState, ShuTab } from '../types/shu';
import { getHoloColorTheme, type HoloColorThemeId } from '../utils/colorTheme';

interface LiveStateRef {
  assistantState: AssistantState;
  audioLevel: number;
  activeTab: ShuTab;
  colorTheme: HoloColorThemeId;
  reducedMotion: boolean;
}

function resolveCorePalette(
  state: AssistantState,
  colorTheme: HoloColorThemeId
): { primary: number; secondary: number; speed: number } {
  if (state === 'stopped') {
    return { primary: 0xf43f5e, secondary: 0x9f1239, speed: 0.12 };
  }
  const theme = getHoloColorTheme(colorTheme);
  switch (state) {
    case 'listening':
      return { primary: theme.secondaryHex, secondary: theme.accentHex, speed: 1.05 };
    case 'thinking':
      return { primary: theme.accentHex, secondary: theme.primaryHex, speed: 1.45 };
    case 'speaking':
      return { primary: theme.accentHex, secondary: theme.secondaryHex, speed: 1.2 };
    case 'ready':
    default:
      return { primary: theme.primaryHex, secondary: theme.secondaryHex, speed: 0.45 };
  }
}

// Reusable scratch objects outside render loop (zero GC)
const _targetColor = new THREE.Color();
const _targetSecondary = new THREE.Color();

function createRadialShadowTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    const grad = ctx.createRadialGradient(128, 128, 10, 128, 128, 124);
    grad.addColorStop(0, 'rgba(2, 6, 16, 0.72)');
    grad.addColorStop(0.55, 'rgba(2, 6, 16, 0.3)');
    grad.addColorStop(1, 'rgba(2, 6, 16, 0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 256, 256);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function createCalibrationGridTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    ctx.clearRect(0, 0, 512, 512);
    const cx = 256;
    const cy = 256;

    const rings = [80, 136, 192, 236];
    rings.forEach((r, idx) => {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.strokeStyle = idx % 2 === 0 ? 'rgba(56, 189, 248, 0.24)' : 'rgba(148, 163, 184, 0.12)';
      ctx.lineWidth = idx === 2 ? 1.5 : 1;
      ctx.stroke();
    });

    for (let i = 0; i < 36; i += 1) {
      const ang = (i / 36) * Math.PI * 2;
      const inner = i % 3 === 0 ? 182 : 188;
      const outer = 196;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(ang) * inner, cy + Math.sin(ang) * inner);
      ctx.lineTo(cx + Math.cos(ang) * outer, cy + Math.sin(ang) * outer);
      ctx.strokeStyle = i % 3 === 0 ? 'rgba(103, 232, 249, 0.45)' : 'rgba(148, 163, 184, 0.2)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export const HologramCore: React.FC = () => {
  const { assistantState, audioLevel, activeTab, settings } = useShu();
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [webglUnavailable, setWebglUnavailable] = useState(false);
  const forceTickRef = useRef<(() => void) | null>(null);

  const liveRef = useRef<LiveStateRef>({
    assistantState,
    audioLevel,
    activeTab,
    colorTheme: settings.colorTheme,
    reducedMotion: false,
  });

  liveRef.current.assistantState = assistantState;
  liveRef.current.audioLevel = audioLevel;
  liveRef.current.activeTab = activeTab;
  liveRef.current.colorTheme = settings.colorTheme;

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    liveRef.current.reducedMotion = Boolean(mq?.matches);
    forceTickRef.current?.();
  }, [assistantState, audioLevel, activeTab, settings.colorTheme]);

  useEffect(() => {
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
        powerPreference: 'high-performance',
        alpha: false,
        preserveDrawingBuffer: true,
      });
    } catch {
      setWebglUnavailable(true);
      return;
    }

    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;

    renderer.setSize(width, height);
    renderer.setPixelRatio(isSoftwareGl ? 1 : Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.shadowMap.enabled = !isSoftwareGl;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(renderer.domElement);

    const onContextLost = (e: Event) => {
      e.preventDefault();
    };
    renderer.domElement.addEventListener('webglcontextlost', onContextLost);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x060911);
    scene.fog = new THREE.FogExp2(0x060911, 0.042);

    const pmrem = new THREE.PMREMGenerator(renderer);
    const roomEnv = new RoomEnvironment();
    scene.environment = pmrem.fromScene(roomEnv, 0.04).texture;
    roomEnv.dispose();
    pmrem.dispose();

    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 80);
    camera.position.set(0, 0.55, 6.2);

    // Three-point studio lighting rig
    const keyLight = new THREE.DirectionalLight(0xfff1e0, 1.35);
    keyLight.position.set(4.5, 6.5, 4.0);
    scene.add(keyLight);

    const hemiLight = new THREE.HemisphereLight(0x7dd3fc, 0x0b1222, 0.75);
    scene.add(hemiLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 1.45);
    rimLight.position.set(-4.2, 2.5, -4.5);
    scene.add(rimLight);

    // Master holographic assembly
    const holoRoot = new THREE.Group();
    scene.add(holoRoot);

    const coreGroup = new THREE.Group();
    coreGroup.position.set(0, 0.25, 0);
    holoRoot.add(coreGroup);

    // 1. Inner crystalline neural icosahedron
    const innerGeo = new THREE.IcosahedronGeometry(0.58, 2);
    const innerMat = new THREE.MeshPhysicalMaterial({
      color: 0x0c1b33,
      emissive: 0x38bdf8,
      emissiveIntensity: 0.72,
      roughness: 0.18,
      metalness: 0.85,
      clearcoat: 1.0,
      flatShading: true,
    });
    const innerMesh = new THREE.Mesh(innerGeo, innerMat);
    coreGroup.add(innerMesh);

    // 2. Volumetric Fresnel holographic shader shell
    const shellGeo = new THREE.SphereGeometry(0.92, 36, 28);
    const shellMat = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uAudio: { value: 0 },
        uColor: { value: new THREE.Color(0x38bdf8) },
      },
      vertexShader: `
        uniform float uTime;
        uniform float uAudio;
        varying vec3 vNormal;
        varying vec3 vWorldPos;
        varying vec2 vUv;

        void main() {
          vUv = uv;
          float wave = sin(position.y * 7.0 - uTime * 2.4) * cos(position.x * 5.0 + uTime * 1.6);
          vec3 displaced = position + normal * (wave * (0.014 + uAudio * 0.085));
          vec4 worldPos = modelMatrix * vec4(displaced, 1.0);
          vWorldPos = worldPos.xyz;
          vNormal = normalize(mat3(modelMatrix) * normal);
          gl_Position = projectionMatrix * viewMatrix * worldPos;
        }
      `,
      fragmentShader: `
        uniform float uTime;
        uniform float uAudio;
        uniform vec3 uColor;
        varying vec3 vNormal;
        varying vec3 vWorldPos;
        varying vec2 vUv;

        void main() {
          vec3 viewDir = normalize(cameraPosition - vWorldPos);
          float fresnel = pow(1.0 - max(0.0, dot(viewDir, normalize(vNormal))), 2.6);
          float scan = 0.72 + 0.28 * sin(vWorldPos.y * 42.0 - uTime * 3.5);
          float alpha = clamp(fresnel * (0.65 + uAudio * 0.35) * scan, 0.04, 0.78);
          vec3 col = uColor * (0.9 + fresnel * 0.85);
          gl_FragColor = vec4(col, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const shellMesh = new THREE.Mesh(shellGeo, shellMat);
    shellMesh.renderOrder = 2;
    coreGroup.add(shellMesh);

    // 3. Outer geodesic wireframe lattice
    const latticeGeo = new THREE.IcosahedronGeometry(1.12, 1);
    const latticeMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      wireframe: true,
      transparent: true,
      opacity: 0.2,
    });
    const latticeMesh = new THREE.Mesh(latticeGeo, latticeMat);
    coreGroup.add(latticeMesh);

    // 4. Equatorial brushed titanium gyro ring
    const ringGeoA = new THREE.TorusGeometry(1.42, 0.022, 16, 96);
    const ringMatA = new THREE.MeshStandardMaterial({
      color: 0x94a3b8,
      metalness: 0.92,
      roughness: 0.22,
    });
    const ringA = new THREE.Mesh(ringGeoA, ringMatA);
    ringA.rotation.x = Math.PI * 0.38;
    coreGroup.add(ringA);

    // 5. Inclined harmonic phase ring
    const ringGeoB = new THREE.TorusGeometry(1.66, 0.013, 14, 96);
    const ringMatB = new THREE.MeshStandardMaterial({
      color: 0x38bdf8,
      emissive: 0x0ea5e9,
      emissiveIntensity: 0.45,
      metalness: 0.7,
      roughness: 0.35,
    });
    const ringB = new THREE.Mesh(ringGeoB, ringMatB);
    ringB.rotation.x = -Math.PI * 0.21;
    ringB.rotation.y = Math.PI * 0.18;
    coreGroup.add(ringB);

    // 6. Instanced telemetry beacons along ringA
    const beaconCount = 8;
    const beaconGeo = new THREE.OctahedronGeometry(0.036, 0);
    const beaconMat = new THREE.MeshStandardMaterial({
      color: 0xe0f2fe,
      emissive: 0x38bdf8,
      emissiveIntensity: 0.9,
      metalness: 0.4,
      roughness: 0.2,
    });
    const beaconMesh = new THREE.InstancedMesh(beaconGeo, beaconMat, beaconCount);
    const dummy = new THREE.Object3D();
    for (let i = 0; i < beaconCount; i += 1) {
      const ang = (i / beaconCount) * Math.PI * 2;
      dummy.position.set(Math.cos(ang) * 1.42, Math.sin(ang) * 1.42, 0);
      dummy.rotation.set(0, 0, ang);
      dummy.updateMatrix();
      beaconMesh.setMatrixAt(i, dummy.matrix);
    }
    beaconMesh.instanceMatrix.needsUpdate = true;
    beaconMesh.computeBoundingSphere();
    ringA.add(beaconMesh);

    // 7. Acoustic particle halo
    const particleCount = 240;
    const basePositions = new Float32Array(particleCount * 3);
    const currentPositions = new Float32Array(particleCount * 3);
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < particleCount; i += 1) {
      const y = 1 - (i / (particleCount - 1)) * 2;
      const radiusAtY = Math.sqrt(1 - y * y);
      const theta = goldenAngle * i;
      const r = 1.28 + (i % 3) * 0.08;
      const px = Math.cos(theta) * radiusAtY * r;
      const py = y * r;
      const pz = Math.sin(theta) * radiusAtY * r;
      basePositions[i * 3] = px;
      basePositions[i * 3 + 1] = py;
      basePositions[i * 3 + 2] = pz;
      currentPositions[i * 3] = px;
      currentPositions[i * 3 + 1] = py;
      currentPositions[i * 3 + 2] = pz;
    }
    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute('position', new THREE.BufferAttribute(currentPositions, 3));
    const particleMat = new THREE.PointsMaterial({
      color: 0x7dd3fc,
      size: 0.028,
      transparent: true,
      opacity: 0.72,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const particles = new THREE.Points(particleGeo, particleMat);
    coreGroup.add(particles);

    // 8. Grounded holographic emitter pedestal (LatheGeometry) + contact shadow + calibration floor ring
    const floorY = -1.85;
    const lathePoints = [
      new THREE.Vector2(0.01, 0),
      new THREE.Vector2(0.95, 0),
      new THREE.Vector2(0.92, 0.06),
      new THREE.Vector2(0.76, 0.09),
      new THREE.Vector2(0.72, 0.14),
      new THREE.Vector2(0.45, 0.16),
      new THREE.Vector2(0.01, 0.14),
    ];
    const pedestalGeo = new THREE.LatheGeometry(lathePoints, 48);
    const pedestalMat = new THREE.MeshStandardMaterial({
      color: 0x111a2c,
      metalness: 0.88,
      roughness: 0.32,
    });
    const pedestalMesh = new THREE.Mesh(pedestalGeo, pedestalMat);
    pedestalMesh.position.set(0, floorY, 0);
    holoRoot.add(pedestalMesh);

    const apertureGeo = new THREE.RingGeometry(0.32, 0.43, 48);
    const apertureMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.65,
    });
    const apertureMesh = new THREE.Mesh(apertureGeo, apertureMat);
    apertureMesh.rotation.x = -Math.PI / 2;
    apertureMesh.position.set(0, floorY + 0.165, 0);
    holoRoot.add(apertureMesh);

    const shadowTex = createRadialShadowTexture();
    const shadowGeo = new THREE.CircleGeometry(1.55, 36);
    const shadowMat = new THREE.MeshBasicMaterial({
      map: shadowTex,
      transparent: true,
      depthWrite: false,
      opacity: 0.55,
    });
    const shadowDisc = new THREE.Mesh(shadowGeo, shadowMat);
    shadowDisc.rotation.x = -Math.PI / 2;
    shadowDisc.position.set(0, floorY + 0.012, 0);
    holoRoot.add(shadowDisc);

    const gridTex = createCalibrationGridTexture();
    gridTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const gridGeo = new THREE.CircleGeometry(2.65, 48);
    const gridMat = new THREE.MeshBasicMaterial({
      map: gridTex,
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    });
    const gridDisc = new THREE.Mesh(gridGeo, gridMat);
    gridDisc.rotation.x = -Math.PI / 2;
    gridDisc.position.set(0, floorY + 0.022, 0);
    holoRoot.add(gridDisc);

    // 9. Projection cone from emitter up to core
    const coneGeo = new THREE.CylinderGeometry(0.95, 0.36, 1.9, 32, 1, true);
    const coneMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.06,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const coneMesh = new THREE.Mesh(coneGeo, coneMat);
    coneMesh.position.set(0, floorY + 1.1, 0);
    holoRoot.add(coneMesh);

    if (!isSoftwareGl) {
      renderer.compile(scene, camera);
    }

    // Gentle pointer parallax drag
    let pointerX = 0;
    let pointerY = 0;
    let dragRotY = 0;
    let dragRotX = 0;
    let dragging = false;
    let lastPtrX = 0;
    let lastPtrY = 0;

    const onPointerDown = (e: PointerEvent) => {
      if ((e.target as HTMLElement)?.closest('button, input, select, textarea, a, dialog')) return;
      dragging = true;
      lastPtrX = e.clientX;
      lastPtrY = e.clientY;
    };
    const onPointerMove = (e: PointerEvent) => {
      pointerX = (e.clientX / window.innerWidth - 0.5) * 2;
      pointerY = (e.clientY / window.innerHeight - 0.5) * 2;
      if (dragging) {
        dragRotY += (e.clientX - lastPtrX) * 0.005;
        dragRotX = THREE.MathUtils.clamp(dragRotX + (e.clientY - lastPtrY) * 0.003, -0.45, 0.45);
        lastPtrX = e.clientX;
        lastPtrY = e.clientY;
      }
    };
    const onPointerUp = () => {
      dragging = false;
    };

    window.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);

    const onResize = () => {
      const w = container.clientWidth || window.innerWidth;
      const h = container.clientHeight || window.innerHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      renderer.render(scene, camera);
    };
    window.addEventListener('resize', onResize);

    let frameId = 0;
    let disposed = false;
    const startTimeMs = performance.now();
    let prevTimeMs = startTimeMs;
    let smoothAudio = 0;
    let smoothSpeed = 0.45;
    let camTargetZ = 6.6;
    let camTargetY = 0.35;
    let prevTheme = liveRef.current.colorTheme;

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
      const delta = Math.min((nowMs - prevTimeMs) / 1000, 0.1);
      prevTimeMs = nowMs;
      const elapsed = (nowMs - startTimeMs) / 1000;
      const {
        assistantState: state,
        audioLevel: level,
        activeTab: tab,
        colorTheme,
        reducedMotion,
      } = liveRef.current;

      const themeChanged = prevTheme !== colorTheme;
      prevTheme = colorTheme;

      const palette = resolveCorePalette(state, colorTheme);
      _targetColor.setHex(palette.primary);
      _targetSecondary.setHex(palette.secondary);

      const dampFactor = reducedMotion || themeChanged ? 1 : 1 - Math.exp(-5 * delta);
      smoothAudio = THREE.MathUtils.damp(smoothAudio, level, 8, delta);
      smoothSpeed = THREE.MathUtils.damp(smoothSpeed, reducedMotion ? 0 : palette.speed, 4, delta);

      // Smoothly transition colors (snap immediately on explicit theme change)
      innerMat.emissive.lerp(_targetColor, dampFactor || 1);
      shellMat.uniforms.uColor.value.lerp(_targetColor, dampFactor || 1);
      latticeMat.color.lerp(_targetColor, dampFactor || 1);
      ringMatB.color.lerp(_targetColor, dampFactor || 1);
      ringMatB.emissive.lerp(_targetSecondary, dampFactor || 1);
      beaconMat.emissive.lerp(_targetColor, dampFactor || 1);
      particleMat.color.lerp(_targetColor, dampFactor || 1);
      apertureMat.color.lerp(_targetColor, dampFactor || 1);
      coneMat.color.lerp(_targetColor, dampFactor || 1);
      rimLight.color.lerp(_targetColor, dampFactor || 1);
      hemiLight.color.lerp(_targetSecondary, dampFactor || 1);

      // Update shaders and audio scale
      shellMat.uniforms.uTime.value = elapsed;
      shellMat.uniforms.uAudio.value = smoothAudio;

      const coreScale = 1 + smoothAudio * 0.18 + (reducedMotion ? 0 : Math.sin(elapsed * 2.1) * 0.025);
      innerMesh.scale.setScalar(coreScale);
      innerMat.emissiveIntensity = 0.68 + smoothAudio * 0.85;

      // Animate gyroscopes & lattice
      if (!reducedMotion) {
        innerMesh.rotation.y += delta * 0.45 * smoothSpeed;
        innerMesh.rotation.x += delta * 0.22 * smoothSpeed;
        latticeMesh.rotation.y -= delta * 0.28 * smoothSpeed;
        ringA.rotation.z += delta * 0.35 * smoothSpeed;
        ringB.rotation.z -= delta * 0.52 * smoothSpeed;
        coreGroup.position.y = 0.25 + Math.sin(elapsed * 1.4) * 0.045;
        gridDisc.rotation.z += delta * 0.08;
      }

      // Acoustic particle wave displacement
      if (!reducedMotion) {
        const posAttr = particleGeo.getAttribute('position') as THREE.BufferAttribute;
        const arr = posAttr.array as Float32Array;
        const amp = 0.03 + smoothAudio * 0.16;
        for (let i = 0; i < particleCount; i += 1) {
          const ix = i * 3;
          const bx = basePositions[ix];
          const by = basePositions[ix + 1];
          const bz = basePositions[ix + 2];
          const pulse = 1 + Math.sin(elapsed * 2.6 + by * 3.5 + bx * 2.1) * amp;
          arr[ix] = bx * pulse;
          arr[ix + 1] = by * pulse;
          arr[ix + 2] = bz * pulse;
        }
        posAttr.needsUpdate = true;
        particles.rotation.y += delta * 0.18 * smoothSpeed;
      }

      // Camera & parallax framing per tab
      const desiredZ = tab === 'assistant' ? 6.6 : 7.35;
      const desiredY = tab === 'assistant' ? 0.32 : 0.62;
      camTargetZ = THREE.MathUtils.damp(camTargetZ, desiredZ, 4, delta);
      camTargetY = THREE.MathUtils.damp(camTargetY, desiredY, 4, delta);

      camera.position.x = THREE.MathUtils.damp(camera.position.x, pointerX * 0.24, 3.5, delta);
      camera.position.y = camTargetY + THREE.MathUtils.damp(0, -pointerY * 0.16, 3.5, delta);
      camera.position.z = camTargetZ;
      camera.lookAt(0, tab === 'assistant' ? -0.08 : 0.1, 0);

      holoRoot.rotation.y = THREE.MathUtils.damp(holoRoot.rotation.y, dragRotY, 6, delta);
      holoRoot.rotation.x = THREE.MathUtils.damp(holoRoot.rotation.x, dragRotX, 6, delta);

      renderer.render(scene, camera);

      if (isSoftwareGl) {
        afterDraw(tick);
      } else {
        frameId = requestAnimationFrame(tick);
      }
    }

    forceTickRef.current = () => {
      if (disposed) return;
      const { assistantState: state, colorTheme } = liveRef.current;
      prevTheme = colorTheme;
      const palette = resolveCorePalette(state, colorTheme);
      _targetColor.setHex(palette.primary);
      _targetSecondary.setHex(palette.secondary);
      innerMat.emissive.copy(_targetColor);
      shellMat.uniforms.uColor.value.copy(_targetColor);
      latticeMat.color.copy(_targetColor);
      ringMatB.color.copy(_targetColor);
      ringMatB.emissive.copy(_targetSecondary);
      beaconMat.emissive.copy(_targetColor);
      particleMat.color.copy(_targetColor);
      apertureMat.color.copy(_targetColor);
      coneMat.color.copy(_targetColor);
      rimLight.color.copy(_targetColor);
      hemiLight.color.copy(_targetSecondary);
      renderer.render(scene, camera);
    };

    tick();

    return () => {
      disposed = true;
      forceTickRef.current = null;
      cancelAnimationFrame(frameId);
      clearTimeout(frameId);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      renderer.domElement.removeEventListener('webglcontextlost', onContextLost);

      innerGeo.dispose();
      innerMat.dispose();
      shellGeo.dispose();
      shellMat.dispose();
      latticeGeo.dispose();
      latticeMat.dispose();
      ringGeoA.dispose();
      ringMatA.dispose();
      ringGeoB.dispose();
      ringMatB.dispose();
      beaconGeo.dispose();
      beaconMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      pedestalGeo.dispose();
      pedestalMat.dispose();
      apertureGeo.dispose();
      apertureMat.dispose();
      shadowTex.dispose();
      shadowGeo.dispose();
      shadowMat.dispose();
      gridTex.dispose();
      gridGeo.dispose();
      gridMat.dispose();
      coneGeo.dispose();
      coneMat.dispose();
      if (scene.environment) scene.environment.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-0 overflow-hidden bg-[#060911]"
      aria-hidden="true"
    >
      <div
        ref={mountRef}
        data-testid="hologram-canvas-mount"
        className="w-full h-full"
      />
      {webglUnavailable && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-72 h-72 rounded-full border border-sky-400/30 bg-radial from-sky-500/20 via-sky-900/10 to-transparent" />
        </div>
      )}
    </div>
  );
};
