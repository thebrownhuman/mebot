import { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

export type OrbState = "idle" | "think" | "talk";

const COLORS: Record<OrbState, number> = {
  idle: 0x2f6d5b,
  think: 0xffcc66,
  talk: 0x7dffb0,
};

// pulseRef lets the chat push token-ticks into the animation without re-rendering.
interface OrbProps {
  state: OrbState;
  pulseRef: React.MutableRefObject<number>;
}

function OrbMesh({ state, pulseRef }: OrbProps) {
  const mesh = useRef<THREE.Mesh>(null!);
  const points = useRef<THREE.Points>(null!);
  const mat = useRef<THREE.MeshBasicMaterial>(null!);
  const pmat = useRef<THREE.PointsMaterial>(null!);
  const scaleRef = useRef(1);
  const reduce =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // inner point cloud positions
  const N = 500;
  const positions = useRef<Float32Array>(
    (() => {
      const arr = new Float32Array(N * 3);
      for (let i = 0; i < N; i++) {
        const r = 0.7 + Math.random() * 0.5;
        const a = Math.random() * Math.PI * 2;
        const b = Math.acos(2 * Math.random() - 1);
        arr[i * 3] = r * Math.sin(b) * Math.cos(a);
        arr[i * 3 + 1] = r * Math.sin(b) * Math.sin(a);
        arr[i * 3 + 2] = r * Math.cos(b);
      }
      return arr;
    })(),
  );

  useFrame((_, delta) => {
    const spin = state === "think" ? 0.9 : state === "talk" ? 0.5 : 0.25;
    const target = state === "think" ? 1.12 : state === "talk" ? 1.06 : 1.0;

    if (mesh.current) {
      mesh.current.rotation.y += spin * delta;
      mesh.current.rotation.x += spin * 0.4 * delta;
    }
    if (points.current) points.current.rotation.y -= spin * 0.7 * delta;

    const breathe = reduce ? 1 : 1 + Math.sin(performance.now() * 0.0016) * 0.03;
    scaleRef.current += (target - scaleRef.current) * 0.06;
    let s = scaleRef.current * breathe;

    // token pulse: decays each frame
    if (pulseRef.current > 0) {
      s *= 1 + pulseRef.current * 0.18;
      pulseRef.current *= 0.86;
      if (pulseRef.current < 0.01) pulseRef.current = 0;
    }
    if (mesh.current) mesh.current.scale.setScalar(s);
    if (points.current) points.current.scale.setScalar(s * 1.02);

    const c = COLORS[state];
    if (mat.current) mat.current.color.setHex(c);
    if (pmat.current) pmat.current.color.setHex(state === "idle" ? 0x7dffb0 : c);
  });

  return (
    <>
      <mesh ref={mesh}>
        <icosahedronGeometry args={[1, 2]} />
        <meshBasicMaterial ref={mat} color={0x2f6d5b} wireframe transparent opacity={0.55} />
      </mesh>
      <points ref={points}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            count={N}
            array={positions.current}
            itemSize={3}
          />
        </bufferGeometry>
        <pointsMaterial ref={pmat} color={0x7dffb0} size={0.022} transparent opacity={0.7} />
      </points>
    </>
  );
}

export default function Orb({ state, pulseRef }: OrbProps) {
  return (
    <div className="fixed inset-0 z-0 opacity-90">
      <Canvas camera={{ position: [0, 0, 3.2], fov: 50 }} dpr={[1, 2]}>
        <OrbMesh state={state} pulseRef={pulseRef} />
      </Canvas>
    </div>
  );
}
